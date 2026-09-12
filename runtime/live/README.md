# GPT-Live Voice-to-Work candidate

OpenAI **GPT-Live-1** is the selected cloud voice direction. Read the
[adoption/migration record](../../docs/GPT-LIVE-ADOPTION.md) before integration.
This directory is a tested **control-plane candidate**, not a deployed Discord
bot, automatic coder, PC connector, VM provisioner or public Voice service.

- `control.py`: namespaced rooms/workspaces, owner grants, replay fence, room writer
  lock, isolated-runner callback, bot capacity and default-deny playback.
- `openai_live.py`: official Live session/start/audio/transcript/client-delegation/
  quiet-context/close contract. Inject an official `AsyncOpenAI` client whose
  installed version supports `client.live.connect()`; imports are network-free.
- `../../tests/test_live_candidate.py`: synthetic tests without provider credentials.

```sh
python -m unittest discover -s tests -p test_live_candidate.py -v
```

Host wiring order: authenticate ingress and consent, allocate an allowlisted room,
bind a source track, start the Live receiver, wait for `started`, then supply paced
24 kHz mono PCM16. Keep receiving while work runs. Reconcile/finalize attributed
requests separately before calling `RoomController.submit`. Only a trusted host
policy service may populate `consent` and `grants`. Never deserialize model output
straight into those authority stores. Treat transcript and tool output as data.

The runner is `async runner(intent, workspace, check_authorized) -> Receipt`.
It must enforce a real sandbox, call `check_authorized()` before each tool action,
and verify the outcome. It must not return success simply because an LLM said
"done". Stop/revocation also requires terminating its real child processes; coroutine
cancellation alone leaves the ledger `uncertain`. Reconciliation needs independent
receipts and remains a production-integration gate.

`BotLeases` and `RoomHub` are single-process coordinators, not distributed leases.
Each listening `LiveSession` binds one known input speaker and never plays output
by default. Use a separate fresh reply session and shared room `PlaybackGate` only
for an addressed reply; flush and recheck the actual playback queue on revocation.
The host must manage common-room context, media clock alignment, bounded queues,
backpressure, idle/maximum duration and provisioned bot capacity. Consent withdrawal
requires `revoke_consent()`, input-buffer purge and `close()` (or transport teardown).
Do not put API keys, raw voice, transcripts or the runtime SQLite file in this repo.

No shell runner or default host-wide permission is supplied. No code in this
candidate connects Slack or Teams, decodes Discord media or replaces the existing
voice owner. Those adapters must satisfy the migration acceptance gates first.
