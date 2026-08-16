---
name: kotodama-surface-audit
description: Audit public Kotodama skill surfaces for manifest validity, trigger collisions, broken links, stale runtime claims, and unsafe executable examples.
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
   size; report missing roots instead of silently widening scope.
2. Check frontmatter `name`/`description`, unique names, required intent/
   trigger/non-trigger/completion sections, relative links, and description
   length.
3. Flag fixed model claims, stale ABI/runtime paths, private host/path
   identifiers, direct public/main mutation, and unbounded executable recipes.
4. Emit a deterministic JSON report with file digests, counts, findings,
   timestamps, and exit code. Never rewrite the audited surface.

## Completion

`COMPLETED` means the declared audit ran to its boundary. It is `LOCAL`
evidence only. Any finding keeps the candidate out of public promotion until a
separate review resolves it.

## Recovery

Fix findings in a new candidate revision, rerun the audit, and compare the new
file list and digests. Preserve the failing report as historical evidence.
