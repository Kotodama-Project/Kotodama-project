/** Compose an operator-validated public knowledge projection as data, not Voice.
 * Expected digests must come from the current trusted KB/Work owner. Matching
 * caller-supplied strings alone never authenticates sources, ACL or Task state.
 */
import { createHash } from 'node:crypto';
import { strictJson } from '../local-review-gateway/server.mjs';

const hex = /^[0-9a-f]{64}$/;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const keys = ['kind', 'schema_revision', 'bundle_id', 'source_digest', 'as_of', 'authority', 'state',
  'filters', 'concepts', 'omitted_ids', 'unresolved_ids', 'consumer_rule', 'errors', 'work', 'claims', 'context_sha256'];
const claimKeys = ['human_approval_verified', 'reviewer_identity_verified', 'semantic_entailment_verified',
  'execution_authorized', 'promotion_created', 'current_truth_changed'];
const sensitivity = Object.freeze({ public: 0, internal: 1, restricted: 2 });
const conceptKeys = ['id', 'path', 'title', 'description', 'status', 'knowledge_state', 'trust_tier',
  'stale_after', 'is_stale', 'owner_role', 'reviewer_role', 'goal_refs', 'kgi_refs', 'initiative_refs',
  'answer_mode', 'source_resources'];
const closed = (value, fields) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
const text = value => typeof value === 'string' && value.isWellFormed() && Boolean(value.trim());
const strings = value => Array.isArray(value) && value.length <= 256 && value.every(text) && new Set(value).size === value.length;
const hexValue = value => typeof value === 'string' && hex.test(value);
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const instant = value => {
  if (typeof value !== 'string' || value.length > 64) return NaN;
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/i.exec(value);
  const time = Date.parse(value);
  if (!match || !Number.isFinite(time)) return NaN;
  const zone = match[2];
  const offset = /^z$/i.test(zone) ? 0 : (zone[0] === '-' ? -1 : 1) *
    (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4))) * 60000;
  return new Date(time + offset).toISOString().slice(0, 19) === match[1].toUpperCase() ? time : NaN;
};

function validateWork(work, omitted, now, ceiling) {
  const fail = () => { throw new Error('knowledge_work_not_ready'); };
  const id = value => typeof value === 'string' && /^[a-z][a-z0-9-]{0,63}$/.test(value);
  const refs = value => strings(value) && value.length <= 64 && value.every(id);
  const prose = value => text(value) && [...value].length <= 4096;
  const classified = value => typeof value === 'string' && Object.hasOwn(sensitivity, value)
    && sensitivity[value] <= sensitivity[work.sensitivity_ceiling];
  const fields = ['package_sha256','subject_sha256','sensitivity_ceiling','work_ref','objective','selected_claims',
    'sources','assumptions','questions','contradictions','acceptance_criteria','deliverable_bindings'];
  if (!closed(work, fields) || !hexValue(work.package_sha256) || !hexValue(work.subject_sha256)
    || typeof work.work_ref !== 'string' || !/^ref\/[A-Za-z0-9][A-Za-z0-9_./-]{0,190}$/.test(work.work_ref)
    || !prose(work.objective) || typeof work.sensitivity_ceiling !== 'string'
    || !Object.hasOwn(sensitivity, work.sensitivity_ceiling)
    || sensitivity[work.sensitivity_ceiling] > sensitivity[ceiling] || !refs(omitted)) fail();
  const collections = [
    ['selected_claims', 64, ['id','kind','statement','source_refs','material','sensitivity']],
    ['sources', 32, ['id','sha256','kind','sensitivity','expires_at']],
    ['assumptions', 64, ['id','statement','claim_refs']],
    ['questions', 64, ['id','statement','blocking','state']],
    ['contradictions', 64, ['id','claim_refs','severity','state']],
    ['acceptance_criteria', 64, ['id','description','reported_state','deliverable_refs']],
    ['deliverable_bindings', 32, ['id','sha256','criterion_refs']]];
  const ids = new Set();
  for (const [key, limit, names] of collections) {
    if (!Array.isArray(work[key]) || work[key].length > limit) fail();
    for (const item of work[key]) {
      if (!closed(item,names) || !id(item.id) || ids.has(item.id)) fail();
      ids.add(item.id);
    }
  }
  if (['selected_claims','sources','acceptance_criteria','deliverable_bindings'].some(key => !work[key].length)) fail();
  const sources = new Map(work.sources.map(item => [item.id,item]));
  const claims = new Map(work.selected_claims.map(item => [item.id,item]));
  const criteria = new Map(work.acceptance_criteria.map(item => [item.id,item]));
  const deliveries = new Map(work.deliverable_bindings.map(item => [item.id,item]));
  const knownClaims = values => refs(values) && values.every(value => claims.has(value));
  if (omitted.some(value => claims.has(value))) fail();
  for (const source of sources.values()) {
    if (!hexValue(source.sha256) || !['synthetic_fixture','local_snapshot'].includes(source.kind) || !classified(source.sensitivity)
      || (source.expires_at === null ? source.kind !== 'synthetic_fixture' : !Number.isFinite(instant(source.expires_at)) || now >= instant(source.expires_at))) fail();
  }
  for (const item of claims.values()) {
    if (!['observation','inference','assumption'].includes(item.kind) || !prose(item.statement) || typeof item.material !== 'boolean'
      || !classified(item.sensitivity) || !refs(item.source_refs) || !item.source_refs.every(ref => sources.has(ref))
      || item.source_refs.some(ref => sensitivity[sources.get(ref).sensitivity] > sensitivity[item.sensitivity])
      || (item.material && item.kind !== 'assumption' && !item.source_refs.length)) fail();
  }
  if (!work.selected_claims.some(item => item.material && item.kind !== 'assumption' && item.source_refs.length)) fail();
  for (const item of work.assumptions) if (!prose(item.statement) || !knownClaims(item.claim_refs)) fail();
  const assumptionClaims = new Set(work.assumptions.flatMap(item => item.claim_refs));
  if (work.selected_claims.some(item => item.kind === 'assumption' && !assumptionClaims.has(item.id))) fail();
  for (const item of work.questions) if (!prose(item.statement) || typeof item.blocking !== 'boolean'
    || !['open','resolved'].includes(item.state) || item.blocking && item.state === 'open') fail();
  for (const item of work.contradictions) if (!knownClaims(item.claim_refs) || !Number.isInteger(item.severity)
    || item.severity < 1 || item.severity > 3 || !['open','resolved'].includes(item.state)
    || item.severity === 1 && item.state === 'open') fail();
  for (const item of criteria.values()) if (!prose(item.description) || item.reported_state !== 'met'
    || !refs(item.deliverable_refs) || !item.deliverable_refs.length
    || !item.deliverable_refs.every(ref => deliveries.has(ref) && refs(deliveries.get(ref).criterion_refs) && deliveries.get(ref).criterion_refs.includes(item.id))) fail();
  for (const item of deliveries.values()) if (!hexValue(item.sha256) || !refs(item.criterion_refs) || !item.criterion_refs.length
    || !item.criterion_refs.every(ref => criteria.has(ref) && criteria.get(ref).deliverable_refs.includes(item.id))) fail();
}

export function prepareKnowledgeBriefInput({ request, contextJson, expectedContextSha256, expectedSourceDigest, sensitivityCeiling = 'public', now = Date.now() }) {
  if (typeof request !== 'string' || !request.trim() || !request.isWellFormed() || Buffer.byteLength(request) > 4096
    || typeof contextJson !== 'string' || !contextJson.isWellFormed() || Buffer.byteLength(contextJson) > 16384
    || typeof expectedContextSha256 !== 'string' || !hex.test(expectedContextSha256)
    || typeof expectedSourceDigest !== 'string' || !hex.test(expectedSourceDigest)
    || !Number.isSafeInteger(now) || now < 0 || typeof sensitivityCeiling !== 'string'
    || !Object.hasOwn(sensitivity, sensitivityCeiling)) throw new Error('knowledge_input_denied');
  if (digest(Buffer.from(contextJson, 'utf8')) !== expectedContextSha256) throw new Error('knowledge_context_drift');
  let context;
  try { context = strictJson(Buffer.from(contextJson, 'utf8')); }
  catch { throw new Error('knowledge_context_invalid'); }
  if (!closed(context, keys)
    || context.kind !== 'kotodama.generated-knowledge-context' || context.schema_revision !== 'v2'
    || context.authority !== 'projection_only' || context.state !== 'ready_candidate'
    || !text(context.bundle_id) || context.bundle_id.length > 256 || !text(context.consumer_rule)
    || !hexValue(context.context_sha256) || !Array.isArray(context.errors) || context.errors.length
    || !closed(context.claims, claimKeys) || !Object.values(context.claims).every(value => value === false)
    || typeof context.source_digest !== 'string' || !hex.test(context.source_digest)
    || !Number.isFinite(instant(context.as_of)) || instant(context.as_of) > now
    || !Array.isArray(context.unresolved_ids) || context.unresolved_ids.length
    || !Array.isArray(context.concepts) || context.concepts.length > 32
    || !strings(context.omitted_ids)
    || !closed(context.filters, ['goals', 'kgis', 'initiatives', 'tags'])
    || !Object.values(context.filters).every(strings)) throw new Error('knowledge_context_not_ready');
  if (context.source_digest !== expectedSourceDigest) throw new Error('knowledge_source_drift');
  if (context.work === null) {
    if (!context.concepts.length || !Object.values(context.filters).some(values => values.length)) throw new Error('knowledge_context_not_ready');
  } else {
    if (context.concepts.length || Object.values(context.filters).some(values => values.length)) throw new Error('knowledge_context_not_ready');
    validateWork(context.work, context.omitted_ids, now, sensitivityCeiling);
  }
  const ids = new Set();
  for (const concept of context.concepts) {
    if (!closed(concept, conceptKeys) || !text(concept.id) || concept.id.length > 128 || ids.has(concept.id)
      || !['path', 'title', 'description', 'owner_role', 'reviewer_role'].every(key => text(concept[key]))
      || !['draft', 'stable'].includes(concept.status) || !['candidate', 'confirmed'].includes(concept.knowledge_state)
      || !['unverified', 'machine-confirmed', 'human-reviewed'].includes(concept.trust_tier)
      || concept.answer_mode !== 'source_required'
      || !['goal_refs', 'kgi_refs', 'initiative_refs', 'source_resources'].every(key => strings(concept[key]))
      || !concept.source_resources.length || context.omitted_ids.includes(concept.id)
      || concept.is_stale !== false || !Number.isFinite(instant(concept.stale_after))
      || now >= instant(concept.stale_after)) {
      throw new Error('knowledge_context_stale');
    }
    ids.add(concept.id);
  }
  const computed = digest(Buffer.from(JSON.stringify(canonical({ ...context, context_sha256: null })), 'utf8'));
  if (computed !== context.context_sha256) throw new Error('knowledge_context_digest_mismatch');
  const input = JSON.stringify({ request, knowledge_context: context });
  if (Buffer.byteLength(input, 'utf8') > 16384) throw new Error('knowledge_input_budget');
  return Object.freeze({ input, knowledge_context_sha256: expectedContextSha256,
    knowledge_source_digest: expectedSourceDigest, input_sha256: digest(Buffer.from(input, 'utf8')),
    authority: 'projection_only', task_binding: 'not_connected' });
}
