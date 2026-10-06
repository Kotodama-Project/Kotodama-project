# License scope and provenance

The project owner's implementation direction, updated on 2026-09-13, selects MIT
for newly authored code and existing code that Kotodama has authority to license.
The root [MIT License](../LICENSE) reflects that direction. It replaces the prior
Apache-2.0 root-license candidate in PR #18.

Third-party conditions remain in force. A root license does not change the
license of dependencies, bundled upstream components, source-derived materials,
assets, or separately marked files. Keep their original copyright and license
notices, including existing MIT notices on migrated material. Their source pins
and license declarations must not be mechanically changed to MIT.

The [2026-09-24 owner decision](https://github.com/Kotodama-Project/Kotodama-project/issues/25#issuecomment-5818551006)
records `@dj-thank` as the accountable rightsholder for the public project and
retains MIT for the admitted BecomeOne extracts. The decision accepts a
per-batch provenance record; it does not authorize publication of the private
source history or settle the rights of every possible future extract.

## Admitted migration batches and notices

| Batch | Machine-readable provenance | Retained license and notice |
|---|---|---|
| A017 hierarchy templates | [A017 provenance](../migration/a017-hierarchy-templates.provenance.json) | MIT; [source notice](../LICENSES/MIT.txt), linked by the templates |
| A019 registry contracts | [A019 provenance](../migration/a019-registry-contracts.provenance.json) | MIT; [source notice](../LICENSES/MIT.txt), referenced by the batch manifest |
| A022 public architecture | [A022 provenance](../migration/a022-public-architecture.provenance.json) | MIT; [source notice](../LICENSES/MIT.txt), linked by the architecture documents |

These records pin source commit `2fc1bf60b0dc8721c96875788447e34adc4c7216`,
source blobs, contribution counts, and the bounded public output. Only authors
recorded with GitHub noreply identities are published as handles; other author
identities remain private. The accepted private-history receipts are recorded
by digest and are not reproduced here.

For these three batches, the retained MIT notice carries the source copyright
(`Copyright (c) 2026 Kotodama Project`) and permission text. Their accepted
provenance records identify no additional third-party `NOTICE` requirement, so
no empty root `NOTICE` is added. The root and Discord runtime retain their own
MIT notices. This finding is limited to those admitted extracts; upstream pins
and package locks do not license a future redistribution of their components.

Material whose licensing authority is unresolved must not be newly exported
on the strength of the root license alone. Review each later migration/export
batch under its existing license and provenance gate, retain any required
third-party notice with the distributed artifact, and record uncertain material
as private-only, regenerated, or dropped.

Generated code, schemas, examples and documentation follow the rights of their
source inputs and recorded contribution provenance. Dependency licenses remain
their own; inspect the pinned dependency manifests and retain required notices
when producing a release artifact or SBOM.

## Release inventory evidence

The [release workflow and verification procedure](CI.md#release-の-sbom-と-provenance-を確認する) produce
three CycloneDX inventories from the Python CI, Task swarm, and Discord locks,
include their checksums, and attest them alongside the source archive and smoke
report. The [v0.2.0-preview draft receipt](https://github.com/Kotodama-Project/Kotodama-project/issues/122#issuecomment-5975513155)
records six attachments and successful checksum, archive-lock, and build
provenance verification at `1f5c0eec4ea7ba2a804175f6924555e0bffea982`.
This is recorded historical evidence, not a new release or a rights review of
installed dependencies. SBOMs do not assert component licenses or prove that
required redistribution notices are complete. Later release artifacts must
repeat the inventory and notice check for their exact bytes.
