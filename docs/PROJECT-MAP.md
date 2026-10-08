# プロジェクトの地図

Kotodamaは、人とagentが楽しく過ごし、一緒に考え、必要なときだけ仕事を進める一つの製品です。公開本体を統合・説明・導入の最優先の中心とし、[製品方向](PRODUCT-DIRECTION.md)からgoal、main、candidate、unconnected、hypothesisを確認できます。これはREADMEから実装と検証へ進む入口であり、Taskや会社のCurrent Truthを所有する台帳ではありません。

日常の入口と継続作業は[OpenAI Dotsを第一候補](OPENAI-ALIGNMENT.md)とし、[Discord / Luma用plugin](../runtime/discord-template/dots-plugin/README.md)で必要な窓口をつなぎます。[公式Cloudflare OS](CLOUDFLARE-OS-ADOPTION.md)は専用画面の候補です。変更は既存の各governed ownerへ返します。BecomeOneは能力の移植元で、移行後は公開Kotodamaの版・内容digestに固定したconsumerとします。接続・実配備は未確定で、この方針だけでは新しい正本や実行権限は作りません。

## 要件と確認する場所

| 要件 | 実装・文書の入口 | 受入で確かめること |
|---|---|---|
| 普段の相談から仕事を始める | [README](../README.md)、[Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) | カジュアルな単体利用と組織利用が共存し、必要のない基盤を必須にしない |
| 日本語の原文、話者、時刻、訂正を保持する | [Voice](OVERVIEW.md#voice--最初に価値を体感する入口)、[Session / Conversation ledger](SESSION-CONVERSATION-LEDGER.md) | 文字起こし断片を確定した意図とせず、原文と後続訂正へ戻れる |
| 意図を同じ仕事と成果へ結ぶ | [Task / Session契約](SESSION-CONVERSATION-LEDGER.md)、[Review Workflow](REVIEW-WORKFLOW.md)、[Company Pack](STARTER-WALKTHROUGH.md) | Source、Intent、Decision、Work、Verification、Promotionを区別し、選択した一つのTask ownerへ戻す |
| 初回の許可範囲で自律的に進める | [Agent entrypoint](../AGENTS.md)、[Security](../SECURITY.md)、[自動改善ループ](IMPROVEMENT-LOOP.md) | 同じ許可を聞き直さず、期限・取消・対象は再確認する。ログインの本人操作は人が行う |
| 必要な文脈を小さく渡す | [Context](OVERVIEW.md#context-platform--会社の共有記憶)、[Dots plugin](../runtime/discord-template/dots-plugin/README.md)、[通信benchmark](LUNA-TASK-SWARM.md) | 全文・訂正・根拠を落とさず、cursorを終端まで読み、アクセス不可や古い資料を再注入しない |
| 話す・録音する・仕事を止める操作を分ける | [Voice](OVERVIEW.md#voice--最初に価値を体感する入口)、[Discord runtime](DISCORD-RUNTIME.md)（main） | 呼びかけ、長時間・複数人、切断復帰、音質、負荷、背景の仕事の継続を同じ実経路で確かめる |
| 小さな成果を検証して学習へ戻す | [5-minute tour](FIVE-MINUTE-TOUR.md)、[Runtime](../runtime/README.md)、[Business Loop](OVERVIEW.md#ai-business-loop) | テスト件数だけでなく成果の有用性、失敗、rollbackと次の改善を確認する |
| 手元の環境で再現・停止・復旧できる | [Installation lifecycle](INSTALLATION-LIFECYCLE.md)、[Runtime](../runtime/README.md) | 対象profileでinstall、実行、停止、backup/restoreを検証する。構成検査を実稼働としない |
| 稼働中のruntimeと候補のbytesを照合する | [Discord runtimeのsource照合](../runtime/discord-template/docs/OPERATIONS.md#稼働中のソースと候補の照合)、[#157](https://github.com/Kotodama-Project/Kotodama-project/issues/157) | 認証済みinstanceの起動時digestを候補・diskと比べる。許可されたlive切替・rollbackの読み戻しとPB-G4の受入は別途必要 |
| 参加者と事業に価値を返す | [Community / Office](OVERVIEW.md#discord-の中に会社を作る)、[Business Loop](OVERVIEW.md#ai-business-loop) | 参加・相談・通報・復旧の体験と、顧客需要や費用を含む成果を実測する |
| 情報アクセス | [情報の分類と閲覧者](INFORMATION-ACCESS.md)、[Gateway](../runtime/local-review-gateway/README.md) | 情報IDと主体IDでread/reviewを検査し、取消・失効を反映する。分類、custodian、reader、reviewer、公開判断を分離し、未分類とsecretを出さない。local snapshotは身元確認サービスではない |
| 公開と非公開、権利の範囲を守る | [License scope](LICENSE-SCOPE.md)、[STATUS](../STATUS.md)、[ROADMAP](../ROADMAP.md) | Kotodamaが扱える範囲のMITと第三者条件を区別し、private source・認証・実会話を公開候補へ混ぜない |

これは要件の地図です。各項目が運用済みであることは意味しません。このcheckoutで実行できるものは現在のファイルとSTATUS、実稼働は担当環境の証拠で確認します。新しい正式な決定・訂正があれば、その対象行と根拠を更新します。

## 採用済みの土台と残る候補

[共通基盤 #18](https://github.com/Kotodama-Project/Kotodama-project/pull/18)と[必須CIの修復 #73](https://github.com/Kotodama-Project/Kotodama-project/pull/73)が、この地図の前提です。mainへ入った範囲は、MITとその適用範囲、公開repoの基本規則、再現可能なCI、Company PackとSession/Conversationの検証、Cloudflare等の限定candidateです。実運用の一括採用ではありません。

後続作業は、PRの本文だけでなく現在のhead/base、差分、レビュー、必須CIを確認して選びます。古いSHAや承認待ちの記述を、現在の停止条件として使い回しません。

mainには、[#43](https://github.com/Kotodama-Project/Kotodama-project/pull/43)由来の[ローカル確認・訂正Gateway](../runtime/local-review-gateway/README.md)と[既存Taskに束縛したCompany Pack作成](COMPANY-PACK-TASK-EXECUTION.md)、Discordから使う[最小構成](DISCORD-RUNTIME.md)（`runtime/discord-template`）も含まれます。Discordの明示`create_company_pack`は、local ownerの同じTaskへPython生成・隔離検証・成果readbackを接続しています。既定無効でLinux限定、自然会話のanalyzerからは選びません。確認Gateway、組織remote owner、実Discord/Human受入は別の境界です。

| 系統 | 次に確認する候補 | 判断の要点 |
|---|---|---|
| 仕事・文脈の継続 | 情報アクセスは[#203](https://github.com/Kotodama-Project/Kotodama-project/pull/203)を統合。旧#44〜#47は[#30の再配置方針](https://github.com/Kotodama-Project/Kotodama-project/issues/30)へ | 保全tagのコードと契約を参照し、必要機能を最新mainへ小さく再配置する。古いstack、日付付きsnapshot、運用方針の写しをまとめて取り込まない |
| 知識と検索 | [Knowledge base](KNOWLEDGE-BASE.md)、[公開知識](../knowledge/index.md)。#48・#61を再配置、#59はparked | 知識基盤の正本はこの系統。schema適合、producer checks、actor/purposeの判断readinessを分け、出典変更・失効・必須context欠落を成功にしない。内容の独立検証と訂正の実入力束縛は後続 |
| 音声 | [GPT-Liveの採用方針](GPT-LIVE-ADOPTION.md)、[#142](https://github.com/Kotodama-Project/Kotodama-project/issues/142)〜[#146](https://github.com/Kotodama-Project/Kotodama-project/issues/146) | Node runtime（`runtime/discord-template`）に一本化する（2026-09-24 owner判断）。#69・#71の別runtimeは取り込まず、方針文書だけをNodeに合わせて取り込んだ。Nodeに無い考え方は後継のIssueで進める |
| 並列実行 | [Luna Task swarm](LUNA-TASK-SWARM.md)（[#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67)・[#85](https://github.com/Kotodama-Project/Kotodama-project/pull/85)を統合） | 明示slashの調査を同じlocal Taskへつなぐ入口、専用の読取範囲、取消・成果readbackを実装。Linuxの合成E2EとWindowsの実行前拒否を検証。過去版`7df1aea`のlive fixture記録は #159、現行版のlive受入は残件。契約候補[#34](https://github.com/Kotodama-Project/Kotodama-project/pull/34)（agent swarm・route binding）は[このruntimeとの対応表](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md#luna-task-swarm-との対応)を付けて取り込み済み。[移行台帳の契約](PUBLIC-MIGRATION-LEDGER.md)（#35）はschema・read-only verifier・合成fixtureとLunaとの対応表を含む。台帳は未記入で実移行は未検証。[agent lifecycle の契約](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md)（#36）はschema・read-only verifier・合成fixtureの段階。実registryは未作成 |
| 別系統のcontrol-plane | [OpenMaus / Cloudflare OS の統合契約候補](OPENMAUS-CLOUDFLARE-OS-INTEGRATION.md)（[#56](https://github.com/Kotodama-Project/Kotodama-project/pull/56) 由来）、[Git Steward](../runtime/git-steward/README.md)。旧#49と後続Draftはparked | #179のGit Steward調整コアはlocal candidate。[設計文書](GIT-STEWARD-AND-WORK-CELLS.md)と[業務演習](BUSINESS-REHEARSAL.md)で訂正・担当交代・再起動を検査。OpenMaus / Cloudflare OSは五つの既存reviewを処理した契約・schema・read-only validatorと合成fixture。旧OKF registryやauditは取り込まず、#48の知識ownerへつなぐ。UI・provider操作・実配備は未実装 |
| 既存能力の移植 | [Migration Epic #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24)、[出典と権利 #25](https://github.com/Kotodama-Project/Kotodama-project/issues/25) | capabilityごとに出典・第三者条件・consumerを確認する。[A022の公開architecture候補](architecture/README.md)はowner・協調・監督・planの契約を再利用する入口（独立review記録、liveは未検証）。[A019のregistry契約候補](../migration/a019-registry-contracts.manifest.json)は[Task契約](../schemas/task-contract.schema.json)など4 schemasの入口（runtime・Task ownerは未統合） |

PRごとの処分と進み具合は[#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)にあります。名前の系統は[NAMES](NAMES.md)、公開リポジトリの関係は[REPOSITORIES](REPOSITORIES.md)にあります。PR一覧は作業選択のための入口です。件数やリンクの存在で全履歴読了、採用、配備を主張しません。元のPRが別branch向けでも、最終的にどのbytesがmainへ入ったかを確認します。

要件の候補を作る限定経路として、[要件Gadget](../runtime/cloudflare-os-kotodama/README.md)と
[Codex brief bridge](../runtime/codex-task-bridge/README.md)があります。catalog v2の閲覧範囲、
source/policy revisionとoperatorのgrantを確認し、同じ要求への再送でモデルを二重起動しません。
Task ownerを追加せず、実Codex・native core・配備の受入は残ります（#124、元#45）。

[control-plane監査](CONTROL-PLANE-AUDIT.md)は現行知識への参照と公開責任索引を検査します。
[保守planner](CONTROL-PLANE-OPERATIONS.md)はfindingから修正候補を返し、実行や稼働を主張しません。

## 作業を一つ進める

[agent状態のoffline投影](AGENT-STATUS-PROJECTION.md)は、責任索引と任意の観測を
診断用に表示します。既定で文脈を伏せ、稼働や認可を静的snapshotから主張しません。

1. 上のどの要件と利用体験を前進させるか、一文で固定する。
2. 正本、現在の担当、対象commitと作業範囲を確認する。既存Taskを別台帳へ複製しない。
3. 変更部分と未解決点を検証する。同じ入力と有効な証拠を何度も読み直さない。
4. 必須CIと対象に合った技術レビューを確認して統合し、結果を元の仕事へ返す。

Task契約を持つcheckoutでは、そのresolver / records / events / restart checkpointを使います。ない契約をあるものとして扱わず、別のTask正本を先に作りません。

公開Botの提供、配備、会社のCurrent Truth、Public Betaへの移行は、それぞれの対象に合う実行証拠と決定で判断します。コードのmain統合だけでそれらを完了扱いにしません。

### Taskに束縛するswarmの入口

既存Taskからの固定plan・出典付き報告・独立reviewの閉じた形は
[Task swarm run契約](TASK-SWARM-RUN.md)、実行基盤とownerの境界は
[Luna Task swarm](LUNA-TASK-SWARM.md)を参照します（#286）。Discordの明示入口と
同じTaskへの返却は実装済みで、専用ログイン・live利用枠・実モデル/依頼者の受入は残ります。
