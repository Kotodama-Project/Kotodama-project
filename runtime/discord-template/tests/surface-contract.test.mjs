import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, generateKeyPairSync, sign } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { verifySlackSignature, verifyTeamsTokenFixture, validateSurfaceEnvelope, validateResultRoute } from '../src/surface-contract.mjs';

const now = 1700000000;
const installation = { surface: 'slack', tenant: 'tenant-a', id: 'install-a', active: true, permissionRevision: 3, channels: ['room-a'], actors: ['actor-a'], expiresAt: 2000000000 };
const envelope = JSON.parse(readFileSync(new URL('../../../examples/surface-envelope/slack.json', import.meta.url), 'utf8'));

test('Slack signatures bind exact raw bytes and reject invalid or stale requests', () => {
  const rawBody = Buffer.from(JSON.stringify(envelope));
  const signingSecret = 'synthetic-signing-material-for-contract-tests';
  const signature = 'v0=' + createHmac('sha256', signingSecret).update(`v0:${now}:`).update(rawBody).digest('hex');
  const input = { rawBody, timestamp: String(now), signature, signingSecret, now };
  assert.equal(verifySlackSignature(input).algorithmVerified, true);
  assert.equal(verifySlackSignature(input).providerVerified, false);
  for (const patch of [{ rawBody: Buffer.concat([rawBody, Buffer.from(' ')]) }, { now: now + 301 }, { now: now - 301 }, { signature: 'v0=' + '0'.repeat(64) }]) {
    assert.throws(() => verifySlackSignature({ ...input, ...patch }));
  }
});

test('Teams fixture requires RSA signature, issuer, audience, time, service URL and endorsement', () => {
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const key = { ...publicKey.export({ format: 'jwk' }), kid: 'fixture-key', endorsements: ['msteams'] };
  const claims = { iss: 'https://api.botframework.com', aud: 'fixture-app', nbf: now - 10, exp: now + 60, serviceUrl: 'https://service.invalid/fixture' };
  const jwt = values => {
    const header = Buffer.from(JSON.stringify({ alg: 'RS256', kid: key.kid })).toString('base64url');
    const payload = Buffer.from(JSON.stringify(values)).toString('base64url');
    return 'Bearer ' + header + '.' + payload + '.' + sign('RSA-SHA256', Buffer.from(header + '.' + payload), privateKey).toString('base64url');
  };
  const input = { authorization: jwt(claims), appId: 'fixture-app', serviceUrl: claims.serviceUrl, keys: [key], now };
  assert.deepEqual(verifyTeamsTokenFixture(input), { algorithmVerified: true, providerVerified: false, keyTrustVerified: false });
  for (const patch of [{ aud: 'different-app' }, { iss: 'https://issuer.invalid' }, { serviceUrl: 'https://different.invalid' }, { exp: now - 301 }]) {
    assert.throws(() => verifyTeamsTokenFixture({ ...input, authorization: jwt({ ...claims, ...patch }) }));
  }
  assert.throws(() => verifyTeamsTokenFixture({ ...input, keys: [{ ...key, endorsements: [] }] }));
  assert.throws(() => verifyTeamsTokenFixture({ ...input, authorization: input.authorization.slice(0, -8) + 'AAAAAAAA' }));
});

for (const surface of ['slack', 'teams']) {
  test(`${surface} replay, tenant isolation, edit/delete and result scope`, () => {
    const profile = { ...installation, surface };
    const event = { ...structuredClone(envelope), surface };
    const first = validateSurfaceEnvelope(event, profile);
    assert.equal(first.taskCreated, false);
    assert.equal(first.signatureVerified, false);
    assert.throws(() => validateSurfaceEnvelope(event, profile, [first]), /REPLAY_REFUSED/);
    assert.throws(() => validateSurfaceEnvelope({ ...event, tenant: 'tenant-b' }, profile), /INSTALLATION_REFUSED/);
    assert.throws(() => validateSurfaceEnvelope(event, { ...profile, active: false }), /INSTALLATION_REFUSED/);
    assert.throws(() => validateSurfaceEnvelope(event, { ...profile, permissionRevision: 4 }), /PERMISSION_REVISION_REFUSED/);
    assert.throws(() => validateSurfaceEnvelope(event, { ...profile, actors: [] }), /MEMBERSHIP_REFUSED/);
    assert.throws(() => validateSurfaceEnvelope(event, { ...profile, expiresAt: 1 }), /SCOPE_EXPIRED/);
    const edited = validateSurfaceEnvelope({ ...event, revision: 2, operation: 'edit', eventId: 'event-b' }, profile, [first]);
    const deleted = validateSurfaceEnvelope({ ...event, revision: 3, operation: 'delete', eventId: 'event-c', text: '' }, profile, [first, edited]);
    assert.equal(deleted.sourceUsable, false);
    assert.throws(() => validateSurfaceEnvelope({ ...event, eventId: 'event-stale' }, profile, [deleted]), /STALE_OR_CONFLICTING/);
    assert.equal(validateResultRoute(first, profile, first.route, first).publicationAuthorized, false);
    assert.throws(() => validateResultRoute(first, profile, first.route, edited), /RESULT_SOURCE_CHANGED/);
    assert.throws(() => validateResultRoute(first, profile, first.route, deleted), /RESULT_SOURCE_CHANGED/);
    assert.throws(() => validateResultRoute(first, profile, first.route, first, 2000000000), /SCOPE_EXPIRED/);
    assert.throws(() => validateResultRoute(first, { ...profile, actors: [] }, first.route, first), /RESULT_MEMBERSHIP_REVOKED/);
    assert.throws(() => validateResultRoute(first, profile, { ...first.route, thread: 'different' }, first), /RESULT_ROUTE_MISMATCH/);
    const otherTenant = { ...event, tenant: 'tenant-b', installation: 'install-b', acl: { tenant: 'tenant-b', readers: ['actor-a'] } };
    const other = validateSurfaceEnvelope(otherTenant, { ...profile, tenant: 'tenant-b', id: 'install-b' }, [first]);
    assert.notEqual(first.sourceKey, other.sourceKey);
  });
}

test('unknown media remains unavailable and passive source cannot authorize work', () => {
  assert.throws(() => validateSurfaceEnvelope({ ...envelope, capabilities: { ...envelope.capabilities, receiveAudio: true } }, installation), /ENVELOPE_SCHEMA_REFUSED/);
  assert.throws(() => validateSurfaceEnvelope({ ...envelope, operation: 'delete' }, installation), /ENVELOPE_SCHEMA_REFUSED/);
  const receipt = validateSurfaceEnvelope(envelope, installation);
  assert.equal(receipt.publicationAuthorized, false);
  assert.equal(receipt.providerVerified, false);
});

test('Node admission follows the same closed schema as the read-only validator', () => {
  for (const patch of [
    { permissionRevision: 0 },
    { acl: { ...envelope.acl, unreviewed: 'must not enter the receipt' } },
    { acl: { ...envelope.acl, readers: ['actor-a', 'actor-a'] } },
    { acl: { ...envelope.acl, readers: ['actor-a', 'bad\nreference'] } },
    { unknown: true },
  ]) assert.throws(() => validateSurfaceEnvelope({ ...envelope, ...patch }, installation), /ENVELOPE_SCHEMA_REFUSED/);
});
