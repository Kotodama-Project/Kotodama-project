# Session Conversation/Event Ledger Candidate 2

これは、Kotodama の Session に関係する会話と操作を後から再構成するための、
**未コミットの公開候補契約**です。実際の Discord、Notion、GitHub、Codex、Claude、
Google Drive や provider へ接続する adapter は含みません。

## Canonical boundary

`schemas/session-conversation-event-ledger.schema.json` が一つの append-only
Conversation/Event Ledger event の閉じた shape です。Conversation、Session、Decision、
Swarm、Knowledge document はこの ledger から rebuild する projection であり、別の
SSOT ではありません。

- `event_id`、`sequence`、`previous_event_hash`、`event_hash` が追記順序と drift を束縛する。
- `source` は `discord_text`、`discord_voice`、`notion`、`github`、`codex`、`claude`、
  `google_drive`、`n8n`、`system` のいずれかで、locator、revision、actor/speaker、authority role、
  thread/channel/document/repository ref、evidence ref を分離する。
- `content` は protected payload vault の opaque ref、SHA-256、span だけを持つ。raw text、
  transcript、audio、provider response は public Git record に埋め込まない。artifact stage と
  `derived_from_event_refs` が raw/derived lineage を明示し、derived event は親の vault ref、
  manifest ref、digest を再利用できない。
- Session 未確定の event は `UNASSIGNED_INBOX` として追加し、後から `session_binding`
  event を追加する。元 event の session ref/revision を書き換えない。
- LLM の抽出は `LLM_CANDIDATE` に限る。`HUMAN_CONFIRMED` 等には human evidence と
  human decision ref が必要で、`current_truth_ref` と execution authority は常に null/false。
- source update/delete/ACL loss は、影響する context pack、projection、task などの
  opaque ref を持つ invalidation event として追加する。削除 readback が未確認なら fail closed。
- `correction`、`withdrawal`、`confirmation`、`decision_confirmed` は先行する target event
  ref を必須とし、候補を projection 上で supersede する。
- `pre_compact` は `PROJECTION_ONLY` の summary event であり source authority ではない。

### Knowledge representation boundary

The rebuildable knowledge document may be rendered in the owner-confirmed Google
Cloud **Open Knowledge Format (OKF) v0.2** as a generated projection candidate
for human/agent knowledge representation. Owner-reviewed curated OKF may later
be canonical for interpretation, but this generated projection is not authority.
This candidate does not make OKF responsible for the raw archive, authority,
ACL, synchronization, or audit semantics: those remain respectively in the
protected payload vault, governed decisions, source/knowledge-scope contracts,
adapter/recovery state, and this event ledger.
The projection emits only an `OKF_V0_2` representation ref, a profile-requirements
ref, `CANDIDATE_UNVERIFIED` status, and explicit false authority-boundary claims;
it does not materialize or publish an OKF bundle. A later profile contract must
close stable IDs, revisions, digests, authority, supersession, typed links, CAS,
and erasure semantics.

### Discord Voice raw-source boundary

The private payload-vault contract for a Discord Voice source must retain a
structured JSON object containing exact time, speaker/track identity,
channel/session/source locator, raw recognition text, content digest,
consent/retention policy revision, and acquisition/provenance refs. The public
event stores only the vault manifest ref, digest, span, and opaque source
metadata. Derived stages are separate refs and never overwrite
raw bytes or text:

```text
raw PCM/event JSON -> per-speaker ASR -> optional alignment
-> speaker-attributed transcript -> deterministic/contextual corrected transcript sidecar
-> whole-conversation minutes -> Source Evidence / intent events

Phoneme/G2P is an optional dictionary/alignment aid, not an assumed audio
recovery stage.
```

The vault manifest and retention/deletion enforcement are a private follow-up
contract; this public candidate intentionally does not embed raw recognition
text or audio.

Artifact lineage is a forward-only DAG. `RAW_AUDIO` and `RAW_SOURCE_JSON` are
roots; `RAW_ASR` must derive from an earlier root, `ALIGNED_TRANSCRIPT` from
`RAW_ASR`, and `SPEAKER_ATTRIBUTED_TRANSCRIPT` from either `RAW_ASR` or the
aligned transcript. `CORRECTED_TRANSCRIPT` is a separate sidecar/diff from
speaker attribution; `MINUTES` follows speaker attribution or correction; and
`SOURCE_EVIDENCE` follows an earlier transcript or minutes event. Alignment and
correction may be skipped, but same-stage, later, backward, unrelated-session,
self, and vault-ref/manifest/digest-reusing parents are refused.
Those three content identity values are also globally unique across distinct
accepted event IDs; a non-parent sibling cannot alias an earlier vault object,
manifest, or digest (`CONTENT_ARTIFACT_ALIAS`).

### Tiered retention/archive boundary

Retention is a pluggable policy binding, not a fixed 30/180-day rule. Each event
records the policy revision, an abstract storage class (for example
`ENCRYPTED_COLD_ARCHIVE`), an **Archive Target / Session Archive Vault** kind and
opaque URI ref, exact package digest, encryption declaration/ref,
archive/restore/delete state, and any receipt refs. Raw audio and
speaker-attributed transcript may be assigned to an encrypted cold/archive
tier; searchable minutes, Source Evidence events, and OKF knowledge documents
remain separate derived layers. Archive backend selection is OPEN: this
contract adopts no backend or provider.
Archive, restore, deletion readback, and derived invalidation remain fail-closed
until their receipts are independently available.

The validator treats archive fields as a coherent state tuple. The following
table is normative for the metadata candidate (receipt refs are opaque and do
not claim that an archive backend was contacted):

| Combination | Result | Required evidence / rejection |
|---|---|---|
| target `NONE`, archive `NOT_REQUESTED`, restore `NOT_REQUESTED` | accept | no archive, restore, or snapshot receipt |
| `ENCRYPTED_COLD_ARCHIVE` + target `NONE` | reject | `COLD_ARCHIVE_TARGET_REQUIRED`; a cold archive must name an Archive Target |
| target present, archive `DECLARED`, restore `NOT_REQUESTED` | accept | archive receipt; no restore receipt |
| archive `RESTORED` | accept only as a pair | archive receipt + restore `RESTORED` + restore receipt |
| archive `DELETED` | accept only with deletion | deletion state/readback `CONFIRMED` + deletion receipt |
| archive `DELETED` after a restore | accept only if history is retained | keep restore `RESTORED` and its receipt; contradictory `NOT_REQUESTED` plus a restore receipt is rejected |
| restore receipt with restore `NOT_REQUESTED` | reject | cannot silently erase or contradict restore history |
| non-`NONE` archive target plus confirmed deletion/readback/receipt while archive is not `DELETED` | reject | archive/deletion state is contradictory; a `NONE` target may still delete protected-hot source data |

`replay_of_event_ref`, causal refs, artifact parents, lifecycle targets, and
`session_binding.target_event_refs` must all point to strictly earlier events.
Replay also requires session parity: bound events replay only within the same
bound Session, and `UNASSIGNED_INBOX` events replay only other unassigned
events; a mismatch is `REPLAY_SESSION_INVALID`.
Lifecycle confirmations/corrections/withdrawals must target a candidate in the
same bound Session. Reusing a candidate ref for a new model revision is not a
new lifecycle; a new revision must allocate a new candidate ref. Candidate
state may move from `CANDIDATE` to human confirmation, correction, or withdrawal;
confirmation may move to correction or withdrawal, correction may move to
correction or withdrawal, and `WITHDRAWN` is terminal. A later same-candidate
LLM or human reopen is refused. Projection status is monotonic and will not
reopen human confirmation; the validator reports `CANDIDATE_LIFECYCLE_REGRESSION`.

## Hook / connector contract map

Hook は event を生成する契約だけを定義します。connector は source locator と source
revision を opaque に返し、payload bytes をこの public candidate に返しません。

| lifecycle / source hook | canonical event kind | minimum evidence |
|---|---|---|
| SessionStart/open | `session_open` | session ref/revision or `UNASSIGNED_INBOX`, correlation/cursor |
| incoming human message/voice segment | `human_message` / `voice_segment` | actor/speaker ref, source locator/revision, payload vault ref/hash/span |
| tool/agent action | `tool_action` / `agent_action` | actor, authority role, owner/assignee, causation and idempotency |
| decision confirmation/correction | `decision_confirmed` / `confirmation` / `correction` | candidate ref, human evidence, decision/correction ref |
| pre-compact | `pre_compact` | projection summary ref, `PROJECTION_ONLY`; never source authority |
| session end/seal | `session_end` / `session_seal` | cursor, seal event, retention policy |
| source update/delete/ACL loss | `source_update` / `source_delete` / `acl_loss` | invalidation kind, affected projection/context/task refs, deletion readback when applicable |

Source adapter names are contracts only:

| source surface | adapter contract ref shape | public record |
|---|---|---|
| Discord text / Voice | `ref/adapter/discord_text` / `ref/adapter/discord_voice` | locator, revision, actor/speaker, protected payload digest |
| Notion | `ref/adapter/notion` | document ref, revision, ACL/knowledge-scope ref |
| GitHub | `ref/adapter/github` | repository/thread/document ref, revision, evidence ref |
| Codex / Claude | `ref/adapter/codex` / `ref/adapter/claude` | opaque conversation/tool ref, model/extraction candidate provenance |
| Google Drive | `ref/adapter/google_drive` | document ref, revision, ACL/retention refs |
| n8n | `ref/adapter/n8n` | workflow/execution ref, revision, causation and evidence refs |

No row above authorizes a live connector, provider call, capture, send, publication, or
credential use. Current truth and human approval remain outside this candidate.

Session auto-creation is allowed by the product direction, but its activation
contract remains an explicit follow-up to this small candidate: an
auto-created Session must bind Task SSOT, required capability/knowledge/tool grants, an
Plan/Requirement refs when known, an assigned LLM/Agent invocation and model
provenance, Capability/Knowledge/MCP grants, A2A delegation, dependencies and
parallel status, evidence, and invalidation relationships before any execution
projection can be considered eligible. Unknown or ambiguous authority remains
explicit and is never silently approved.
The current ledger can carry opaque owner, assignee, knowledge-scope,
invocation/provenance, and evidence refs without granting those capabilities.

Voice Requirements / GrillU is a case-dependent, channel-neutral facilitator
projection. Natural continuous voice conversation may form requirements; it is
not a rigid UI or mandatory one-question ritual. A facilitator hook should ask
only when uncertainty, risk, or authority requires clarification, and it remains
separate from execution authority.

Autonomous work may later receive a **Disposable Experiment Environment**
grant/lease. That contract must bind the environment owner, exact base revision
or image, scoped data/network/tool grants, budget, TTL, kill switch,
export/evidence boundary, cleanup/destruction receipt, and no ambient authority
inheritance. It may cover a clean clone/worktree/container or an isolated VM and
may be intentionally broken and rebuilt by its owner. This preview records only
opaque handoff refs and does not create or destroy any environment.

Model binding is intentionally opaque in this candidate and does not enforce a
Luna-only absolute. The policy is Luna-first: overwhelming bulk tasks,
Context Packs, research, builds, reviews, and normal swarm execution use Luna.
Sol may occupy upper architecture/integration/audit or hard-judgment roles when
explicitly provenance-bound; Terra may be explicitly selected for an appropriate
balanced task. There is no hidden fallback, and exact runtime/routing rationale
and evidence remain required. Candidate 1's exact public documentation still
contains the superseded Luna-only absolute and needs a separate content-confirmed
follow-up correction; it is not rewritten by this worktree.

## Unattended Improvement Loop (contract-only)

The ledger can carry the lifecycle refs for an unattended improvement loop:

```text
observe evidence/metrics/feedback -> hypothesis + automatic Session/Task
-> bounded disposable experiment -> Luna-first build/review
-> upper-tier Sol audit/integration when warranted -> reversible Git merge
-> monitor -> auto-revert regression -> promote verified learning into OKF/SSOT
```

The loop requires explicit budget, cadence, kill conditions, and evidence at
each transition. It cannot perform unbounded self-modification or cross
provider, deploy, public, credential, or human-data authority without an
explicit grant. GitHub branch/commit/PR/merge actions may be reversible when
independent tests/review and a reliable agent-executable revert path say OK;
force-push/history erasure, repository deletion, visibility/settings/credential
changes remain outside this candidate. No such external action occurs here.

## Validator and projection

The standard-library-only CLI is read-only:

```powershell
python tools\validate_session_conversation_ledger.py validate path\to\ledger.jsonl
python tools\validate_session_conversation_ledger.py project path\to\ledger.jsonl ref/session/example
```

`LEDGER_VALID` checks closed fields, opaque refs, required source locator/hash, actor versus
authority separation, monotonic ingestion time, contiguous sequence, idempotency uniqueness,
hash-chain integrity, causal refs, stale session revisions, Session/Task/Invocation/grant
provenance, candidate-only extraction, Human evidence, policy-deviation completeness,
tiered Archive Target receipts, deletion readback, ACL invalidation, offline recovery, and
explicit integrity markers. Unknown, lost, revoked, or ACL-invalidated selected source
events keep projection access `FAIL_CLOSED`; a later `AVAILABLE` metadata event does not
reopen it. Projection arrays are bounded before serialization: source refs/timeline at
4096, and intent/decision/correction/action/deviation items at 256. Exceeding a bound
returns `PROJECTION_LIMIT_EXCEEDED` rather than truncating. `validate_projection` also
rejects an over-bound saved projection before digest comparison and binds the remaining
fields to a fresh rebuild. A valid result is `LOCAL_PASS` evidence only.
Malformed roots and nested non-object integrity values are refused without
exception; the CLI returns exit 2 rather than a traceback.
The `project` CLI returns exit 0 for a schema-valid `REBUILDABLE`, `INVALIDATED`, or
`INCOMPLETE` projection and emits the projection JSON; refusal remains exit 2.

The projection schema is
`schemas/session-knowledge-projection.schema.json`. It includes source timeline, confirmed
intent, decisions, corrections, action items/owners, evidence, policy deviations, unresolved
questions, omissions, knowledge scope, invalidation state, and the next safe action. It is
rebuildable and always reports `projection_is_source_authority: false`,
`compaction_summary_is_source: false`, `current_truth_changed: false`, and
`public_beta: NO_GO_UNPUBLISHED`.

## Recovery and deletion stop rules

- A missing or corrupt sequence is represented by a later `integrity_marker` / `recovery_marker`; do
  not resequence or rewrite historical bytes.
- An offline replay must carry a recovery cursor and receipt ref. Same event/idempotency retry is
  idempotent; a conflicting duplicate is refused.
- Unknown ACL/knowledge scope, invalid deletion receipt, missing source revision/hash, or a lost
  permission invalidates the affected projection and blocks the next action.
- A compaction summary can guide a rebuild but cannot supply source evidence or Human Decision.

This candidate remains uncommitted and has no device, provider, public, or human-go effect.
