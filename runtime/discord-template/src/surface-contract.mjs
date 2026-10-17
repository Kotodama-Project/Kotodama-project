// Account-free contract checks. This module does not register a connector or Task.
import { createHash, createHmac, createPublicKey, timingSafeEqual, verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

const ajv = new Ajv2020({ strict: true });
addFormats(ajv);
const envelopeShape = ajv.compile(JSON.parse(readFileSync(new URL('../schemas/surface-event-envelope.schema.json', import.meta.url), 'utf8')));

function requireValue(condition, code) {
  if (!condition) throw new Error(code);
}

function text(value, maximum = 512) {
  requireValue(typeof value === 'string' && value.length > 0 && value.length <= maximum && !/[\u0000-\u001f]/u.test(value), 'INVALID_REFERENCE');
  return value;
}

function seconds(value) {
  requireValue(Number.isSafeInteger(value) && value >= 0, 'INVALID_TIME');
  return value;
}

export function verifySlackSignature({ rawBody, timestamp, signature, signingSecret, now }) {
  requireValue(Buffer.isBuffer(rawBody) && rawBody.length <= 65536, 'BODY_LIMIT');
  requireValue(typeof timestamp === 'string' && /^\d{10}$/u.test(timestamp), 'INVALID_TIME');
  requireValue(Math.abs(seconds(now) - Number(timestamp)) <= 300, 'STALE_REQUEST');
  requireValue(typeof signature === 'string' && /^v0=[a-f0-9]{64}$/u.test(signature), 'INVALID_SIGNATURE');
  requireValue(typeof signingSecret === 'string' && signingSecret.length >= 16 && signingSecret.length <= 512, 'KEY_REQUIRED');
  const expected = createHmac('sha256', signingSecret).update(`v0:${timestamp}:`).update(rawBody).digest();
  requireValue(timingSafeEqual(expected, Buffer.from(signature.slice(3), 'hex')), 'INVALID_SIGNATURE');
  return { algorithmVerified: true, rawBodySha256: createHash('sha256').update(rawBody).digest('hex'), providerVerified: false };
}

function jwtPart(value) {
  requireValue(typeof value === 'string' && /^[A-Za-z0-9_-]+$/u.test(value), 'INVALID_JWT');
  const bytes = Buffer.from(value, 'base64url');
  requireValue(bytes.toString('base64url') === value && bytes.length <= 8192, 'INVALID_JWT');
  try {
    const result = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    requireValue(result && typeof result === 'object' && !Array.isArray(result), 'INVALID_JWT');
    return result;
  } catch { throw new Error('INVALID_JWT'); }
}

export function verifyTeamsTokenFixture({ authorization, appId, serviceUrl, keys, now }) {
  // The calling production adapter must obtain/refresh trusted OpenID keys and
  // authenticate the TLS request. These offline checks never establish that trust.
  requireValue(typeof authorization === 'string' && authorization.length <= 24000 && authorization.startsWith('Bearer '), 'BEARER_REQUIRED');
  const parts = authorization.slice(7).split('.');
  requireValue(parts.length === 3, 'INVALID_JWT');
  const header = jwtPart(parts[0]);
  const claims = jwtPart(parts[1]);
  requireValue(header.alg === 'RS256' && typeof header.kid === 'string' && header.crit === undefined, 'JWT_ALGORITHM_REFUSED');
  requireValue(Array.isArray(keys) && keys.length <= 32, 'KEY_SET_REQUIRED');
  const matches = keys.filter(key => key.kid === header.kid);
  requireValue(matches.length === 1 && matches[0].kty === 'RSA' && matches[0].endorsements?.includes('msteams'), 'CHANNEL_KEY_REQUIRED');
  const key = createPublicKey({ key: matches[0], format: 'jwk' });
  requireValue(key.asymmetricKeyDetails.modulusLength >= 2048, 'KEY_SIZE_REFUSED');
  requireValue(/^[A-Za-z0-9_-]+$/u.test(parts[2]) && verify('RSA-SHA256', Buffer.from(`${parts[0]}.${parts[1]}`), key, Buffer.from(parts[2], 'base64url')), 'INVALID_SIGNATURE');
  requireValue(claims.iss === 'https://api.botframework.com' && claims.aud === text(appId), 'JWT_IDENTITY_REFUSED');
  const current = seconds(now);
  requireValue(seconds(claims.nbf) <= current + 300 && seconds(claims.exp) > current - 300 && claims.exp > claims.nbf, 'STALE_REQUEST');
  requireValue(new URL(serviceUrl).protocol === 'https:' && claims.serviceUrl === serviceUrl, 'SERVICE_URL_REFUSED');
  return { algorithmVerified: true, providerVerified: false, keyTrustVerified: false };
}

export function validateSurfaceEnvelope(event, installation, prior = [], now = Math.floor(Date.now() / 1000)) {
  requireValue(envelopeShape(event), 'ENVELOPE_SCHEMA_REFUSED');
  requireValue(event?.kind === 'kotodama/surface-envelope/v1' && event.synthetic === true, 'SYNTHETIC_CONTRACT_REQUIRED');
  requireValue(['slack', 'teams'].includes(event.surface) && installation.surface === event.surface, 'SURFACE_MISMATCH');
  for (const name of ['tenant', 'installation', 'channel', 'thread', 'actor', 'eventId', 'sourceId']) text(event[name]);
  requireValue(event.tenant === installation.tenant && event.installation === installation.id && installation.active === true, 'INSTALLATION_REFUSED');
  requireValue(seconds(installation.expiresAt) > seconds(now) && seconds(event.expiresAt) > now && event.expiresAt <= installation.expiresAt, 'SCOPE_EXPIRED');
  text(event.consentRef);
  requireValue(event.permissionRevision === installation.permissionRevision && Number.isSafeInteger(event.permissionRevision), 'PERMISSION_REVISION_REFUSED');
  requireValue(installation.channels.includes(event.channel) && installation.actors.includes(event.actor), 'MEMBERSHIP_REFUSED');
  requireValue(Number.isSafeInteger(event.revision) && event.revision > 0 && ['message', 'edit', 'delete', 'revoke'].includes(event.operation), 'REVISION_REFUSED');
  requireValue(typeof event.text === 'string' && event.text.length <= 12000, 'TEXT_LIMIT');
  requireValue(['delete', 'revoke'].includes(event.operation) ? event.text === '' : true, 'TOMBSTONE_CONTENT_REFUSED');
  requireValue(event.acl?.tenant === event.tenant && Array.isArray(event.acl.readers) && event.acl.readers.length <= 64 && event.acl.readers.every(reader => typeof reader === 'string') && event.acl.readers.includes(event.actor), 'ACL_REFUSED');
  requireValue(event.capabilities?.textIngress === true && event.capabilities?.textProjection === true, 'TEXT_CAPABILITY_REQUIRED');
  for (const name of ['receiveAudio', 'sendAudio', 'verifiedSpeaker']) requireValue(['unknown', 'unsupported'].includes(event.capabilities[name]), 'MEDIA_NOT_ACCEPTED');
  requireValue(Number.isFinite(Date.parse(event.occurredAt)), 'INVALID_TIME');
  const eventKey = JSON.stringify([event.surface, event.tenant, event.installation, event.eventId]);
  const sourceKey = JSON.stringify([event.surface, event.tenant, event.installation, event.channel, event.sourceId]);
  requireValue(Array.isArray(prior) && prior.length <= 4096, 'HISTORY_LIMIT');
  requireValue(!prior.some(receipt => receipt.eventKey === eventKey), 'REPLAY_REFUSED');
  const previous = prior.filter(receipt => receipt.sourceKey === sourceKey);
  requireValue(previous.every(receipt => Number.isSafeInteger(receipt.revision) && receipt.revision < event.revision), 'STALE_OR_CONFLICTING_REVISION');
  const route = { surface: event.surface, tenant: event.tenant, installation: event.installation, channel: event.channel, thread: event.thread };
  return { eventKey, sourceKey, revision: event.revision, operation: event.operation, route,
    permissionRevision: event.permissionRevision, sourceUsable: !['delete', 'revoke'].includes(event.operation),
    actor: event.actor, acl: structuredClone(event.acl),
    expiresAt: event.expiresAt,
    state: 'SYNTHETIC_CANDIDATE_ONLY', signatureVerified: false, providerVerified: false,
    taskCreated: false, publicationAuthorized: false };
}

export function validateResultRoute(receipt, installation, route, currentSource, now = Math.floor(Date.now() / 1000)) {
  requireValue(receipt?.state === 'SYNTHETIC_CANDIDATE_ONLY' && installation.active === true && receipt.sourceUsable === true, 'RESULT_SCOPE_REVOKED');
  requireValue(seconds(installation.expiresAt) > seconds(now) && seconds(receipt.expiresAt) > now, 'SCOPE_EXPIRED');
  requireValue(receipt.permissionRevision === installation.permissionRevision && receipt.route.tenant === installation.tenant && receipt.route.installation === installation.id && receipt.route.surface === installation.surface, 'RESULT_SCOPE_REVOKED');
  requireValue(currentSource?.sourceKey === receipt.sourceKey && currentSource.revision === receipt.revision && currentSource.sourceUsable === true, 'RESULT_SOURCE_CHANGED');
  requireValue(installation.channels.includes(receipt.route.channel) && installation.actors.includes(receipt.actor) && receipt.acl.readers.includes(receipt.actor), 'RESULT_MEMBERSHIP_REVOKED');
  requireValue(['surface', 'tenant', 'installation', 'channel', 'thread'].every(key => route[key] === receipt.route[key]), 'RESULT_ROUTE_MISMATCH');
  return { routeVerified: true, publicationAuthorized: false };
}
