import { createHash } from "node:crypto";

const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");

// The caller has already admitted the catalog record; this contains no identity or source body.
export function contextReceipt(record, status, elapsedMs) {
  const success = status === 200 && record;
  return {
    kind: "kotodama/context-gateway-receipt/v1",
    policy_sha256: success ? digest(record.access_policy) : null,
    provenance_sha256: success ? digest([...new Set(record.projection.evidence_pointers)].sort()) : null,
    backend_version: "local-review-gateway/v3",
    latency_bucket: elapsedMs < 100 ? "under_100ms" : elapsedMs < 1000 ? "under_1s" : "at_least_1s",
    outcome: success ? "ok" : status >= 500 ? "unavailable" : "refused",
    provider_verified: false,
    publication_authorized: false,
  };
}

export function receiptHeaders(receipt) {
  const headers = {};
  for (const [field, suffix] of [["policy_sha256", "policy"], ["provenance_sha256", "provenance"],
    ["backend_version", "backend"], ["latency_bucket", "latency"], ["outcome", "outcome"]]) {
    if (receipt[field] !== null) headers[`x-kotodama-context-${suffix}`] = receipt[field];
  }
  return headers;
}
