// Platform-neutral wire contract, used by the private Node runner and OS boundary.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HEX = /^[0-9a-f]{64}$/;
const FIELDS = ["objective", "deliverable", "constraints", "acceptance_criteria", "open_questions"];
const closed = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
const text = (value, max = 8000) => typeof value === "string" && value.isWellFormed() && value.trim().length > 0
  && new TextEncoder().encode(value).length <= max && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value);
const positive = (value) => Number.isSafeInteger(value) && value > 0;
const hex = (value) => typeof value === "string" && HEX.test(value);
const uuid = (value) => typeof value === "string" && UUID.test(value);
const BRIDGE_STATES = ["running", "ready", "failed", "interrupted"];
const APPROVAL_STATES = ["awaiting_approval", "approval_unknown", "rejected"];
export const SESSION_STATE_TYPE = [...BRIDGE_STATES, ...APPROVAL_STATES].map((state) => JSON.stringify(state)).join(" | ");

export function validateBridgeOrigin(value) {
  if (typeof value !== "string") throw new Error("invalid_bridge_origin");
  const origin = new URL(value);
  if (origin.pathname !== "/" || origin.search || origin.hash || origin.username || origin.password
    || !(origin.protocol === "https:" || (origin.protocol === "http:" && origin.hostname === "127.0.0.1"))) throw new Error("invalid_bridge_origin");
  return origin;
}

export function validateBrief(value) {
  if (!closed(value, FIELDS) || !text(value.objective) || !text(value.deliverable)) throw new Error("invalid_brief");
  for (const key of FIELDS.slice(2)) {
    if (!Array.isArray(value[key]) || value[key].length > 32 || value[key].some((item) => !text(item))) throw new Error("invalid_brief");
  }
  if (!value.constraints.length || !value.acceptance_criteria.length || new TextEncoder().encode(JSON.stringify(value)).length > 32768) throw new Error("invalid_brief");
  return value;
}
export function validateAdmission(value) {
  if (!closed(value, ["allowed", "binding_sha256"]) || value.allowed !== true || !hex(value.binding_sha256)) throw new Error("invalid_admission");
  return value;
}
export function validateSource(value) {
  if (!closed(value, ["handoff_id", "revision", "overview", "binding_sha256"])
    || !text(value.handoff_id, 128) || !/^[a-z0-9][a-z0-9-]{0,127}$/.test(value.handoff_id)
    || !positive(value.revision) || !text(value.overview) || !hex(value.binding_sha256)) throw new Error("invalid_source");
  return value;
}
export function validateQueued(value, requestId) {
  if (!closed(value, ["request_id", "state", "task_state_changed"]) || !uuid(value.request_id) || value.request_id !== requestId
    || !BRIDGE_STATES.includes(value.state) || value.task_state_changed !== false) throw new Error("invalid_queue_response");
  return value;
}
export function validateResult(value, requestId) {
  if (!closed(value, ["request_id", "state", "brief", "task_state_changed", "publication"]) || !uuid(value.request_id) || value.request_id !== requestId
    || !BRIDGE_STATES.includes(value.state)
    || value.task_state_changed !== false || value.publication !== false) throw new Error("invalid_result");
  if (value.state === "ready") validateBrief(value.brief);
  else if (value.brief !== null) throw new Error("invalid_result");
  return value;
}
export function validateSessionResult(value, requestId) {
  if (APPROVAL_STATES.includes(value?.state)) {
    if (!closed(value, ["request_id", "state", "brief", "task_state_changed", "publication"])
      || !uuid(value.request_id) || value.request_id !== requestId || value.brief !== null
      || value.task_state_changed !== false || value.publication !== false) throw new Error("invalid_approval_result");
    return value;
  }
  return validateResult(value, requestId);
}
export function validateRevoked(value) {
  if (!closed(value, ["revoked"]) || value.revoked !== true) throw new Error("invalid_revocation");
  return value;
}
