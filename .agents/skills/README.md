# Public Kotodama skills

This directory is the public, portable reference pack for Kotodama Agent
Skills. It is intentionally smaller than the private `BecomeOne` runtime
surfaces: public readers get the intent and safety contracts without private
hosts, credentials, raw conversations, provider commands, or deployment
recipes.

Each skill has a standard `SKILL.md` frontmatter manifest (`name` and
`description`), scopes model invocation to the Kotodama public repository, and
gives every numbered procedure step its own `Done when:` criterion. The skills
are safe to inspect or plan by default. They do not
grant permission to write, publish, send, delete, rotate credentials, or
promote a candidate. The public project remains `NO_GO_UNPUBLISHED` until its
own evidence and human-governance gates are satisfied.

## Included skills

| Skill | Use it for |
| --- | --- |
| `kotodama-intent` | Resolving missing choices and recording scope, agreements, and acceptance in the existing owner. |
| `kotodama-plan` | Making a bounded plan with acceptance, stop, and rollback conditions. |
| `kotodama-research` | Reusing current evidence and recording claim-level provenance, freshness, and contradictions. |
| `kotodama-delegate` | Bounded subagent work with ownership, leases, and receipts. |
| `kotodama-validate` | Read-only validation and machine-readable evidence receipts. |
| `kotodama-implement` | Applying an approved local change without contaminating dirty state. |
| `kotodama-public-review` | Separating local, device, provider, public, and human-go evidence. |
| `kotodama-surface-audit` | Auditing skill manifests, links, triggers, and stale assumptions. |
| `kotodama-agent-status` | Diagnosing responsibility indexes and offline observation snapshots without runtime controls ([diagnostic contract](../../docs/AGENT-DIAGNOSTICS-INTEGRATION.md)). |
| `kotodama-handoff` | Resuming work from a compact, redacted, evidence-bound handoff. |
| `kotodama-luna-swarm` | Running a bounded Task swarm with owner-bound packets, peer receipts, and independent review ([Luna Task swarm](../../docs/LUNA-TASK-SWARM.md)). |

The normative shared contract is [SKILL-OPERATING-CONTRACT.md](../../docs/SKILL-OPERATING-CONTRACT.md).
Use the public repository's existing Company Pack validators and review-chain
docs for executable checks; this pack does not invent a second runtime CLI.

Select a small set for the outcome instead of loading the whole catalog.
[Skill workflow evaluation](../../docs/SKILL-WORKFLOW-EVALUATION.md) separates
input delivery, deterministic behavior, and the still-required review of
model reasoning and useful results.

Run the local audit with `python tools/audit_public_skills.py`. To check known
catalog collisions too, repeat `--external-skill-root <declared-root>` for each
catalog. The resulting claim covers only those declared roots.
