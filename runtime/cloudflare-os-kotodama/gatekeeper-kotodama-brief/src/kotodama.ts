import { DurableObject, RpcTarget, WorkerEntrypoint, RpcStub } from "cloudflare:workers";
import { skipRpcValidation, validateRpc } from "capnweb-validate";
import type { AccountDescription, ActionKind, ApprovalQueue, Gatekeeper, GatekeeperConnectCallback,
  GatekeeperUser, GatekeeperUserVerifier, ResourceDescription, ResourceConfiguratorFrame,
  SupportedResource, VendorDescription } from "@gadgets/workshop-shared/gatekeeper";
import CONFIGURATOR from "./generated/brief-configurator-ui.txt";
import { validateAdmission, validateSource, validateQueued, validateResult, validateRevoked } from "./protocol.mjs";

// Logical resource identity only; no request is ever sent to this reserved domain.
const RESOURCE = "https://requirements.kotodama.invalid/current";
const RESOURCES: SupportedResource[] = [{ urlPattern: RESOURCE, title: "Kotodamaの要件整理", description: "許可された依頼の要件案と検証結果。" }];
const ICON = { url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23243e36'/%3E%3Cpath d='M9 8v16M10 17l12-9M10 17l12 7' stroke='white' stroke-width='3'/%3E%3C/svg%3E" };
const TYPES = `
interface KotodamaBriefSource { handoff_id: string; revision: number; overview: string; binding_sha256: string; }
interface KotodamaBrief { objective: string; deliverable: string; constraints: string[]; acceptance_criteria: string[]; open_questions: string[]; }
interface KotodamaBriefResult { request_id: string; state: string; brief: KotodamaBrief | null; task_state_changed: false; publication: false; }
interface KotodamaTaskBrief {
  getSource(): Promise<KotodamaBriefSource>;
  requestBrief(requestId: string, sourceRevision: number, bindingSha256: string): Promise<{actionId:number}>;
  getResult(requestId: string): Promise<KotodamaBriefResult>;
}
`;
type Props = { principalRef: string };
type BriefSource = { handoff_id: string; revision: number; overview: string; binding_sha256: string };
type Brief = { objective: string; deliverable: string; constraints: string[]; acceptance_criteria: string[]; open_questions: string[] };
type BriefResult = { request_id: string; state: string; brief: Brief | null; task_state_changed: false; publication: false };
type Action = { requestId: string; sourceRevision: number; bindingSha256: string; state: "pending" | "submitted" | "rejected" };
interface Session {
  getSource(): Promise<BriefSource>;
  requestBrief(requestId: string, sourceRevision: number, bindingSha256: string): Promise<{ actionId: number }>;
  getResult(requestId: string): Promise<BriefResult>;
}
interface VerifierApi extends GatekeeperUserVerifier { identify(): Promise<string>; }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function accountState(exports: Cloudflare.Exports, principalRef: string) {
  return exports.AccountState.getByName(principalRef);
}
async function bridge(env: Cloudflare.Env, principalRef: string, path: string, body?: unknown): Promise<unknown> {
  const origin = new URL(env.KOTODAMA_BRIDGE_ORIGIN);
  if (!["http:", "https:"].includes(origin.protocol) || origin.pathname !== "/" || origin.search || origin.hash || origin.username || origin.password
    || !/^[0-9a-f]{64}$/.test(env.KOTODAMA_BRIDGE_SECRET)) throw new Error("実行サービスの設定を確認してください。");
  const response = await fetch(new URL(path, origin), { method: body === undefined ? "GET" : "POST", redirect: "error",
    headers: { authorization: `Bearer ${env.KOTODAMA_BRIDGE_SECRET}`, "x-kotodama-principal": principalRef, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15_000) });
  if (!response.ok) { await response.body?.cancel(); throw new Error("この依頼を利用できません。権限・期限・接続を確認してください。"); }
  const reader = response.body?.getReader(); if (!reader) throw new Error("応答がありません。");
  const chunks: Uint8Array[] = []; let size = 0;
  while (true) { const next = await reader.read(); if (next.done) break; size += next.value.length;
    if (size > 65536) { await reader.cancel(); throw new Error("応答が大きすぎます。"); } chunks.push(next.value); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
}

@validateRpc()
export class AccountState extends DurableObject<Cloudflare.Env> {
  isRevoked(): boolean { return this.ctx.storage.kv.get<boolean>("revoked") === true; }
  revoke(): void { this.ctx.storage.kv.put("revoked", true); }
}

@validateRpc()
export class GatekeeperVendor extends WorkerEntrypoint<Cloudflare.Env> {
  async describe(): Promise<VendorDescription> {
    return { displayName: "Kotodama 要件整理", url: "https://github.com/Kotodama-Project/Kotodama-project", logo: ICON,
      tagline: "閲覧許可と実行許可を確認して、Codexで要件案を作る。", autoProvisionsAccount: true };
  }
  @skipRpcValidation()
  async createAccount(): Promise<Fetcher<GatekeeperUser>> {
    return this.ctx.exports.UserAccount({ props: { principalRef: `urn:kotodama:principal:${crypto.randomUUID()}` } });
  }
  async getSupportedResources(): Promise<SupportedResource[]> { return RESOURCES; }
  async getTypeScriptTypes(): Promise<string> { return TYPES; }
  async connectAccount(_callback: Fetcher<GatekeeperConnectCallback>): Promise<{ url: string }> {
    throw new Error("OSの利用者に内部IDを割り当てます。別の認証情報は入力しません。");
  }
}

@validateRpc()
export class UserAccount extends WorkerEntrypoint<Cloudflare.Env, Props> implements GatekeeperUser {
  async describe(): Promise<AccountDescription> {
    return { displayName: "このOS利用者のKotodama接続", uniqueName: this.ctx.props.principalRef, avatar: ICON };
  }
  async getSupportedResources(): Promise<SupportedResource[]> { return RESOURCES; }
  async getGatekeeperClassFor(url: string) {
    if (url !== RESOURCE || await accountState(this.ctx.exports, this.ctx.props.principalRef).isRevoked()) throw new Error("接続は利用できません。");
    return { class: this.ctx.exports.KotodamaGatekeeper({ props: this.ctx.props }), resource: RESOURCES[0]! };
  }
  @skipRpcValidation()
  async getVerifier(): Promise<Fetcher<VerifierApi>> { return this.ctx.exports.UserVerifier({ props: this.ctx.props }); }
  async ensureResources(_patterns: string[]): Promise<{ url?: string }> { return {}; }
  async getAuthenticatedEmail(): Promise<null> { return null; }
  async startResourceConfigurator(pattern: string): Promise<ResourceConfiguratorFrame> {
    if (pattern !== RESOURCE) throw new Error("対応する依頼を選んでください。");
    return { iframeHtml: CONFIGURATOR, ui: new RpcStub(new Configurator()) };
  }
  async revoke(): Promise<void> {
    await accountState(this.ctx.exports, this.ctx.props.principalRef).revoke();
    validateRevoked(await bridge(this.env, this.ctx.props.principalRef, "/v1/revoke", {}));
  }
  async reconnect(): Promise<{ url: string }> { throw new Error("新しい内部IDと権限の確認が必要です。"); }
}

@validateRpc()
class Configurator extends RpcTarget { async resourceUrl(): Promise<string> { return RESOURCE; } }

@validateRpc()
export class UserVerifier extends WorkerEntrypoint<Cloudflare.Env, Props> implements VerifierApi {
  async identify(): Promise<string> {
    if (await accountState(this.ctx.exports, this.ctx.props.principalRef).isRevoked()) throw new Error("接続は取り消されています。");
    return this.ctx.props.principalRef;
  }
}

@validateRpc()
class BriefSession extends RpcTarget implements Session {
  #queue: RpcStub<ApprovalQueue>;
  #gatekeeper: KotodamaGatekeeper;
  constructor(queue: RpcStub<ApprovalQueue>, gatekeeper: KotodamaGatekeeper) { super(); this.#queue = queue.dup(); this.#gatekeeper = gatekeeper; }
  async getSource(): Promise<BriefSource> {
    await this.#queue.authorizeObservation({ title: "依頼を読む", description: "閲覧を許可された依頼だけを取得します。" });
    return this.#gatekeeper.readSource();
  }
  async requestBrief(requestId: string, sourceRevision: number, bindingSha256: string): Promise<{ actionId: number }> {
    const actionId = await this.#gatekeeper.stage(requestId, sourceRevision, bindingSha256);
    try {
      await this.#queue.submitAction(actionId, { title: "Codexで要件案を作る", description: "この依頼だけをCodex契約で整理します。ファイルや外部サービスの変更は行いません。",
        implementsRevert: false, awaitDecision: true, actionKind: { tag: "draft-requirements", label: "要件案の作成" } });
      return { actionId };
    } catch (error) { await this.#gatekeeper.rejectAction(actionId); throw error; }
  }
  async getResult(requestId: string): Promise<BriefResult> {
    if (!UUID.test(requestId)) throw new Error("依頼を確認してください。");
    await this.#queue.authorizeObservation({ title: "要件案を読む", description: "元の情報と実行許可を再確認して結果を取得します。" });
    return this.#gatekeeper.readResult(requestId);
  }
  [Symbol.dispose](): void { this.#queue[Symbol.dispose](); }
}

@validateRpc()
export class KotodamaGatekeeper extends DurableObject<Cloudflare.Env, Props> implements Gatekeeper<Session> {
  async describe(): Promise<ResourceDescription> {
    return { url: RESOURCE, title: "Kotodamaの要件整理", snippet: "一つの許可された依頼を整理する。", suggestedBindingName: "KOTODAMA_BRIEF", tsType: "KotodamaTaskBrief" };
  }
  async getTypeScriptTypes(): Promise<string> { return TYPES; }
  async getAutoApprovableActions(): Promise<ActionKind[]> { return []; }
  async startSession(queue: RpcStub<ApprovalQueue>): Promise<Session> { return new BriefSession(queue, this); }
  async assertConnected(): Promise<void> {
    if (await accountState(this.ctx.exports, this.ctx.props.principalRef).isRevoked()) throw new Error("接続は取り消されています。");
  }
  async addObserver(id: string, user: Fetcher<VerifierApi>): Promise<void> {
    await this.assertConnected();
    if (await user.identify() !== this.ctx.props.principalRef) throw new Error("この利用者には共有できません。");
    await this.assertAdmission();
    this.ctx.storage.kv.put(`observer:${id}`, true);
  }
  async removeObserver(id: string): Promise<void> { this.ctx.storage.kv.delete(`observer:${id}`); }
  pinBinding(binding: string): void {
    const pinned = this.ctx.storage.kv.get<string>("binding");
    if (pinned && pinned !== binding) throw new Error("依頼または実行許可が変更されました。接続を確認してください。");
    this.ctx.storage.kv.put("binding", binding);
  }
  async assertAdmission(): Promise<void> {
    await this.assertConnected();
    const result = validateAdmission(await bridge(this.env, this.ctx.props.principalRef, "/v1/admission"));
    this.pinBinding(result.binding_sha256);
  }
  async readSource(): Promise<BriefSource> {
    await this.assertConnected();
    const source = validateSource(await bridge(this.env, this.ctx.props.principalRef, "/v1/handoff"));
    this.pinBinding(source.binding_sha256);
    return source;
  }
  async readResult(requestId: string): Promise<BriefResult> {
    if (!UUID.test(requestId)) throw new Error("依頼を確認してください。");
    await this.assertAdmission();
    const id = this.ctx.storage.kv.get<number>(`request:${requestId}`);
    const action = id === undefined ? undefined : this.ctx.storage.kv.get<Action>(`action:${id}`);
    if (!action) throw new Error("依頼を確認してください。");
    if (action.state !== "submitted") return { request_id: requestId,
      state: action.state === "pending" ? "awaiting_approval" : "rejected", brief: null, task_state_changed: false, publication: false };
    return validateResult(await bridge(this.env, this.ctx.props.principalRef, `/v1/briefs/${requestId}`), requestId);
  }
  async stage(requestId: string, sourceRevision: number, bindingSha256: string): Promise<number> {
    await this.assertConnected();
    if (!UUID.test(requestId) || !Number.isSafeInteger(sourceRevision) || sourceRevision < 1 || !/^[0-9a-f]{64}$/.test(bindingSha256)) throw new Error("依頼を確認してください。");
    const source = await this.readSource();
    if (source.revision !== sourceRevision || source.binding_sha256 !== bindingSha256) throw new Error("依頼が変更されました。");
    const previous = this.ctx.storage.kv.get<number>(`request:${requestId}`);
    if (previous !== undefined) {
      const action = this.ctx.storage.kv.get<Action>(`action:${previous}`);
      if (!action || action.sourceRevision !== sourceRevision || action.bindingSha256 !== bindingSha256) throw new Error("依頼が一致しません。");
      return previous;
    }
    const id = this.ctx.storage.kv.get<number>("next-action") ?? 1;
    if (id > 32) throw new Error("この接続の作業数の上限です。");
    this.ctx.storage.kv.put("next-action", id + 1);
    this.ctx.storage.kv.put(`action:${id}`, { requestId, sourceRevision, bindingSha256, state: "pending" } satisfies Action);
    this.ctx.storage.kv.put(`request:${requestId}`, id);
    return id;
  }
  async applyAction(id: number): Promise<void> {
    await this.assertConnected();
    const action = this.ctx.storage.kv.get<Action>(`action:${id}`);
    if (!action || action.state === "rejected") throw new Error("この操作は利用できません。");
    if (action.state === "submitted") return;
    await this.assertAdmission();
    validateQueued(await bridge(this.env, this.ctx.props.principalRef, "/v1/briefs", {
      request_id: action.requestId, source_revision: action.sourceRevision, binding_sha256: action.bindingSha256 }), action.requestId);
    this.ctx.storage.kv.put(`action:${id}`, { ...action, state: "submitted" });
  }
  async rejectAction(id: number): Promise<void> {
    const action = this.ctx.storage.kv.get<Action>(`action:${id}`);
    if (action?.state === "pending") this.ctx.storage.kv.put(`action:${id}`, { ...action, state: "rejected" });
  }
  async revertAction(_id: number): Promise<void> { throw new Error("モデルに送信済みの処理は巻き戻せません。"); }
}

export default { fetch(): Response { return new Response("Not found", { status: 404 }); } };
