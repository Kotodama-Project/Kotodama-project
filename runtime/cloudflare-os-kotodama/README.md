# Kotodama's official Cloudflare OS extension

This directory is a source addon for official Cloudflare OS core
`c0b6f3e52ff0ab8d44d290647e256936e88e6b57`. It provides a native Gatekeeper and
bundled requirements Gadget. It is not a replacement OS or a new identity SSOT.

## Reproducible native workspace

From the Kotodama checkout, with Git and Python 3.12 or later:

```bash
python -S -B tools/prepare_cloudflare_native.py --destination ../kotodama-native-os
```

The destination's parent must exist; the destination itself must not. The command
fetches the exact compatibility commit from the selected Kotodama commit's
[existing integration record](../../governance/cloudflare-os-integration.json),
checks it out detached, and mounts only committed native source:

| Kotodama source in this directory | Path in the official core checkout |
|---|---|
| `gatekeeper-kotodama-brief/` | `packages/gatekeeper-kotodama-brief/` |
| `blueprints/kotodama-requirements/` | `packages/workshop-backend/format-blueprints/kotodama-requirements/` |

Use `--ref <kotodama-commit>` to reproduce an earlier extension, or
`--source-core <local-official-clone>` to fetch that same pin locally without a
network connection. Dirty working-tree edits, untracked configuration and runtime
state are not copied. Commit reviewed source changes before preparing them.
Existing destinations and locations inside either source repository are refused.
A failed preparation keeps its newly created directory for inspection and returns
`NOT_PREPARED`; do not use it as a successful installation or reset another checkout.

Success is `PREPARED_NOT_INSTALLED`, with the two actual commit IDs, file count and
core's integrity-pinned package manager. It means source assembly only: no package
install, patch application, service startup, bridge configuration or provider call.
The official core stays outside Kotodama; do not commit its tree back into this repo.
This is an additive evaluation workspace, not production self-host certification.

## AI maintenance loop

Change this extension in Kotodama, not a second fork of the OS. Run the small offline
regression before preparing a new workspace:

```bash
python -S -B -m unittest discover -s tests -p test_cloudflare_native_workspace.py -v
```

The path-scoped [native addon workflow](../../.github/workflows/cloudflare-native-addon.yml)
prepares the real official source, verifies the package-manager archive against the
native core's `packageManager` integrity, generates the additional workspace
importer, and refuses changes outside the lock's importer section. It then performs
a scripts-disabled frozen install and runs the **existing** native approval test.
The dependency diff and test log are retained for review. This test uses doubles
for queue, storage and transport; it does not prove a live OS, authentication or
model inference. The workflow does not run `run-local`, deploy, or use secrets.

Do not substitute `runtime/cloudflare-os/`'s older evaluation pin/toolchain or the
latest upstream HEAD for this addon pin. A compatibility upgrade needs its own
review. The core dev runner and bundled-blueprint builder are reused; no new UI
host, scheduler or Task database is introduced. Track this preparation/CI work in
[#424](https://github.com/Kotodama-Project/Kotodama-project/issues/424), not a second
Task ledger. Existing Project GUI work remains with #385 and its PRs.

## Before runtime use

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
