# Kotodama

Talk in Discord, turn the conversation into goals and work, let OpenAI agents cooperate, and receive checked results in the same place. Preserve the original request, corrections, decisions and useful learning.

Kotodama retired its independent Company OS on 2026-10-21. The subsequent decision to exclude the Discord product was too broad and is corrected: the user experience continues, while duplicated agent infrastructure is removed. The [Japanese README](README.md) is authoritative.

Product development is consolidated in the existing [discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template), tracked by [product issue #3](https://github.com/Kotodama-Project/discord-voice-template/issues/3). It is a candidate, not an accepted replacement for deployed services. Historical text-to-Codex-to-result checks do not establish current voice, streaming transcript, cooperative execution or user acceptance. The old main, voice template and private deployments contain divergent changes that require selective migration.

Keep only the Discord transport, speaker and access boundaries, original/corrected text, request-to-OpenAI-session mapping, cancellation, restart recovery and result delivery. A small durable connection store is allowed; a new Company OS, swarm or general knowledge engine is not. OpenAI product access, personal CLI authentication and a hosted bot's API access/cost are separate deployment questions.

This repository remains the migration entry point. Do not create another repository or archive this one before product acceptance, outstanding work and recovery references have a verified home. Deployment/data migration remains open in [#442](https://github.com/Kotodama-Project/Kotodama-project/issues/442).

Current main contains documentation and development checks, not a runnable bot. Do not deploy it over an existing service. Old source remains at [50ca4d2](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b). See [migration](docs/RETIREMENT.md), [status](STATUS.md) and [remaining work](ROADMAP.md).

The [direct Codex workflow](docs/WORKFLOW.md) remains useful for individual work; it does not replace Discord product acceptance.

[MIT License](LICENSE) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
