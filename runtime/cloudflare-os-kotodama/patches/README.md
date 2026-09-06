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

Apply with `git apply --check` followed by `git apply` only after checking the
manifest against current source bytes. Preserve both source preimages and the
affected instance's state. Rebuild through the official project scripts and
check authored types and the actual user flow. Existing Gadget instances carry
their own code; a Blueprint patch alone does not update them.

The public asset contains patches and provenance only, without a private model
endpoint, account state, conversation or deployment identifier. Upstream source
remains owned by the upstream repository and its license. This is a local
evaluation customization, not upstream acceptance or production certification.
