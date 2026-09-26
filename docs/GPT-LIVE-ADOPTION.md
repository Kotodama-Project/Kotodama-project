# GPT-Live adoption and Voice-to-Work migration

Decision date: 2026-09-12 (Asia/Tokyo).
Direction: adopt **OpenAI GPT-Live-1 / Live API** as Kotodama's primary cloud voice
provider, following the project owner's change request. This is not a Discord
API product and is not the old OpenAI Realtime event protocol.

Implementation status: **candidate_only / NO_GO_UNPUBLISHED**. Provider selection
is a product decision, not evidence of a deployed bot. Public Beta, public
invitations, production execution and Final Human GO remain unchanged. This
migration record supplements the older local-ASR-only description in README;
it does not declare the existing service replaced or a second runtime owner.

## Product behavior

Kotodama listens without greetings, backchannels or unsolicited progress speech.
An authenticated participant directly asks it to implement a change; within an
owner-issued safe-development grant, it prepares a work item and runs the agent
without demanding manual approval for every reversible edit/test. It reports
progress in the room's text/task surface. It speaks only when addressed, including
when someone asks for the result. Merely mentioning its name, quoting another
request, debating an idea, or reading a document does not authorize execution.
An already assigned job continues quietly; silence is not cancellation.

GrillU becomes one strategy within a general **Interaction Policy**: determine
addressee, task completeness, ambiguity, correction and response channel. Ask at
most one essential clarification at a time. Do not force a question when the
request is already sufficiently precise. Unknown speakers and ambiguous action
intent stay candidates. A classifier's confidence is not an access token.

## Architecture and breaking changes

```text
Discord / Slack / Teams authenticated adapter
  -> membership + cloud-processing consent + source identity
  -> RoomHub(surface, tenant, channel)
       -> stable room workspace + isolated worker binding
       -> per-source LiveSession -> source-labelled transcript fragments
       -> intent finalizer / Interaction Policy
       -> addressed complete request + host-issued capability grant
       -> durable replay fence + single-writer room lock
       -> bounded local / VM / container agent -> tests + verification receipt
       -> same-room private text status
       -> fresh addressed reply session -> PlaybackGate -> platform audio
```

| Previous constraint | New direction |
|---|---|
| Local ASR and 900-second rotation precede useful work | Live is the low-latency conversation path; optional 900-second evidence rotation must not delay work |
| One global voice/session state | Room-scoped state, task lifecycle, workspace and media ownership |
| A particular VM/container is the assistant | A stable room workspace is bound to a replaceable worker: local PC, Compose or Proxmox |
| Discord-specific intent handling | Surface-neutral ingress, authority checks and result projection; provider capability negotiation |
| GrillU as a mandatory interview | General Interaction Policy, with minimal clarification only where needed |
| Model prompt expected to guarantee silence | Application-controlled, default-deny playback and independent execution authorization |

Local/private processing and the existing ASR/evidence path are retained as
explicit operating modes. Selecting Live requires consent to send audio to
OpenAI; lack of consent must not silently enable cloud processing. `store: false`
is set, but is not a claim of Zero Data Retention or a substitute for provider
data-policy review. A new or revoked participant must have their own stream
stopped and unsent data purged before further processing.

### Speaker attribution and simultaneous rooms

The candidate binds each Live input session to **one authenticated source track**.
Keep Discord receiver user IDs and reconnect/SSRC mapping epochs; exclude the bot's
own output and other bot tracks. Do not label mixed audio as the latest speaker or
use model-guessed names/voice similarity as authority. Input transcripts retain
room, actor, session ID, exact text and original session-relative intervals;
assistant transcripts have no human actor. The media adapter must align source
sample clocks before combining different sessions; arrival time is not alignment.
Per-source sessions need measured cost/concurrency budgets and shared-room context.

A single Discord bot identity has one voice connection per guild. Concurrent VCs
in the same guild therefore require explicitly provisioned, legitimate bot
identities (a bot pool), not merely additional gateway shards. Exhausted capacity
must report busy rather than moving an existing room's connection. `BotLeases`
models this constraint for a single process. A fleet needs a distributed ownership
lease and verified Discord transport behavior. No self-bots or encryption bypasses.

### PC / VM / container execution

The API does not automatically grant access to a PC or provision a VM. An
owner-installed worker exposes a narrow, authenticated capability interface. Its
room binding selects the allowed repository/worktree, account, resource budget,
network policy and expiry. Do not expose a general host shell, Docker socket,
Proxmox administrator credential or whole home directory to conversation input.
The runner calls the supplied authorization check before each tool step, enforces
OS isolation, stops child processes on cancellation, and emits an actual receipt.
A directory created by `RoomHub` is **not** a VM, container or security sandbox.

Automatic candidate operations in this slice are `code.inspect`, `code.edit`,
and `code.test`, restricted further by an owner-issued grant. Deployment, merging,
external messaging, destructive operations and credential changes are not granted
by this interface. Future policy lanes can add those with separate explicit
capabilities; do not rename them to `code.edit` to bypass the boundary. Run tests
on untrusted code only in the configured isolated worker, not the voice process.

### Execution and speech are independent

Live delegation events carry IDs/timestamps, **not task text**. Raw transcript
deltas have no authoritative completed-user-turn event. A finalizer must reconcile
fragments, source attribution and corrections before creating an `Intent`.
Source IDs/revisions must survive transport reconnects and be bound to the actual
request. Model-generated IDs, transcript arrival gaps or a delegation alone are
not permission to run tools.

SQLite stores request hashes/status and serializes writes per room across
connections. Duplicate source revisions do not run twice. A reused revision with
changed content is rejected. An interrupted or unknown operation stays locked as
`uncertain` until an operator verifies the external outcome; do not delete the
ledger to retry. This is an idempotency fence, **not** a durable job dispatcher,
recovery worker or complete authorization database.

Listening sessions receive no playback permit. An addressed reply uses a **fresh
Live session** with a bounded permit; a revoked session cannot be reopened. This
avoids replaying stale generated audio when a later request opens the gate. Drop,
never defer, audio outside the permit. The final media playback queue must recheck
and flush on revoke/expiry. Live audio has no output-done event or per-response ID;
backend completion and transcript timestamps do not prove playback finished.
Quiet progress uses `session.thinking.append`, not `session.commentary.append`.
Quiet context is still model-visible and must never contain secrets.

## Included and not yet included

| Capability | Evidence in this change |
|---|---|
| Official Live protocol and SDK-shaped lifecycle | `runtime/live/openai_live.py`; synthetic SDK contract tests |
| Per-room local workspace, explicit authority, durable replay/single-writer fence | `runtime/live/control.py`; local SQLite/async tests |
| Consent boundary, source-labelled fragments, quiet output, bot-pool capacity | Synthetic positive and adversarial tests |
| Real Discord gateway, DAVE, Opus and paced resampling | **Not implemented in this candidate**; existing adapter migration remains required |
| Voice intent finalization and automatic agent invocation | Control boundary exists; **production finalizer and runner are not wired** |
| VM/container provisioning and authenticated PC worker | **Not implemented**; callback contract is not a provisioner |
| Slack/Teams text ingestion or meeting transport | **Not implemented**; separate tracked workstream |
| Locked official SDK release, real API authentication/usage and device test | **Not verified**; no key was provisioned or used for these tests |

The public runtime remains opt-in: importing it opens no sockets, reads no keys,
starts no processes and modifies no existing bot. Use an official `AsyncOpenAI`
client with `client.live.connect()` support; an older SDK fails explicitly rather
than falling back to Realtime. Pin the verified SDK and media dependencies before
an integration release. Do not guess an SDK version from the model release date.

## Migration acceptance gates

1. Bootstrap an approved implementation session in the runtime-owning repository;
   preserve its existing source/intent/work/evidence contracts. Establish one
   authoritative capture and execution owner per room. No parallel legacy/new
   owner may submit duplicate work.
2. Lock and exercise a Live-capable official SDK. Check start/close acknowledgments,
   bounded PCM queues, paced silence/audio, socket loss, cumulative usage, and idle
   and maximum-duration budgets. Measure latency and cost rather than inventing them.
3. Exercise DAVE-compatible Discord receive/send with two identified participants,
   interruptions/overlap, rejoin and two simultaneous VCs in the same guild. Verify
   sample-rate conversion with signal tests. Assert zero playback outside a permit.
4. Demonstrate a spoken request -> finalized attributed intent -> isolated code
   change -> tests -> PR/receipt without manually retyping the request. Show negative
   controls for casual discussion, quoted instructions, unknown speaker, identity
   remapping, revoked consent/grant, duplicate delivery, timeout and correction.
5. Prove runner read/write/egress boundaries, per-room isolation, cancellation of
   actual child processes, reconciliation of uncertain work and restart recovery.
   Scope any granted PC access explicitly; do not infer authority from audio.
6. Keep rollback to the previous voice owner possible. Reconcile in-flight jobs
   before cutover/rollback. Remove the old path only after replacement evidence;
   preserve optional local ASR and 900-second evidence delivery.
7. Complete separate Slack/Teams connector gates before advertising support. Slack
   Calls API represents third-party calls; it is not evidence of raw Huddles audio
   access. Teams real-time media has its own Graph permissions, deployment and
   platform requirements. Negotiate capabilities; never pretend all three provide
   the same media API.

## Local validation

```sh
python -m unittest discover -s tests -p test_live_candidate.py -v
```

On Python 3.13.5, all **36** added synthetic tests passed. They exercise default
silence, bounded/fresh reply permits, exact source text and timestamps, grants,
expiry/revocation, room isolation, replay/restart, single-writer locking, uncertain
outcomes, concurrent work, protocol ordering, quiet context, graceful close and
startup/close failure. No real audio, Discord token, OpenAI key or private workspace
was used. Whole-repository and Python-matrix validation is delegated to the added
GitHub Actions workflow and must be reported separately from this local result.

## Primary sources checked on 2026-09-12

- OpenAI release (displayed publication date **2026-09-10**): https://openai.com/index/introducing-gpt-live-1-in-the-api/
- Live quickstart: https://developers.openai.com/api/docs/guides/live
- WebSocket/PCM protocol: https://developers.openai.com/api/docs/guides/voice-websockets
- Client delegation: https://developers.openai.com/api/docs/guides/live-delegation
- Transcript/session/usage semantics: https://developers.openai.com/api/docs/guides/live-conversations
- Discord voice/DAVE: https://docs.discord.com/developers/topics/voice-connections
- Discord encryption rollout: https://discord.com/blog/every-voice-and-video-call-on-discord-is-now-end-to-end-encrypted
- Discord.js connection capacity: https://discordjs.guide/voice/voice-connections
- Slack Calls: https://docs.slack.dev/apis/web-api/using-the-calls-api/
- Teams media requirements: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots
