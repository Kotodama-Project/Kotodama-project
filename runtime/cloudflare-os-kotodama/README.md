# Kotodama's official Cloudflare OS extension

This directory is a source addon for official Cloudflare OS core
`c0b6f3e52ff0ab8d44d290647e256936e88e6b57`. It provides a native Gatekeeper and
bundled requirements Gadget. It is not a replacement OS or a new identity SSOT.

Copy `gatekeeper-kotodama-brief` into an isolated core checkout's `packages/`, and
the `blueprints/kotodama-requirements` directory into
`packages/workshop-backend/format-blueprints/`. Preserve the original checkout and
state. The core dev runner discovers the Gatekeeper package; the original bundled
blueprints builder reconstructs the normal Gadget archive from these files.
This is an additive evaluation deployment, not production self-host certification.

Use the existing pinned dependency graph. The new package's dependency declarations
match the existing Home Assistant Gatekeeper importer; a new workspace importer
can reuse those resolutions without selecting newer package versions. A frozen
offline install, configurator generation, RPC validation, authored-source typecheck
and Wrangler dry-run must pass before use. `generate-types.mjs` generates runtime
types against authored source rather than typechecking generated wrappers twice.

Only this Gatekeeper's private environment receives `KOTODAMA_BRIDGE_ORIGIN` and
`KOTODAMA_BRIDGE_SECRET`. The origin is fixed by the deployment operator and is not
chosen by a user or Gadget. Keep both configuration and state outside the public
source package. Do not enable the generic MCP_ALLOW_INSECURE bypass.
The resource identifier uses a reserved `.invalid` HTTPS URL so the native
connection UI preserves it. It is an identity, never a network destination.
The vendor ID is the lowercased binding suffix `kotodama_brief`.

OS account provisioning creates an opaque principal reference. The caller cannot
choose it; the vendor's verifier returns that same reference. The operator must
then register that observed principal and explicitly grant the handoff scope on
the private bridge. Account creation alone grants no source access or inference.
The initial implementation permits only the same OS account to observe its
binding. It does not implement team/department ACL reconciliation.

Reads use the native observation authorizer. Inference uses a distinct queued
action with no auto-approvable kinds. Applying that action submits an invocation;
it does not mean inference or the canonical Task is complete. The Gadget stores
only its request locator and reads source/result through the Gatekeeper again.
Queued approval is persisted and displayed until native `applyAction` or
`rejectAction` runs, including after Gadget restart. Every successful bridge
response is checked against a closed wire contract. The Gatekeeper pins the
complete source/grant binding; a replacement scope requires a fresh binding.
An uncertain approval RPC is kept as unknown, never fabricated as a rejection.
Only the native queue can subsequently apply or reject the retained action ID.
Plain HTTP is accepted only for literal loopback `127.0.0.1`; remote transports
must use HTTPS. The local operator still verifies the SSH/socket protection.
An account revoke blocks local reads immediately and attempts to cancel/revoke its
bridge grant; failed network delivery cannot guarantee remote cancellation.

The Gadget displays Japanese requirements candidates. It does not expose backend
credentials or an arbitrary prompt/command/endpoint input. Unknown responses keep
the existing request ID and do not silently make another model call.

API provenance: [official Gatekeeper contract](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/packages/workshop-shared/src/gatekeeper.ts),
[bundled Blueprint format](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/docs/blueprints.md).
This package is new Kotodama code using those public interfaces; no private
repository history or runtime account state is included.
