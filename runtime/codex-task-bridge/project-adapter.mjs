// A fixed, operator-selected connection to the existing Project owner. No new store.
import { createHash } from "node:crypto";
import { resolve, join, isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";
import { validateProjectView, validateProjectInspection, validateProjectInput } from "../cloudflare-os-kotodama/gatekeeper-kotodama-brief/src/project-protocol.mjs";

const closed = (v, keys) => v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const hex = v => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const fail = () => { throw new Error("project_connection_denied"); };
const hash = v => createHash("sha256").update(JSON.stringify(v)).digest("hex");

async function connectRuntime(binding) {
  const { sourceSnapshot } = await import("../discord-template/src/source-bootstrap.mjs");
  const root = resolve(binding.runtimeRoot);
  const snapshot = async () => {
    const value = await sourceSnapshot(root);
    if (value.binding.setDigest !== binding.sourceSetDigest) fail();
    return value;
  };
  const before = await snapshot();
  const { loadConfig } = await import(pathToFileURL(join(root, "src/config.mjs")).href);
  const { controlCommand } = await import(pathToFileURL(join(root, "src/runtime.mjs")).href);
  const after = await snapshot();
  if (before.metadataDigest !== after.metadataDigest) fail();
  const initial = await loadConfig(binding.configFile);
  const identity = config => JSON.stringify([config.installation, config.dataDir, config.owner]);
  const permitted = (config, operation) => {
    if (identity(config) !== identity(initial) || config.owner?.kind !== "local"
      || !config.discord?.operators?.includes(binding.actorId)
      || !config.projects.operations?.includes(operation)) fail();
  };
  return async input => {
    await snapshot();
    const current = await loadConfig(binding.configFile); permitted(current, input.operation);
    const status = await controlCommand(current, { action: "status" });
    // Only the running official bootstrap can establish its loaded source set.
    if (status.source?.error || status.source?.setDigest !== binding.sourceSetDigest) fail();
    const result = await controlCommand(current, input);
    permitted(await loadConfig(binding.configFile), input.operation);
    await snapshot();
    const finalStatus = await controlCommand(current, { action: "status" });
    if (finalStatus.source?.error || finalStatus.source?.setDigest !== binding.sourceSetDigest) fail();
    return result;
  };
}

export async function createProjectAdapter(config, { connect = connectRuntime, now = Date.now } = {}) {
  if (config === undefined) return null;
  if (!closed(config, ["requesterRef", "actorId", "projectId", "source", "expiresAt", "operations", "runtimeRoot", "configFile", "sourceSetDigest"])
    || typeof config.requesterRef !== "string" || !/^urn:kotodama:principal:[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(config.requesterRef)
    || typeof config.actorId !== "string" || !/^\d{5,24}$/.test(config.actorId)
    || typeof config.projectId !== "string" || !/^ref\/[A-Za-z0-9][A-Za-z0-9._/@-]{1,180}$/.test(config.projectId)
    || !closed(config.source, ["key", "revision"]) || !hex(config.source.key)
    || !Number.isSafeInteger(config.source.revision) || config.source.revision < 0
    || !Array.isArray(config.operations) || !config.operations.includes("read") || config.operations.length > 2
    || new Set(config.operations).size !== config.operations.length || config.operations.some(v => !["read", "inspect"].includes(v))
    || typeof config.expiresAt !== "string" || !Number.isFinite(Date.parse(config.expiresAt)) || new Date(config.expiresAt).toISOString() !== config.expiresAt
    || ![config.runtimeRoot, config.configFile].every(v => typeof v === "string" && isAbsolute(v)) || !hex(config.sourceSetDigest)) fail();
  const binding = structuredClone(config);
  Object.freeze(binding.source); Object.freeze(binding.operations); Object.freeze(binding);
  const bindingDigest = hash(Object.keys(binding).sort().map(k => [k, binding[k]]));
  const invoke = await connect(binding);
  const admitted = (principal, operation) => {
    if (principal !== binding.requesterRef || now() >= Date.parse(binding.expiresAt) || !binding.operations.includes(operation)) fail();
  };
  return { bindingDigest, requesterRef: binding.requesterRef,
    async read(principal) {
      admitted(principal, "read");
      const view = validateProjectView(await invoke({ action: "project", actor: binding.actorId, operation: "read", project_id: binding.projectId }), binding.projectId);
      admitted(principal, "read");
      return { state: "connected", binding_sha256: bindingDigest, can_inspect: binding.operations.includes("inspect"), view };
    },
    async inspect(principal, body) {
      admitted(principal, "inspect"); validateProjectInput(body);
      if (body.binding_sha256 !== bindingDigest) fail();
      const { binding_sha256, ...input } = body;
      const inspection = validateProjectInspection(await invoke({ ...input, action: "project", actor: binding.actorId, operation: "inspect",
        project_id: binding.projectId, source: structuredClone(binding.source) }), binding.projectId, body);
      admitted(principal, "inspect");
      return { binding_sha256: bindingDigest, inspection };
    },
  };
}
