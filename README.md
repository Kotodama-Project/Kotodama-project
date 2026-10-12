# Kotodama

**会話を、監査できる意図・仕事・成果・学習へつなぐ Local-first Company OS。**

Kotodama is a local-first Company OS that turns conversation into auditable intent, work, results, and learning. English summary: [README.en.md](README.en.md).

> [!IMPORTANT]
> このリポジトリは **Incomplete Public Preview** です。公開しているのは Company Pack の schema・validator・review chain、runtime と evidence の候補、Discord runtime の候補です。Public Beta の受付、Discord 招待、公開 Voice Bot は提供していません。公開面の既定は `NO_GO_UNPUBLISHED` で、validator や CI の PASS は install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。最新の境界は [STATUS.md](STATUS.md)、未完了の gate は [ROADMAP.md](ROADMAP.md) にあります。

## 何を作っているか

会話・音声・Issue・文書から意図を検知し、足りない要件だけを確認して仕事へ分解し、成果と検証証拠を残して採用を判断し、会社の知識へ戻す。この鎖を短絡しないまま速く回すための部品を、Evidence Chain、Company Pack、Context Platform、AI Workforce、そして Cloudflare edge と公式 Cloudflare OS を基盤として作っています。

組織・設計・Project の文書階層と、目標・記憶・分解・並行実行・独立検証・統合・学習・再計画をつなぐ仕組み全体が対象です。各仕事へ原意・訂正・上位制約を保ち、同じ課題を繰り返さず、品質・時間・メモリ・費用・人の手間を改善します。文書や固定 worker の数を、全体の完成とは扱いません。

2026-10-12 の [Project 中心の agent ハブ方針（#385）](https://github.com/Kotodama-Project/Kotodama-project/issues/385) では、Project を目的・要件・人・agent・資料・Task・判断・成果・学習のハブにし、GUI・自然言語・CLI を既存 owner へつなぐ方向を記録しています。必要な役割を親子・横で協働させ、版付き設定で変更する設計です。[意図・設計の PR #386](https://github.com/Kotodama-Project/Kotodama-project/pull/386) は未統合で、Project service、動的 agent 生成、実外部接続、最適化 engine は未実装です。API/MCP 等のバックエンド連携候補も、main の接続済み機能とは区別します。

2026-09-30の方針として、[OpenAI Dotsを日常の入口と継続作業の第一候補](docs/OPENAI-ALIGNMENT.md)にします。Kotodamaは会社の知識・権限・訂正・Task・検証証拠を既存の各正本へ返します。Cloudflare edgeと公式Cloudflare OSは接続・専用画面の候補として維持し、実接続と配備は検証して決めます。

同じ製品の中で、利用の場面を選べます。

- **仕事を進める**: Company Pack と review chain で、依頼を Work Order、Verification Receipt、Promotion まで辿る。
- **「OK」の後は agent に任せる**: 明示した調査依頼を、同じTaskの3workerと独立reviewへつなぐ [Task swarm](docs/TASK-SWARM-RUN.md) を備えます。既定無効で、Linuxの専用実行領域を使います。合成の一連動作を検証済みで、実モデル・実Discordの受入は残っています。
- **Voice channel で過ごす**: 楽しく過ごす、一緒に考える、必要なときだけ仕事を進める、のモードを選ぶ。雑談を勝手に仕事や追加の権限へ変えません。

設計の全文は [docs/OVERVIEW.md](docs/OVERVIEW.md)、方向と現在地の対応は [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md) と [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md) にあります。

## 現在地と再開する仕事（2026-10-12）

確認した公開 main は [`c63e632`](https://github.com/Kotodama-Project/Kotodama-project/commit/c63e63291cd561c0ed2764b311935bd4f90b14a3) です。これは source の確認点で、実利用・配備の受入ではありません。

| 区分 | 確認できるもの | 残る受入・次の作業 |
|---|---|---|
| main：知識と目的入力 | canonical OKF Markdown、50 Concept の catalog/graph、検索・限定 context、型付き Goal/KGI/INIT と原意・訂正・現在 Source を既存 Task 入力へ束縛する CLI | 大規模 corpus の検索品質・cold/warm latency・RSS は [#326](https://github.com/Kotodama-Project/Kotodama-project/issues/326) / [#349](https://github.com/Kotodama-Project/Kotodama-project/issues/349)。全体の目的入力受入は [#327](https://github.com/Kotodama-Project/Kotodama-project/issues/327) |
| main：有限の実行と取消 | 既存 Task owner、全担当 critic 証拠、checkpoint 後の再開・再読、明示取消の永続保存。[PR #383](https://github.com/Kotodama-Project/Kotodama-project/pull/383) を採用し [#363](https://github.com/Kotodama-Project/Kotodama-project/issues/363) は完了 | 取消前の in-flight 強制停止、実モデル・利用者受入、全8層の完成を意味しない |
| main：通常 Task の並行受付 | [PR #346](https://github.com/Kotodama-Project/Kotodama-project/pull/346) の有限 queue、actor/room の独占回避、writer 排他、実処理 settle までの slot 保持。既定幅1 | 幅1/2/4の同一負荷比較、全呼出 RSS/CPU、費用の受入は [#330](https://github.com/Kotodama-Project/Kotodama-project/issues/330)。全試験の並列化評価は [#331](https://github.com/Kotodama-Project/Kotodama-project/issues/331)。未計測の高速化や最適な既定値を主張しない |
| 公開 PR：必要な leaf の部分修復 | [PR #384](https://github.com/Kotodama-Project/Kotodama-project/pull/384) / [#365](https://github.com/Kotodama-Project/Kotodama-project/issues/365)。長い ID と検査時の DB 作成を修正した公開 head `0381f26` | Windows CI で file stat の API 差による拒否を確認。追加修正候補を公開・再検証してから採用する。main 未統合 |
| preview：後続の固定候補 | [候補ブランチ](https://github.com/Kotodama-Project/Kotodama-project/tree/preview/closed-loop-candidates-20261012) に階層 reader/producer、A→B 依存契約、通常 task-input inspect、資料入力、dormant executor、任意 test runner を掲載 | [#366](https://github.com/Kotodama-Project/Kotodama-project/issues/366) / [#372](https://github.com/Kotodama-Project/Kotodama-project/issues/372) / [#375](https://github.com/Kotodama-Project/Kotodama-project/issues/375)。snapshot は main 採用ではなく、PR #384 の後続修正や B1/C は含まない |

再開順は次です。詳細な受入・担当・証拠はリンク先の既存 Issue と最新 PR に戻します。

1. **#365 / PR #384**：Windows の file ID 照合修正を公開し、訂正 head の独立照合・必須 CI・取り込み後検証から完了を確認する。
2. **#366**：A→B の検証済み release、B 限定修復、取消・再開を採用する。長い B ID の scheduler 延長と claim 読戻しに残る旧 ID 形式を修正し、Windows 修正と合成する。
3. **#375 / #327 / #347**：実 process executor の最終 owner/actor 検証で残る変更競合を直し、既存の通常・learning 検証を保った製品 CLI を接続する。hierarchy の新実行 mode、実 stdin と全 reader を確認する。まだ main の実行入口ではない。
4. **#330 / #331 / #326 / #349**：固定入力・環境で速度、RSS、読取量、品質、再実行・費用を比較する。既存コードを重複実装せず、改善なし・失敗・未計測も残す。
5. **#385 と #328 / #350**：既存 owner 上の Project 統合 view・共通操作と継続改善へつなぐ。実モデル・利用者・本番の受入を local/synthetic の結果と分ける。

各候補は追加費用・provider 接続・配備・公開設定を有効化しません。README は案内であり、新しい Task 台帳や採用判断の正本ではありません。

## 5 分で試す

Git と Python 3.12 だけで、Company Pack の review chain（13 steps）を一時 workspace で完走させます。外部接続、credential、runtime は不要です。

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
python3 -S -B tools/smoke_company_pack_review_chain.py
```

Windows の PowerShell では `python3` の代わりに `python` を使います。成功すると `"status": "PASS"` と `"public_beta": "NO_GO_UNPUBLISHED"` を含む一行 JSON が返り、`claims` はすべて `false` です。読み方と次の一歩は [5-minute tour](docs/FIVE-MINUTE-TOUR.md) にあります。

## 使い方を選ぶ

| やりたいこと | 今日 `main` でできること | 入口 |
|---|---|---|
| Company Pack を自分の会社の候補として編集し検査する | initializer、customization checker、validator、Catalog、Review Bundle（read-only / candidate-only） | [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)、[CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) |
| Discord / Voice で使う | `runtime/discord-template`。Node 24、Discord Bot、モデル接続が前提。local ASR と Live 会話、限定 Task worker、エージェント用チャンネルからの即時着手。書込みの仕事は Linux と Docker での検証が必要。実マイクの連続応答、2 人 30 分の会話、別設定での再現は未受入 | [Discord runtime](docs/DISCORD-RUNTIME.md) |
| 既存 Task に結び付けて Company Pack を実生成し、確認・訂正する | `tools/run_company_pack_task.py` と local review gateway | [Task-bound execution](docs/COMPANY-PACK-TASK-EXECUTION.md)、[Gateway](runtime/local-review-gateway/README.md) |
| 会社の runtime を配備する | Compose minimum / Proxmox segmented の lifecycle contract と validator（live receipt なし）。Cloudflare edge と公式 Cloudflare OS の候補（未 upload、未 deploy） | [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)、[Cloudflare OS](docs/CLOUDFLARE-OS-ADOPTION.md) |
| agent swarm に調査を任せる | 明示slashから同じTaskの3worker・別verifier・成果readbackへ接続。既定無効、Linux限定。移行台帳とlifecycle registryの実運用は別の未完事項 | [Task swarm run](docs/TASK-SWARM-RUN.md)、[実行基盤](docs/LUNA-TASK-SWARM.md)、[swarm契約](docs/AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md) |
| 知識基盤と目的入力を使う | canonical OKF Markdown、catalog/graph、出典・鮮度の検査、字句検索、限定context、型付き目的と原意・訂正を既存Taskへ束縛する compile/verify/simulate。内容の独立検証・実モデル品質・大規模性能は別の受入 | [Knowledge base](docs/KNOWLEDGE-BASE.md)、[Task input](docs/KNOWLEDGE-TASK-INPUT.md)、[公開知識の入口](knowledge/index.md) |

## 今 `main` にあるもの、候補、方向

| 面 | `main` | 候補（未統合） | 方向 |
|---|---|---|---|
| Company Pack / Evidence Chain | 9 Blocks、9 Records、3 MOCs の starter、schema と validator、review chain、smoke | | lane ごとの Promotion policy |
| Session / conversation ledger | schema と validator | | runtime への取込 |
| Discord / Voice | `runtime/discord-template` | | 15 分 rotation、Voice-to-Verified-Handoff、GrillU、[GPT-Live の採用方針](docs/GPT-LIVE-ADOPTION.md)の残り（#142〜#146） |
| Agent swarm / 自律実行 | 限定 Task 実行、Luna Task swarm、agent swarm・route binding の契約（#34）、移行台帳の契約（#35）、agent lifecycle の契約（#36） | 実 registry と runtime/continuity 受入 | 「OK」後の Goal Completion Loop、reversible delegation |
| 知識・Context | canonical OKF bundle、read-only検索/context、型付きTask目的・Source/frontier・learning候補の既存owner接続 | 階層統合、実executor入力・製品CLI、大規模検索評価 | Context Gateway、継続改善 |
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
