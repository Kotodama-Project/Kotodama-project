# Kotodama

**会話を、監査できる意図・仕事・成果・学習へつなぐ Local-first Company OS。**

Kotodama is a local-first Company OS that turns conversation into auditable intent, work, results, and learning. English summary: [README.en.md](README.en.md).

> [!IMPORTANT]
> このリポジトリは **Incomplete Public Preview** です。公開しているのは Company Pack の schema・validator・review chain、runtime と evidence の候補、Discord runtime の候補です。Public Beta の受付、Discord 招待、公開 Voice Bot は提供していません。公開面の既定は `NO_GO_UNPUBLISHED` で、validator や CI の PASS は install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。最新の境界は [STATUS.md](STATUS.md)、未完了の gate は [ROADMAP.md](ROADMAP.md) にあります。

## 5 分で試す

Git と Python 3.12 だけで、Company Pack の review chain（13 steps）を一時 workspace で完走させます。外部接続、credential、runtime は不要です。

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
python3 -S -B tools/smoke_company_pack_review_chain.py
```

Windows の PowerShell では `python3` の代わりに `python` を使います。成功すると `"status": "PASS"` と `"public_beta": "NO_GO_UNPUBLISHED"` を含む一行 JSON が返り、`claims` はすべて `false` です。読み方と次の一歩は [5-minute tour](docs/FIVE-MINUTE-TOUR.md) にあります。

## 何を作っているか

会話・音声・Issue・文書から意図を検知し、足りない要件だけを確認して仕事へ分解し、成果と検証証拠を残して採用を判断し、会社の知識へ戻す。この鎖を短絡しないまま速く回すための部品を、Evidence Chain、Company Pack、Context Platform、AI Workforce、そして Cloudflare edge と公式 Cloudflare OS を基盤として作っています。

組織・設計・Project の文書階層と、目標・記憶・分解・並行実行・独立検証・統合・学習・再計画をつなぐ仕組み全体が対象です。各仕事へ原意・訂正・上位制約を保ち、同じ課題を繰り返さず、品質・時間・メモリ・費用・人の手間を改善します。文書や固定 worker の数を、全体の完成とは扱いません。

[Owner intent](docs/OWNER-INTENT-COMPANY-AGI.md) に、Project を目的・要件・人・agent・資料・Task・判断・成果・学習のハブにする方向を保持しています。必要な役割が親子・横で協働し、GUI・自然言語・CLI から同じ仕事を扱う設計です。[Project 参照 CLI](docs/PROJECT-HUB-VIEW.md) と、原依頼・訂正履歴を保持する[既存 local owner の保存・訂正](runtime/discord-template/docs/PROJECTS.md)は `main` にあります。保存操作は既定無効です。Dots・GUI との共通操作、Task の関連付け、動的割当・実外部接続は [#385](https://github.com/Kotodama-Project/Kotodama-project/issues/385) で進めています。

2026-09-30の方針として、[OpenAI Dotsを日常の入口と継続作業の第一候補](docs/OPENAI-ALIGNMENT.md)にします。Kotodamaは会社の知識・権限・訂正・Task・検証証拠を既存の各正本へ返します。Cloudflare edgeと公式Cloudflare OSは接続・専用画面の候補として維持し、実接続と配備は検証して決めます。

同じ製品の中で、利用の場面を選べます。

- **仕事を進める**: Company Pack と review chain で、依頼を Work Order、Verification Receipt、Promotion まで辿る。
- **「OK」の後は agent に任せる**: 明示した調査依頼を、同じTaskの3workerと独立reviewへつなぐ [Task swarm](docs/TASK-SWARM-RUN.md) を備えます。既定無効で、Linuxの専用実行領域を使います。合成の一連動作を検証済みで、実モデル・実Discordの受入は残っています。
- **Voice channel で過ごす**: 楽しく過ごす、一緒に考える、必要なときだけ仕事を進める、のモードを選ぶ。雑談を勝手に仕事や追加の権限へ変えません。

設計の全文は [docs/OVERVIEW.md](docs/OVERVIEW.md)、方向と現在地の対応は [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md) と [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md) にあります。

## 現在地

この版には、OKF Markdown の知識検索・限定 context、原意と訂正を束縛する Task 入力、独立 critic、永続取消、必要な leaf だけの一回修復、検証済み A から B への二葉の依存実行、Project の read-only view と限定 local 保存・訂正があります。修復は同じ Task・予算を保ち、終端 checkpoint 後の復旧で仕事を再実行しません。

`local_executable_fixture` を明示すると、知識 CLI またはインストールした core から、既存 owner が指定したローカル子プロセスを実行できます。二資料の fixture では、別プロセスの独立 critic を含む5回の呼出しで DocA の結果を保持し、DocB だけを修復する経路を検証しています。学習元の意味検証は一回の呼出し内で再利用し、各検査では現在の実行証拠・owner・学習判断を確認します。 Windows の作業ディレクトリ検証と、現在性を保った検査内の重複読取削減も含みます。

この版の source 能力、採用状況、階層 reader などの残件、性能測定と優先 Issue は [STATUS の現在地](STATUS.md#current-source-and-open-integration-work) に集約しています。次の担当はそこから各 Issue の最新 head・証拠・残る受入を確認してください。全8階層、実モデル・利用者成果、常駐運用は引き続き受入が必要です。

## 知識・目的・Project を CLI で確認する

checkout の Python 3.12 から使います。検索は現在の小さな Markdown 単位で出典・鮮度を返します。Task と Project の入力・依存準備はリンク先の手順を参照してください。

| 目的 | 入口 | 契約・手順 |
|---|---|---|
| 知識を探す | `python -B tools/knowledge_base.py query --root . "意図 KGI"` | [検索と限定 context](docs/KNOWLEDGE-BASE.md) |
| 目的と Source を既存 Task に束縛する | `python -B tools/knowledge_base.py task-input --help` | [compile / verify / simulate / execute](docs/KNOWLEDGE-TASK-INPUT.md) |
| 受入済み入力から local fixture を実行する | `python -B tools/knowledge_base.py task-input execute --help` | [owner・入力・明示 mode の準備](docs/KNOWLEDGE-TASK-INPUT.md#知識cliから使う) |
| インストールした core で同じ有限実行を使う | `python -I -m kotodama_core.task_swarm.closed_loop --help` | [local executor](docs/TASK-LOOP-EXECUTOR.md)、[配布候補のビルド](python/README.md#ビルドと確認) |
| Project と既存 Task の対応を読む | `python -B tools/project_hub.py --help` | [view / inspect-change](docs/PROJECT-HUB-VIEW.md) |

実行には既存 owner に束縛した入力・worker と `--executor-mode local_executable_fixture` が必要です。学習の再利用には現在の採否判断も必要です。Python の Project CLI は参照と訂正候補の検査までです。既定無効の local owner 共通操作は Project の create/read/inspect/correct を扱い、保存した Project の `task_refs` は空です。Task 作成・更新・dispatch は行いません。検索品質・大規模性能や自律改善の全体受入は、これらの入口の存在だけでは成立しません。

## 使い方を選ぶ

| やりたいこと | この版で使える範囲 | 入口 |
|---|---|---|
| Company Pack を自分の会社の候補として編集し検査する | initializer、customization checker、validator、Catalog、Review Bundle（read-only / candidate-only） | [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)、[CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) |
| Discord / Voice で使う | `runtime/discord-template`。Node 24、Discord Bot、モデル接続が前提。local ASR と Live 会話、限定 Task worker、エージェント用チャンネルからの即時着手。書込みの仕事は Linux と Docker での検証が必要。実マイクの連続応答、2 人 30 分の会話、別設定での再現は未受入 | [Discord runtime](docs/DISCORD-RUNTIME.md) |
| 既存 Task に結び付けて Company Pack を実生成し、確認・訂正する | `tools/run_company_pack_task.py` と local review gateway | [Task-bound execution](docs/COMPANY-PACK-TASK-EXECUTION.md)、[Gateway](runtime/local-review-gateway/README.md) |
| 会社の runtime を配備する | Compose minimum / Proxmox segmented の lifecycle contract と validator（live receipt なし）。Cloudflare edge と公式 Cloudflare OS の候補（未 upload、未 deploy） | [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)、[Cloudflare OS](docs/CLOUDFLARE-OS-ADOPTION.md) |
| agent swarm に調査を任せる | 明示slashから同じTaskの3worker・別verifier・成果readbackへ接続。既定無効、Linux限定。移行台帳とlifecycle registryの実運用は別の未完事項 | [Task swarm run](docs/TASK-SWARM-RUN.md)、[実行基盤](docs/LUNA-TASK-SWARM.md)、[swarm契約](docs/AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md) |
| 知識基盤と目的入力を使う | canonical OKF Markdown、catalog/graph、出典・鮮度の検査、字句検索、限定context、型付き目的と原意・訂正を既存Taskへ束縛する compile/verify/simulate/execute。明示した local fixture の子プロセス・独立 critic・部分修復と学習を同じTaskへ接続。内容の独立検証・実モデル品質・大規模性能は別の受入 | [Knowledge base](docs/KNOWLEDGE-BASE.md)、[Task input](docs/KNOWLEDGE-TASK-INPUT.md)、[local executor](docs/TASK-LOOP-EXECUTOR.md)、[公開知識の入口](knowledge/index.md) |
| Project と既存 Task を確認する | Project 情報契約、既存 owner に束縛した Task 参照 view、訂正候補と影響の検査。local owner の保存・訂正は既定無効の共通操作から使う | [Project view](docs/PROJECT-HUB-VIEW.md)、[保存・訂正](runtime/discord-template/docs/PROJECTS.md) |

## この版に含むもの、候補、方向

| 面 | この版の source | 候補（未統合） | 方向 |
|---|---|---|---|
| Company Pack / Evidence Chain | 9 Blocks、9 Records、3 MOCs の starter、schema と validator、review chain、smoke | | lane ごとの Promotion policy |
| Session / conversation ledger | schema・validator、[local ledger-export/readback](docs/SESSION-CONVERSATION-LEDGER.md)（合成検証） | | 実データの取込・保持・運用 |
| Discord / Voice | `runtime/discord-template` | | 15 分 rotation、Voice-to-Verified-Handoff、GrillU、[GPT-Live の採用方針](docs/GPT-LIVE-ADOPTION.md)の残り（#142〜#146） |
| Agent swarm / 自律実行 | 限定 Task 実行、Luna Task swarm、agent swarm・route binding の契約（#34）、移行台帳の契約（#35）、agent lifecycle の契約（#36） | 実 registry と runtime/continuity 受入 | 「OK」後の Goal Completion Loop、reversible delegation |
| 知識・Context | canonical OKF bundle、read-only検索/context、型付きTask目的・Source/frontier・learning候補の既存owner接続、明示 local executor の CLI と現在証拠の検査、呼出し内の学習元検証再利用 | 階層統合、欠落DBの副作用なし再読、大規模検索評価 | Context Gateway、継続改善 |
| Project | 最小情報契約、既存 Task の read-only view、原依頼と訂正履歴を既存 SQLite に保持する local 保存（既定無効） | [Dots 共通操作 #395](https://github.com/Kotodama-Project/Kotodama-project/pull/395)、GUI・Task の関連付け | 目的に応じた協働・最適化 |
| Runtime | Compose / Proxmox contract、Cloudflare candidate | | Cloudflare edge と公式 Cloudflare OS を基盤にした配備 |
| 組織・事業 | | | Resident Clone、Agent Foundry、AI Business Loop |

状態の正本は [STATUS.md](STATUS.md) です。README は projection であり、Human Decision や Current Truth ではありません。

## 仕組みの骨格

```text
Source Evidence → Intent Candidate → Human Decision → Work Order → Capability Grant
→ Change Candidate → Verification Receipt → Promotion Decision → Current Truth
```

各段階がそれだけでは何を作らないか、Company Pack の Blocks / Records / MOCs との対応、Voice と GrillU の設計、Local-first architecture の表は [docs/OVERVIEW.md](docs/OVERVIEW.md) に全文があります。用語は [docs/OVERVIEW.md#用語](docs/OVERVIEW.md#用語) を参照してください。

## 文書の地図

- 現在地と gate: [STATUS.md](STATUS.md)、[ROADMAP.md](ROADMAP.md)、[CHANGELOG.md](CHANGELOG.md)（版ごとの変更）、[docs/HISTORY.md](docs/HISTORY.md)（過去の revision 履歴）
- 方向: [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md)、[docs/OWNER-INTENT-COMPANY-AGI.md](docs/OWNER-INTENT-COMPANY-AGI.md)、[docs/PROJECT-MAP.md](docs/PROJECT-MAP.md)
- 使う: [5-minute tour](docs/FIVE-MINUTE-TOUR.md)、[Discord runtime](docs/DISCORD-RUNTIME.md)、[Template Guide](docs/TEMPLATE-GUIDE.md)、[Validation Guide](docs/VALIDATION.md)、[Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)、[Luna Task swarm](docs/LUNA-TASK-SWARM.md)、[Runtime candidates](runtime/README.md)
- 設計の全文: [docs/OVERVIEW.md](docs/OVERVIEW.md)

## 参加する

Issue と Pull Request の手順は [CONTRIBUTING.md](CONTRIBUTING.md)、相談は [GitHub Discussions](https://github.com/Kotodama-Project/Kotodama-project/discussions)、脆弱性は [SECURITY.md](SECURITY.md)、それ以外の問い合わせは [SUPPORT.md](SUPPORT.md)、行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) にあります。エージェントの開始手順は [AGENTS.md](AGENTS.md) です。

## ライセンス

Kotodama がライセンスを設定できるコードは [MIT License](LICENSE)（SPDX identifier: `MIT`）で提供します。第三者の条件と移植部分の出典は [docs/LICENSE-SCOPE.md](docs/LICENSE-SCOPE.md) を参照してください。
