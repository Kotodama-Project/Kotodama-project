# Pinned evaluation patches

`manifest.json` identifies the official source revision and the exact before /
after SHA-256 values for these two small patches:

- `document-block-validation.patch`: invalid blocks raise before persistence.
  A full-document writer must receive an array of `{ id, html }` objects. String
  arrays, missing fields and duplicate IDs must not silently erase the document.
  An explicit empty array retains its existing clear-document semantics.
- `local-qwen-window.patch`: the selected local Qwen profile reserves 4096 output
  tokens and limits the modeled input budget to 56000, within its 65536-token
  operational deployment. This is an operator profile, not a model benchmark.

Before applying, run `python tools/verify_official_os_patchset.py --source UPSTREAM_CHECKOUT --phase before`
from this repository. This binds every patch file digest, rejects extra paths and
mode/rename/binary changes, and checks the exact clean upstream source bytes.
Then use `git apply --check` followed by `git apply` from the upstream checkout,
and run the verifier with `--phase after` to check the complete changed-path set
and after hashes. Keep one source writer throughout; preflight is not a lock.
Preserve both source preimages and the
affected instance's state. Rebuild through the official project scripts and
check authored types and the actual user flow. Existing Gadget instances carry
their own code; a Blueprint patch alone does not update them.

The public asset contains patches and provenance only, without a private model
endpoint, account state, conversation or deployment identifier. Upstream source
remains owned by the upstream repository and its license. This is a local
evaluation customization, not upstream acceptance or production certification.

## Upstream attribution and change notice

These patch files modify Cloudflare OS, from
`cloudflare/cloudflare-os@c0b6f3e52ff0ab8d44d290647e256936e88e6b57`.
The upstream root [LICENSE](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/LICENSE)
is Apache-2.0; its exact Git blob `f433b1a53f5b830a205fd2df78e2b34974656c7b`
is retained in [UPSTREAM-LICENSE.txt](UPSTREAM-LICENSE.txt). No root NOTICE file
was listed in that exact upstream root tree.

Local modifications, 2026-09-06: strict pre-persistence Document block
validation in `packages/workshop-backend/format-blueprints/workspace-docs/files/server.js`,
and the operator-selected model window in `packages/workshop-shared/src/api.ts`.
The manifest binds both original and changed bytes. These are Kotodama
evaluation changes, not endorsed or accepted upstream changes. Upstream
ownership, license and notices are retained; this scoped record does not close
the separate project-wide rights/provenance obligations in Issue #25.
