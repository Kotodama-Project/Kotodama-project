# Kotodama information access language

**Information reference**: A stable reference to the information being handled. Its content revision can change without giving the information a new identity.
_Avoid_: filename as identity, access credential

**Principal reference**: An opaque identifier for a human, agent or service to which an authenticated caller can be resolved. The identifier itself is not proof of identity or permission.
_Avoid_: display name, email as identity, token

**Information custodian**: The principal responsible for keeping the information's classification and audience correct. Responsibility does not imply permission to read, review or publish it.
_Avoid_: implicit administrator, all-access owner

**Information classification**: The handling category of information: unclassified, public candidate, internal, restricted or secret. It describes sensitivity without defining the people who may see it.
_Avoid_: audience, publication approval

**Access policy**: A revisioned statement of the custodian, explicit readers, reviewers, expiry and revocation state for one information reference. Reading, reviewing and publishing are distinct permissions.
_Avoid_: company membership as blanket access, Task execution authority

**Public candidate**: Information that may be considered for publication after the separate release decision. The classification is not an instruction to publish or proof of public approval.
_Avoid_: already public, automatic Human GO

**Knowledge concept**: One human- and agent-readable OKF Markdown document with provenance, trust, lifecycle, and Kotodama projection metadata. Its path is a stable bundle concept ID, not the identity or authority of the underlying information.
_Avoid_: Current Truth, Task record, permission, executable instruction

**Knowledge bundle**: A hierarchical collection of concepts, indexes, logs, and rebuildable machine projections used for progressive disclosure. The public repository bundle contains public-candidate projections only.
_Avoid_: second Company database, unrestricted memory, private source archive

**Knowledge projection**: Catalog, graph, search result, or generated agent context derived from current concepts and source references. It can be rebuilt and invalidated; it never self-promotes to policy, decision, access, or runtime authority.
_Avoid_: proof of correctness, proof of deployment, automatic approval
