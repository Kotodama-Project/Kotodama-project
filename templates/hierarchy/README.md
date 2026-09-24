# Public hierarchy templates

Status: `candidate_only` / `NO_GO_UNPUBLISHED`

These provider-neutral templates describe a small planning hierarchy without
creating runtime authority or importing operational state:

1. [index](index.md) is a navigation projection, never a second source of truth;
2. [project](project.md) binds an outcome, boundary, owner role, and rollback;
3. [phase](phase.md) adds entry and exit criteria;
4. [requirement](requirement.md) states a testable need and its dependencies;
5. [plan](plan.md) orders bounded steps and stop conditions;
6. [task](task.md) binds one work item to intent, session, evidence, and rollback;
7. [session context](session-context.json) is a minimal structured context stub.

## Safety contract

- Replace every `{{PLACEHOLDER}}` before treating a copy as a candidate.
- Keep identifiers opaque and keep personal data, credentials, private
  endpoints, provider configuration, transcripts, and operational logs out of
  public copies.
- Use references and digests instead of embedding source bodies or secret
  evidence.
- Leave acceptance items unchecked until evidence exists.
- A completed child never promotes its parent automatically.
- Navigation indexes are derived views; the referenced artifact remains the
  canonical record.

## Validation

Run the read-only, standard-library validator from the repository root:

```bash
python tools/validate_migration_batch_a017.py
```

The validator binds this pack to the ten allowlisted source blob identifiers
in `migration/a017-hierarchy-templates.manifest.json`, checks the eight public
destinations, verifies component attribution, and scans the candidate payload.
A pass is candidate evidence only. Admission is recorded separately: Issue #25
holds the owner's rightsholder decision (2026-09-24), the provenance file lists
the source commits and authors, and the manifest records the private
source-history scan receipt and the independent review.

## Migration and license boundary

The hierarchy was re-authored from the A017 template family without importing
source Git history or private operational references. The malformed duplicate
requirement source is classified `SUPERSEDED`; the two task sources are
explicitly consolidated into `task.md`.

This source-derived batch is distributed under the MIT License. See
[`LICENSES/MIT.txt`](../../LICENSES/MIT.txt), the deterministic migration
manifest, and `migration/a017-hierarchy-templates.provenance.json`. The
repository root license is also MIT (#18); this component keeps its own notice
and provenance record.
