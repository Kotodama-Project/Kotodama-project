# Public Kotodama skills

This directory is the public, portable reference pack for Kotodama Agent
Skills. It is intentionally smaller than the private `BecomeOne` runtime
surfaces: public readers get the intent and safety contracts without private
hosts, credentials, raw conversations, provider commands, or deployment
recipes.

Each skill has a standard `SKILL.md` frontmatter manifest (`name` and
`description`) and is safe to inspect or plan by default. The skills do not
grant permission to write, publish, send, delete, rotate credentials, or
promote a candidate. The public project remains `NO_GO_UNPUBLISHED` until its
own evidence and human-governance gates are satisfied.

## Included skills

| Skill | Use it for |
| --- | --- |
| `kotodama-intent` | Turning a request into an intent candidate with scope and non-goals. |
| `kotodama-plan` | Making a bounded plan with acceptance, stop, and rollback conditions. |
| `kotodama-research` | Source-backed research with claim-level provenance and freshness. |
| `kotodama-delegate` | Bounded subagent work with ownership, leases, and receipts. |
| `kotodama-validate` | Read-only validation and machine-readable evidence receipts. |
| `kotodama-implement` | Applying an approved local change without contaminating dirty state. |
| `kotodama-public-review` | Separating local, device, provider, public, and human-go evidence. |
| `kotodama-surface-audit` | Auditing skill manifests, links, triggers, and stale assumptions. |
| `kotodama-handoff` | Resuming work from a compact, redacted, evidence-bound handoff. |

The normative shared contract is [SKILL-OPERATING-CONTRACT.md](../../docs/SKILL-OPERATING-CONTRACT.md).
Use the public repository's existing Company Pack validators and review-chain
docs for executable checks; this pack does not invent a second runtime CLI.
