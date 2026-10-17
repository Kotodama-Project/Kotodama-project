// Closed Project wire contracts. Bounds reject oversized values without truncation.
export const PROJECT_WIRE_BYTES = 750000;
// Reserve 10KB for the fixed command envelope at the owner's 200KB ingress.
export const PROJECT_INSPECTION_BYTES = 190000;
const closed = (v, keys) => v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const check = v => { if (!v) throw new Error("invalid_project_response"); };
const positive = v => Number.isSafeInteger(v) && v > 0;
const sourceRevision = v => Number.isSafeInteger(v) && v >= 0;
const hex = v => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const whitespace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
const text = (v, max) => typeof v === "string" && v.isWellFormed() && !v.includes("\0") && !whitespace.test(v) && [...v].length <= max;
const ref = v => typeof v === "string" && v.isWellFormed() && [...v].length > 0 && [...v].length <= 256 && !/[\x00-\x1f]/.test(v);
const fields = ["outcome", "in_scope", "out_of_scope", "constraints", "acceptance", "unknowns"];
const bounded = (v, limit = PROJECT_WIRE_BYTES) => check(new TextEncoder().encode(JSON.stringify(v)).length <= limit);
const sources = v => check(Array.isArray(v) && v.length <= 256 && v.every(s => closed(s, ["key", "revision", "current_revision", "freshness"])
  && hex(s.key) && sourceRevision(s.revision) && sourceRevision(s.current_revision) && s.current_revision >= s.revision
  && s.freshness === (s.revision === s.current_revision ? "current" : "superseded")));
export function validateProjectTaskRefs(values, version) {
  check(Array.isArray(values) && values.length <= 50);
  // Inspection envelopes remain v1 and do not carry the nested Project version.
  const selected = version ?? (values.length && Object.hasOwn(values[0] ?? {}, "adapter") ? 2 : 1);
  check([1, 2].includes(selected)); const ids = new Set();
  for (const value of values) {
    const local = selected === 2 && value?.adapter === "discord_local_task_v1";
    if (selected === 2) check(["discord_local_task_v1", "swarm_execution_v1"].includes(value?.adapter));
    check(closed(value, local ? ["adapter", "task_id", "revision"]
      : [...(selected === 2 ? ["adapter"] : []), "task_id", "owner_ref", "revision", "context_digest"])
      && typeof value.task_id === "string" && /^task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.task_id)
      && positive(value.revision) && !ids.has(value.task_id));
    if (!local) check(ref(value.owner_ref) && hex(value.context_digest));
    ids.add(value.task_id);
  }
  return values;
}
export function validateProjectBrief(v) {
  check(closed(v, fields) && text(v.outcome, 4000));
  for (const key of fields.slice(1)) check(Array.isArray(v[key]) && v[key].length <= 20 && new Set(v[key]).size === v[key].length && v[key].every(s => text(s, 1000)));
  return v;
}
export function validateProjectView(v, projectId) {
  bounded(v);
  check(closed(v, ["kind", "version", "authority", "project", "project_digest", "snapshot", "current_revision", "source_refs", "task_state_changed", "execution_authorized"])
    && v.kind === "kotodama.project-owner-view" && v.version === 1 && v.authority === "selected_local_project_owner" && v.snapshot === "current"
    && hex(v.project_digest) && v.task_state_changed === false && v.execution_authorized === false);
  const p = v.project;
  check(closed(p, ["version", "project_id", "revision", "owner_ref", "name", "original_ref", "brief", "task_refs"])
    && [1, 2].includes(p.version) && ref(p.project_id) && (projectId === undefined || p.project_id === projectId) && positive(p.revision)
    && p.revision === v.current_revision && ref(p.owner_ref) && ref(p.original_ref) && text(p.name, 200));
  validateProjectTaskRefs(p.task_refs, p.version); validateProjectBrief(p.brief); sources(v.source_refs); return v;
}
export function validateProjectInput(v) {
  bounded(v, PROJECT_INSPECTION_BYTES);
  check(closed(v, ["binding_sha256", "expected_revision", "base_digest", "reason", "brief"])
    && hex(v.binding_sha256) && positive(v.expected_revision) && hex(v.base_digest) && text(v.reason, 1000));
  validateProjectBrief(v.brief); return v;
}
export function validateProjectInspection(v, projectId, input) {
  bounded(v);
  check(closed(v, ["kind", "version", "authority", "project_id", "expected_revision", "base_digest", "proposal_digest", "proposal", "changed_fields", "removed_requirements", "impact_task_refs", "applied", "next_action", "source_refs", "task_state_changed", "execution_authorized"])
    && v.kind === "kotodama.project-change-candidate" && v.version === 1 && v.authority === "candidate_only" && ref(v.project_id)
    && (projectId === undefined || projectId === v.project_id) && positive(v.expected_revision) && hex(v.base_digest) && hex(v.proposal_digest)
    && v.applied === false && v.task_state_changed === false && v.execution_authorized === false && v.next_action === "owner_revalidate_authorize_and_record_correction"
    && Array.isArray(v.changed_fields) && v.changed_fields.length > 0 && v.changed_fields.length <= 6 && new Set(v.changed_fields).size === v.changed_fields.length && v.changed_fields.every(k => fields.includes(k)));
  validateProjectTaskRefs(v.impact_task_refs);
  const p = v.proposal;
  check(closed(p, ["version", "project_id", "expected_revision", "base_digest", "reason", "source_ref", "brief"])
    && p.version === 1 && p.project_id === v.project_id && p.expected_revision === v.expected_revision && p.base_digest === v.base_digest && text(p.reason, 1000) && ref(p.source_ref));
  validateProjectBrief(p.brief);
  check(closed(v.removed_requirements, ["constraints", "acceptance"]));
  for (const values of Object.values(v.removed_requirements)) check(Array.isArray(values) && values.length <= 20 && values.every(s => text(s, 1000)));
  // Inspection source_refs use the exact current source selected by the owner.
  check(Array.isArray(v.source_refs) && v.source_refs.length <= 256 && v.source_refs.every(s => closed(s, ["key", "revision"]) && hex(s.key) && sourceRevision(s.revision)));
  if (input) check(v.expected_revision === input.expected_revision && v.base_digest === input.base_digest && p.reason === input.reason && fields.every(key => JSON.stringify(p.brief[key]) === JSON.stringify(input.brief[key])));
  return v;
}
export function validateProjectResponse(v) {
  bounded(v);
  if (closed(v, ["state"]) && v.state === "not_connected") return v;
  check(closed(v, ["state", "binding_sha256", "can_inspect", "view"]) && v.state === "connected" && hex(v.binding_sha256) && typeof v.can_inspect === "boolean");
  validateProjectView(v.view); return v;
}
export function validateProjectInspectionResponse(v, input, project) {
  bounded(v); check(closed(v, ["binding_sha256", "inspection"]) && hex(v.binding_sha256) && v.binding_sha256 === input.binding_sha256);
  validateProjectInspection(v.inspection, project?.project_id, input);
  if (project) {
    validateProjectTaskRefs(v.inspection.impact_task_refs, project.version);
    const canonical = values => JSON.stringify(values.map(value => Object.keys(value).sort().map(key => [key, value[key]])));
    check(canonical(v.inspection.impact_task_refs) === canonical(project.task_refs));
  }
  return v;
}
