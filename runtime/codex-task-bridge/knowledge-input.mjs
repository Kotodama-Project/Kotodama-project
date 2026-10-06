/** Compose an operator-validated public knowledge projection as data, not Voice.
 * Expected digests must come from the current trusted KB/Work owner. Matching
 * caller-supplied strings alone never authenticates sources, ACL or Task state.
 */
import { createHash } from 'node:crypto';
import { strictJson } from '../local-review-gateway/server.mjs';

const hex = /^[0-9a-f]{64}$/;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const keys = ['kind', 'schema_revision', 'bundle_id', 'source_digest', 'as_of', 'authority', 'state',
  'filters', 'concepts', 'omitted_ids', 'unresolved_ids', 'consumer_rule'];
const conceptKeys = ['id', 'path', 'title', 'description', 'status', 'knowledge_state', 'trust_tier',
  'stale_after', 'is_stale', 'owner_role', 'reviewer_role', 'goal_refs', 'kgi_refs', 'initiative_refs',
  'answer_mode', 'source_resources'];
const closed = (value, fields) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key));
const text = value => typeof value === 'string' && value.isWellFormed() && Boolean(value.trim());
const strings = value => Array.isArray(value) && value.length <= 256 && value.every(text);
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

export function prepareKnowledgeBriefInput({ request, contextJson, expectedContextSha256, expectedSourceDigest, now = Date.now() }) {
  if (typeof request !== 'string' || !request.trim() || !request.isWellFormed() || Buffer.byteLength(request) > 4096
    || typeof contextJson !== 'string' || !contextJson.isWellFormed() || Buffer.byteLength(contextJson) > 16384
    || typeof expectedContextSha256 !== 'string' || !hex.test(expectedContextSha256)
    || typeof expectedSourceDigest !== 'string' || !hex.test(expectedSourceDigest)
    || !Number.isSafeInteger(now) || now < 0) throw new Error('knowledge_input_denied');
  if (digest(Buffer.from(contextJson, 'utf8')) !== expectedContextSha256) throw new Error('knowledge_context_drift');
  let context;
  try { context = strictJson(Buffer.from(contextJson, 'utf8')); }
  catch { throw new Error('knowledge_context_invalid'); }
  if (!closed(context, keys)
    || context.kind !== 'kotodama.generated-knowledge-context' || context.schema_revision !== 'v1'
    || context.authority !== 'projection_only' || context.state !== 'ready_candidate'
    || !text(context.bundle_id) || !text(context.consumer_rule)
    || typeof context.source_digest !== 'string' || !hex.test(context.source_digest)
    || !Number.isFinite(instant(context.as_of)) || instant(context.as_of) > now
    || !Array.isArray(context.unresolved_ids) || context.unresolved_ids.length
    || !Array.isArray(context.concepts) || !context.concepts.length || context.concepts.length > 32
    || !strings(context.omitted_ids)
    || !closed(context.filters, ['goals', 'kgis', 'initiatives', 'tags'])
    || !Object.values(context.filters).every(strings)
    || !Object.values(context.filters).some(values => values.length)) throw new Error('knowledge_context_not_ready');
  if (context.source_digest !== expectedSourceDigest) throw new Error('knowledge_source_drift');
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
  const input = JSON.stringify({ request, knowledge_context: context });
  if (Buffer.byteLength(input, 'utf8') > 16384) throw new Error('knowledge_input_budget');
  return Object.freeze({ input, knowledge_context_sha256: expectedContextSha256,
    knowledge_source_digest: expectedSourceDigest, input_sha256: digest(Buffer.from(input, 'utf8')),
    authority: 'projection_only', task_binding: 'not_connected' });
}
