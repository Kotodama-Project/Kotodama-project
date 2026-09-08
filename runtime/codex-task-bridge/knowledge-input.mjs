/** Compose an operator-validated public knowledge projection as data, not Voice.
 * Expected digests must come from the current trusted KB/Work owner. Matching
 * caller-supplied strings alone never authenticates sources, ACL or Task state.
 */
import { createHash } from 'node:crypto';
import { strictJson } from '../local-review-gateway/server.mjs';

const hex = /^[0-9a-f]{64}$/;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const keys = ['kind', 'schema_revision', 'bundle_id', 'source_digest', 'authority', 'state',
  'filters', 'concepts', 'omitted_ids', 'unresolved_ids', 'consumer_rule'];

export function prepareKnowledgeBriefInput({ request, contextJson, expectedContextSha256, expectedSourceDigest, now = Date.now() }) {
  if (typeof request !== 'string' || !request.trim() || !request.isWellFormed() || Buffer.byteLength(request) > 4096
    || typeof contextJson !== 'string' || !contextJson.isWellFormed() || Buffer.byteLength(contextJson) > 16384
    || !hex.test(expectedContextSha256 ?? '') || !hex.test(expectedSourceDigest ?? '')
    || !Number.isSafeInteger(now) || now < 0) throw new Error('knowledge_input_denied');
  if (digest(Buffer.from(contextJson, 'utf8')) !== expectedContextSha256) throw new Error('knowledge_context_drift');
  let context;
  try { context = strictJson(Buffer.from(contextJson, 'utf8')); }
  catch { throw new Error('knowledge_context_invalid'); }
  if (!context || typeof context !== 'object' || Array.isArray(context)
    || Object.keys(context).length !== keys.length || keys.some(key => !Object.hasOwn(context, key))
    || context.kind !== 'kotodama.generated-knowledge-context' || context.schema_revision !== 'v1'
    || context.authority !== 'projection_only' || context.state !== 'ready_candidate'
    || !hex.test(context.source_digest ?? '') || !Array.isArray(context.unresolved_ids) || context.unresolved_ids.length
    || !Array.isArray(context.concepts) || !context.concepts.length || context.concepts.length > 32
    || !Array.isArray(context.omitted_ids)) throw new Error('knowledge_context_not_ready');
  if (context.source_digest !== expectedSourceDigest) throw new Error('knowledge_source_drift');
  const ids = new Set();
  for (const concept of context.concepts) {
    if (!concept || typeof concept !== 'object' || Array.isArray(concept) || typeof concept.id !== 'string'
      || !concept.id || concept.id.length > 128 || ids.has(concept.id)
      || concept.is_stale !== false || typeof concept.stale_after !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(concept.stale_after)
      || !Number.isFinite(Date.parse(concept.stale_after)) || now >= Date.parse(concept.stale_after)) {
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
