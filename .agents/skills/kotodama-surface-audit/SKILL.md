---
name: kotodama-surface-audit
description: Use only for the Kotodama public repository to audit public skill manifests, trigger scope, step criteria, links, and unsafe examples.
---

# Kotodama skill-surface audit

## Intent

Catch documentation drift before a skill is copied, loaded, or published. The
audit is deterministic and read-only.

## Triggers

Use after adding or refreshing a `SKILL.md`, changing a public skills catalog,
or reviewing a candidate branch for public publication.

## Non-triggers

Do not auto-fix files, regenerate a catalog, install dependencies, contact a
provider, or treat a clean manifest audit as a release or Human GO.

## Procedure

1. Discover only the declared skill roots and read UTF-8 bytes with bounded
   size; report missing roots instead of silently widening scope. Done when:
   every discovered file is within a declared root and count/byte ceiling.
2. Check frontmatter `name`/`description`, unique names, required intent/
   trigger/non-trigger/completion sections, relative links, and description
   length. Done when: each procedure step also has a checkable `Done when` rule.
3. Flag fixed model claims, stale ABI/runtime paths, private host/path
   identifiers, direct public/main mutation, and unbounded executable recipes.
   Done when: every deny rule was evaluated for every public skill.
4. Emit a deterministic JSON report with file digests, counts, findings,
   timestamps, and exit code. Never rewrite the audited surface. Done when:
   findings include declared external-catalog name/description collisions.

## Completion

`COMPLETED` means the declared audit ran to its boundary. It is `LOCAL`
evidence only. Any finding keeps the candidate out of public promotion until a
separate review resolves it.

## Recovery

Fix findings in a new candidate revision, rerun the audit, and compare the new
file list and digests. Preserve the failing report as historical evidence.
