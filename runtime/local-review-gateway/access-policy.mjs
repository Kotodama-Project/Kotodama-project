// Local projection access policy. IDs name subjects; they are not credentials.
export const CLASSIFICATIONS = Object.freeze(["unclassified", "public_candidate", "internal", "restricted", "secret"]);
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const PRINCIPAL = new RegExp(`^urn:kotodama:principal:${UUID}$`);
const POLICY = new RegExp(`^urn:kotodama:access-policy:${UUID}$`);
const DIGEST = /^[0-9a-f]{64}$/;
const KEYS = ["policy_id", "revision", "classification", "owner_ref", "readers", "reviewers", "expires_at", "state"];
const closed = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
export function validatePrincipals(principals) {
  if (!Array.isArray(principals) || !principals.length || principals.length > 128) throw new Error("principals_denied");
  const ids = new Set();
  const bindings = new Set();
  for (const principal of principals) {
    if (!closed(principal, ["principal_ref", "kind", "actor_sha256"])
      || typeof principal.principal_ref !== "string" || !PRINCIPAL.test(principal.principal_ref)
      || !["human", "agent", "service"].includes(principal.kind)
      || typeof principal.actor_sha256 !== "string" || !DIGEST.test(principal.actor_sha256)
      || ids.has(principal.principal_ref) || bindings.has(principal.actor_sha256)) throw new Error("principals_denied");
    ids.add(principal.principal_ref); bindings.add(principal.actor_sha256);
  }
  return ids;
}

export function validateAccessPolicy(policy, principalRefs) {
  if (!closed(policy, KEYS) || typeof policy.policy_id !== "string" || !POLICY.test(policy.policy_id)
    || !Number.isSafeInteger(policy.revision) || policy.revision < 1 || policy.revision > 33
    || !CLASSIFICATIONS.includes(policy.classification) || !principalRefs.has(policy.owner_ref)
    || !["active", "revoked"].includes(policy.state)) throw new Error("policy_denied");
  for (const field of ["readers", "reviewers"]) {
    const refs = policy[field];
    if (!Array.isArray(refs) || refs.length > 128 || new Set(refs).size !== refs.length
      || refs.some((ref) => typeof ref !== "string" || !principalRefs.has(ref))) throw new Error("policy_denied");
  }
  if (policy.reviewers.some((ref) => !policy.readers.includes(ref))
    || typeof policy.expires_at !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(policy.expires_at)
    || !Number.isFinite(Date.parse(policy.expires_at)) || new Date(policy.expires_at).toISOString() !== policy.expires_at) throw new Error("policy_denied");
  return policy;
}

export function canAccess(policy, principalRef, action, now = Date.now()) {
  // No public/publish/execute action exists. Unclassified and secrets never reach this review UI.
  if (!principalRef || !Number.isFinite(now) || !["read", "review"].includes(action)
    || !["public_candidate", "internal", "restricted"].includes(policy.classification)
    || policy.state !== "active" || Date.parse(policy.expires_at) <= now) return false;
  return policy.readers.includes(principalRef) && (action === "read" || policy.reviewers.includes(principalRef));
}
