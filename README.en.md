# Kotodama (English summary)

**A local-first Company OS that connects conversation to auditable intent, work, results, and learning.**

The Japanese [README.md](README.md) is the canonical entry point. This page is a summary for English readers; the design text in [docs/OVERVIEW.md](docs/OVERVIEW.md) and most documentation are Japanese with English governance terms.

> [!IMPORTANT]
> This repository is an **Incomplete Public Preview**. It publishes the Company Pack schemas, validators, and review chain, runtime and evidence candidates, and a Discord runtime candidate. Public Beta signup, a public Discord invite, and a public Voice Bot are not offered. The public boundary stays `NO_GO_UNPUBLISHED`: a validator or CI PASS never means install, deployment, provider connection, Promotion, Current Truth, or Final Human GO. See [STATUS.md](STATUS.md) and [ROADMAP.md](ROADMAP.md).

## Try it in five minutes

Git and Python 3.12 are enough. The command runs the thirteen-step Company Pack review chain in a temporary workspace with no network, credential, or runtime.

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
python3 -S -B tools/smoke_company_pack_review_chain.py
```

On Windows PowerShell, use `python` instead of `python3`. A success prints one line of JSON with `"status": "PASS"` and `"public_beta": "NO_GO_UNPUBLISHED"`; every value under `claims` is `false`. The [5-minute tour](docs/FIVE-MINUTE-TOUR.md) explains the report and the bounded next choices.

## What is being built

Kotodama detects intent in conversation, voice, issues, and documents, confirms only the requirements that are missing, decomposes the work, keeps results and verification evidence, lets an authority decide adoption, and returns the learning to the company. The parts are the Evidence Chain, Company Packs, a Context Platform, an AI workforce, and a deployment foundation on Cloudflare edge plus the official Cloudflare OS.

The 2026-09-30 [OpenAI alignment direction](docs/OPENAI-ALIGNMENT.md) makes Dots the first candidate for everyday interaction and ongoing work. Kotodama keeps knowledge, permissions, corrections, Tasks, and verification with their existing governed owners. Cloudflare edge and official Cloudflare OS remain candidates for connectivity and dedicated views; live integration and deployment require validation.

The target is the whole loop across organizational/design/Project documents and goals, memory, decomposition, parallel work, independent verification, integration, learning and replanning. Preserve original intent, corrections and inherited constraints; document or worker counts are not completion.

The [owner intent](docs/OWNER-INTENT-COMPANY-AGI.md) makes the Project a durable hub for people, agents, sources, Tasks, decisions, outcomes and learning. The [Project view CLI](docs/PROJECT-HUB-VIEW.md) and [existing local-owner persistence/correction](runtime/discord-template/docs/PROJECTS.md) are on `main`. Persistence preserves original requests and correction history; its operations are disabled by default. Dots/GUI shared operations, Task links, dynamic delegation and live external connections remain [#385](https://github.com/Kotodama-Project/Kotodama-project/issues/385) work.

## Current state

This revision includes OKF Markdown retrieval and bounded context, Task inputs bound to original intent and corrections, independent critic evidence, durable cancellation, one repair of selected leaves, verified two-leaf A-to-B dependency execution, a read-only Project view and bounded local Project persistence/correction. Repair retains the existing Task and budget; terminal checkpoint recovery does not redispatch work.

Explicit `local_executable_fixture` mode lets the knowledge CLI or installed core run local child processes declared by the existing owner. The two-document fixture verifies five calls, including a separate critic process, that retain DocA's result and repair only DocB. Learning-origin semantic verification is reused within one invocation, while every guard checks current execution evidence, owner bindings and the learning decision. This revision also validates the Windows working directory and reduces repeated reads within a freshness check.

[Learning proposal readback](docs/TASK-LEARNING-REUSE.md) uses a validated private copy without creating or repairing the original execution DB/WAL/SHM. Missing or corrupt state and missing required current-schema tables produce typed refusals; verified legacy-writer formats remain readable. Current owner, Source, execution policy, expiry, cancellation and final evidence checks still apply.

The [hierarchy CLI](docs/KNOWLEDGE-HIERARCHY-TRACE.md) follows multiple parents and shared references across Project, optional Phase and Requirement declarations using stable IDs and current Source. Parent constraints and corrections remain in the existing Task input. It reads current owner-bound Tasks, receipt-anchored execution Plans and saved local worker/critic inputs, results and the code retained for each execution. Required organization or architecture references without a resolved current owner, and unobserved learning decisions, leave the context `BLOCKED`.

This revision also includes the [measurement CLI](docs/PERFORMANCE-BENCHMARK.md) and the [published fixed comparison](docs/PERFORMANCE-TASK-ADMISSION-2026-10-13.md) across widths 1/2/4: 72 trials and 1,152 Task result rows. The record preserves historical observations of source `d2822b0`. `qualification=NOT_EVALUATED` and default width 1 remain unchanged; full-pipeline resource measurement, sustained memory growth and production performance acceptance remain #330/#331 work.

[STATUS](STATUS.md#current-source-and-open-integration-work) owns this revision's source capabilities, adoption status, remaining owner connections, performance observations and prioritized Issues. Follow each linked Issue's latest evidence before resuming. Whole eight-layer operation, actual model/user outcomes and continuous production operation remain unaccepted.

## Knowledge, Task and Project CLI entrypoints

Use Python 3.12 from the checkout. Follow the linked guides for dependencies and admitted inputs.

| Purpose | Entrypoint | Guide |
|---|---|---|
| Find small, source-bound knowledge units | `python -B tools/knowledge_base.py query --root . "intent KGI"` | [Knowledge retrieval/context](docs/KNOWLEDGE-BASE.md) |
| Bind goals and corrected Source to an existing Task | `python -B tools/knowledge_base.py task-input --help` | [compile / verify / simulate / execute](docs/KNOWLEDGE-TASK-INPUT.md) |
| Execute a local fixture from admitted input | `python -B tools/knowledge_base.py task-input execute --help` | [Owner, input and explicit mode](docs/KNOWLEDGE-TASK-INPUT.md#知識cliから使う) |
| Use the same bounded execution in installed core | `python -I -m kotodama_core.task_swarm.closed_loop --help` | [Local executor](docs/TASK-LOOP-EXECUTOR.md), [building the package candidate](python/README.md#ビルドと確認) |
| Inspect a Project and existing Task bindings | `python -B tools/project_hub.py --help` | [view / inspect-change](docs/PROJECT-HUB-VIEW.md) |
| Trace current parent constraints, Tasks and saved execution | `python -B tools/hierarchy_trace.py --help` | [Hierarchy and execution trace](docs/KNOWLEDGE-HIERARCHY-TRACE.md) |
| Inspect fixed-fixture measurement options | `python -B tools/performance_benchmark.py --help` | [Measurement CLI and fixed comparison](docs/PERFORMANCE-BENCHMARK.md) |

Execution requires input and workers bound to the existing owner plus `--executor-mode local_executable_fixture`. Learning reuse also requires a current decision. The Python Project CLI reads references and validates proposed corrections. The disabled-by-default local-owner operations handle Project create/read/inspect/correct; persisted Projects still have empty `task_refs`. They do not create, update or dispatch Tasks. These entrypoints do not establish large-corpus performance or acceptance of the complete improvement loop.

You choose how to use the product:

- **Run work**: Company Packs trace Work Orders, verification and Promotion.
- **Delegate bounded work**: [Task swarm research](docs/TASK-SWARM-RUN.md) connects explicit requests to three workers and a separate verifier. It is disabled by default; real model/Discord acceptance remains open.
- **Spend time in a voice channel**: choose conversation or work modes. Casual conversation does not grant new work or authority.

## What this revision includes

| Area | Source in this revision | Candidate (not integrated) | Direction |
|---|---|---|---|
| Company Pack / Evidence Chain | starter with 9 Blocks, 9 Records, 3 MOCs; schemas, validators, review chain, smoke | | Promotion policy per lane |
| Session / conversation ledger | schema, validator and [local ledger export/readback](docs/SESSION-CONVERSATION-LEDGER.md) (synthetic validation) | | real-data ingestion, retention and operation |
| Discord / Voice | `runtime/discord-template` (Node 24, local ASR, continuous Live conversation, bounded Task worker, agent channels that start clear requests immediately; write tasks need Linux with Docker verification; real-microphone continuity not yet accepted) | | 15-minute rotation, Voice-to-Verified-Handoff, GrillU, the rest of the [GPT-Live adoption policy](docs/GPT-LIVE-ADOPTION.md) (#142 to #146) |
| Agent swarm / autonomy | bounded Task execution, Luna Task swarm, swarm and route-binding contracts (#34), migration-ledger schema and read-only verifier (#35; synthetic fixture only), [agent-lifecycle contract](docs/PUBLIC-AGENT-LIFECYCLE-REGISTRY.md) (#36; schema, read-only verifier, synthetic fixture) | real registry and runtime/continuity acceptance | Goal Completion Loop after a human GO |
| Knowledge / Context | canonical OKF Markdown, catalog/graph, bounded retrieval/context, typed goal/Source/frontier inputs and owner-bound learning candidates; explicit local-executor CLI, current evidence checks, learning-origin verification reuse within an invocation, proposal readback without creating or repairing the original DB, and bounded multiple-parent hierarchy and saved-execution trace | owner connections across all eight layers and large-corpus evaluation | Context Gateway and continuous improvement |
| Project | minimal information contract, existing Task read-only view and disabled-by-default local persistence of original requests and correction history in the existing SQLite store | [Dots shared operations #395](https://github.com/Kotodama-Project/Kotodama-project/pull/395), GUI and Task links | configurable collaboration and optimization |
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
