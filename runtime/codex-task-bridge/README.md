# Private Codex requirements bridge

This bounded adapter turns one previously admitted handoff into a requirements
brief using the operator's existing local Codex CLI account. It does not execute
arbitrary commands or mark a canonical Task complete. The official OS integration
lives in `../cloudflare-os-kotodama/`.

The operator creates a private configuration with `stateRoot`, `reviewStateRoot`,
optional first-use `seeds` in the existing review catalog format, `expectedHost`,
`port`, `grant` and `runner`. The service secret is supplied only as the
`KOTODAMA_BRIDGE_SECRET` process environment variable, never as a client argument,
Gadget binding, model prompt or public configuration.

The explicit startup grant owns the allowed operation (`DRAFT_REQUIREMENTS`),
one authenticated requester principal, one worker principal, handoff ID and
revision/digest, policy revision, expiry and at most three invocations. Its
`work_order_ref` is an audit locator, not a string that obtains authority. The
operator must bind this configuration to the actual current Work Order before
starting the service. Neither a caller nor model can supply or widen the grant.

The requester must be a registered human and the worker a registered agent;
both must currently have read access. Secret/unclassified data, expiry, revocation
and source/policy drift refuse admission. Source and grant are checked again
before inference, after inference and on result retrieval. Revocation cannot
recall data already delivered to the model, but it withholds the new result.

An invocation is persisted before starting the worker. Same-ID retries read the
same invocation, while changed requests conflict. One model runs at a time.
Requests return the source/grant digest obtained from admission; a queued request
cannot silently switch to a replacement grant with the same numeric revision.
Interrupted invocations do not automatically rerun on restart. This is a private
invocation journal, not another Project/Task SSOT or an exactly-once provider
transaction. Power-loss durability and malicious local writers are not certified.
Shutdown cancels the active runner with a bounded wait. If termination remains
uncertain, the invocation becomes interrupted and the writer lock remains in
place until an operator verifies the old process has ended. Do not remove that
lock merely to start another writer.

## Started-session evidence

When the existing CLI emits a validated `thread.started` event, the bridge
persists its private thread ID, observation time, requested model and
`ephemeral_codex` kind before accepting later output. The session stays bound to
the existing invocation's request, handoff, source revision and startup-grant
digest. A later failure or interruption preserves that evidence; replaying the
same request never starts another model invocation.

An authenticated `GET /v1/briefs/<request_id>/session` returns this narrow execution
view under the same current access checks. It reports `session: null` when a
start was not observed, `task_binding: "not_connected"`, `resumable: false`, and
never marks a canonical Task complete. A model cannot supply the thread ID in
its brief or attach a new session after the invocation ends.

The journal is now `kotodama/brief-invocations/v2`. Existing v1 files are accepted,
kept byte-for-byte as `invocations.v1.backup.json`, and upgraded with unknown
session evidence rather than invented starts. A conflicting backup refuses the
upgrade. Before rolling back to old code, retain the v2 journal separately and
restore the pre-upgrade copy; do not discard new evidence to make old code start.

This implements observable automatic **ephemeral CLI execution** within the
existing startup grant. It does not create a new Task registry, persistent
conversation, sidebar task, automatic task assignment, or a general session
resumption service. The official [non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
describes JSONL start events and the distinction between ephemeral execution and
persisted sessions.

The CLI executable and its SHA-256, private working directory and model are
operator-selected. The runner requests read-only mode, no project docs, no user
config, ephemeral runs and disabled shell, plugins, apps, browsers, memory and
multi-agent features. The overview and all source summaries are passed to the
model without actor IDs. Existing structured questions are retained even when
the model omits them; this does not certify complete semantic extraction of
every constraint from unrestricted natural language.
This pilot admits at most 16 KiB of rendered source input and 32 distinct source
questions. Larger valid catalog records are refused before creating an invocation;
the operator must select a smaller scope. Input is never silently truncated.
It filters process environment variables and does not forward the bridge secret,
API keys or endpoint overrides. Tool/error events and output overflow are refused;
the known `skip_host_skill_discovery` development-feature advisory is separate.
Requested controls and observed zero tool events are not OS-sandbox attestation.

The response is validated and remains a candidate: objective, deliverable,
constraints, observable acceptance criteria and open questions. It grants no
execution, publication, retention change, deletion or Human GO.

Private operator startup:

```text
node runtime/codex-task-bridge/server.mjs PRIVATE_CONFIG_JSON
```

Use a tracked process and an exact transport lease. A service secret does not
make plain remote HTTP acceptable: use a protected local/SSH transport. This
candidate's intended pilot uses loopback, a dedicated Unix socket and SSH without
opening a new private-network egress route. Never expose this service publicly.

Checks:

```text
node --test tests/node/test_codex_brief_bridge.mjs
```

The offline suite uses an explicitly injected synthetic runner. A real private
Codex invocation and native OS/Gadget acceptance are separate evidence.
Official command behavior: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
