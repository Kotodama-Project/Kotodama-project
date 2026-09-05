import { DurableObject } from "cloudflare:workers";

export class Gadget extends DurableObject {
  async getState() {
    if (!this.env.KOTODAMA_BRIEF) return { state: "not_connected", source: null, result: null };
    const source = await this.env.KOTODAMA_BRIEF.getSource();
    const job = this.ctx.storage.kv.get("current-request");
    if (!job) return { state: "ready_to_request", source, result: null };
    if (job.phase === "awaiting_approval") return { state: "awaiting_approval", source, result: null };
    const result = await this.env.KOTODAMA_BRIEF.getResult(job.requestId);
    return { state: result.state, source, result: result.brief };
  }

  async requestBrief() {
    if (!this.env.KOTODAMA_BRIEF) throw new Error("ConnectionsからKotodamaの接続を設定してください。");
    const source = await this.env.KOTODAMA_BRIEF.getSource();
    // Recheck after the await, then reserve synchronously before another RPC can interleave.
    if (this.ctx.storage.kv.get("current-request")) return this.getState();
    const requestId = crypto.randomUUID();
    this.ctx.storage.kv.put("current-request", { requestId, sourceRevision: source.revision, phase: "awaiting_approval" });
    try {
      await this.env.KOTODAMA_BRIEF.requestBrief(requestId, source.revision);
      this.ctx.storage.kv.put("current-request", { requestId, sourceRevision: source.revision, phase: "submitted" });
      return this.getState();
    } catch (error) {
      // Do not automatically dispatch a new UUID after an uncertain response.
      this.ctx.storage.kv.put("current-request", { requestId, sourceRevision: source.revision, phase: "uncertain" });
      throw error;
    }
  }
}
