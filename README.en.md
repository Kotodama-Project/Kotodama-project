# Kotodama

Talk in Discord, turn the conversation into goals and work, let OpenAI agents cooperate, and receive checked results in the same place. Preserve the original request, corrections, decisions and useful learning.

Development of the independent Company OS ended on 2026-10-21. The decision to exclude the Discord product was too broad and is corrected: the user experience continues, without rebuilding the entire former infrastructure. Existing features are replaced or retired individually only after the successor meets real-use acceptance conditions. The [Japanese README](README.md) is authoritative.

Product development is consolidated in the existing [discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template), tracked by [product issue #3](https://github.com/Kotodama-Project/discord-voice-template/issues/3). It is a candidate, not an accepted replacement for deployed services. Historical text-to-Codex-to-result checks do not establish current voice, streaming transcript, cooperative execution or user acceptance. The old main, voice template and private deployments contain divergent changes that require selective migration.

Preserve the original intent, corrections, work in progress, permissions, results and delivery records. Keep the Discord experience and its necessary connections, including speaker and access boundaries, request-to-OpenAI-session mapping, cancellation and restart recovery. Decide what UI, storage and connections are needed from concrete use cases and acceptance criteria; do not exclude them by name. Implement the minimum needed without rebuilding the entire former Company OS or duplicated execution infrastructure. Replace features individually only after verifying the successor in real use, including correction, resumption, migration of unfinished work and data, and rollback. OpenAI product access, personal CLI authentication and a hosted bot's API access/cost are separate deployment questions.

This repository remains the migration entry point. Do not create another repository or archive this one before product acceptance, outstanding work and recovery references have a verified home. Deployment/data migration remains open in [#442](https://github.com/Kotodama-Project/Kotodama-project/issues/442).

Current main contains documentation and development checks, not a runnable bot. Do not deploy it over an existing service. Old source remains at [50ca4d2](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b). See [migration](docs/RETIREMENT.md), [status](STATUS.md) and [remaining work](ROADMAP.md).

The [direct Codex workflow](docs/WORKFLOW.md) remains useful for individual work; it does not replace Discord product acceptance.

[MIT License](LICENSE) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
