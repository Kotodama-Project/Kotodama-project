# Kotodama (English summary)

**A local-first Company OS that connects conversation to auditable intent, work, results, and learning.**

The Japanese [README.md](README.md) is the canonical entry point. This page is a summary for English readers; the design text in [docs/OVERVIEW.md](docs/OVERVIEW.md) and most documentation are Japanese with English governance terms.

> [!IMPORTANT]
> This repository is an **Incomplete Public Preview**. It publishes the Company Pack schemas, validators, and review chain, runtime and evidence candidates, and a Discord runtime candidate. Public Beta signup, a public Discord invite, and a public Voice Bot are not offered. The public boundary stays `NO_GO_UNPUBLISHED`: a validator or CI PASS never means install, deployment, provider connection, Promotion, Current Truth, or Final Human GO. See [STATUS.md](STATUS.md) and [ROADMAP.md](ROADMAP.md).

## What is being built

Kotodama detects intent in conversation, voice, issues, and documents, confirms only the requirements that are missing, decomposes the work, keeps results and verification evidence, lets an authority decide adoption, and returns the learning to the company. The parts are the Evidence Chain, Company Packs, a Context Platform, an AI workforce, and a deployment foundation on Cloudflare edge plus the official Cloudflare OS.

The official Cloudflare OS is the planned shared frontend for knowledge, conversation, Tasks, and agents. Operations return to their existing governed owners; connection details, UI composition, and deployment remain subject to design and validation.

You choose how to use it:

- **Run work**: Company Packs and the review chain trace a request through Work Order, Verification Receipt, and Promotion.
- **Say "OK" and let agents proceed**: within a permission granted once, an agent swarm researches, implements, and verifies on its own and returns to a human only when judgment or authority is missing. This is the design direction; `main` contains bounded Task execution and the [Luna Task swarm](docs/LUNA-TASK-SWARM.md), exercised with an offline fixture (no live model acceptance yet).
- **Spend time in a voice channel**: choose a mode such as relaxing, thinking together, or working only when needed. Small talk is never turned into work or extra permission by itself.

## Try it in five minutes

Git and Python 3.12 are enough. The command runs the thirteen-step Company Pack review chain in a temporary workspace with no network, credential, or runtime.

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
python3 -S -B tools/smoke_company_pack_review_chain.py
```

On Windows PowerShell, use `python` instead of `python3`. A success prints one line of JSON with `"status": "PASS"` and `"public_beta": "NO_GO_UNPUBLISHED"`; every value under `claims` is `false`. The [5-minute tour](docs/FIVE-MINUTE-TOUR.md) explains the report and the bounded next choices.

## What works today

| Area | On `main` | Candidate (open PR) | Direction |
|---|---|---|---|
| Company Pack / Evidence Chain | starter with 9 Blocks, 9 Records, 3 MOCs; schemas, validators, review chain, smoke | | Promotion policy per lane |
| Session / conversation ledger | schema and validator | | runtime ingestion |
| Discord / Voice | `runtime/discord-template` (Node 24, local ASR, continuous Live conversation, bounded Task worker, agent channels that start clear requests immediately; write tasks need Linux with Docker verification; real-microphone continuity not yet accepted) | #69 and #71 (not taken in as separate runtimes; their ideas move into this Node runtime) | 15-minute rotation, Voice-to-Verified-Handoff, GrillU |
| Agent swarm / autonomy | bounded Task execution, Luna Task swarm, swarm and route-binding contracts (#34) | migration-ledger and agent-lifecycle contracts (#35, #36) | Goal Completion Loop after a human GO |
| Knowledge / Context | | OKF v0.2 knowledge bundle (#48, #61, #59, chosen as the canonical line), control plane (#49 line) | Context Gateway, TiDB evaluation |
| Runtime | Compose / Proxmox lifecycle contracts, Cloudflare candidates | | deployment on Cloudflare edge and the official Cloudflare OS |

[STATUS.md](STATUS.md) is the source for the current state. This page is a projection, not a Human Decision or Current Truth.

## Documents

- Current state and gates: [STATUS.md](STATUS.md), [ROADMAP.md](ROADMAP.md), [CHANGELOG.md](CHANGELOG.md), [docs/HISTORY.md](docs/HISTORY.md)
- Direction: [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md), [docs/OWNER-INTENT-COMPANY-AGI.md](docs/OWNER-INTENT-COMPANY-AGI.md), [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md)
- Use: [5-minute tour](docs/FIVE-MINUTE-TOUR.md), [Discord runtime](docs/DISCORD-RUNTIME.md), [Template Guide](docs/TEMPLATE-GUIDE.md), [Validation Guide](docs/VALIDATION.md), [Luna Task swarm](docs/LUNA-TASK-SWARM.md)
- Full design text: [docs/OVERVIEW.md](docs/OVERVIEW.md)

## Participate

[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [SUPPORT.md](SUPPORT.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) describe how to contribute, report vulnerabilities, ask for help, and behave. Questions and discussion go to [GitHub Discussions](https://github.com/Kotodama-Project/Kotodama-project/discussions). Agents start from [AGENTS.md](AGENTS.md).

## License

Code that Kotodama can license is under the [MIT License](LICENSE). Third-party conditions and the provenance of migrated material are described in [docs/LICENSE-SCOPE.md](docs/LICENSE-SCOPE.md).
