# プロジェクトの地図

Kotodamaは、人とagentが楽しく過ごし、一緒に考え、必要なときだけ仕事を進める一つの製品です。公開本体を統合・説明・導入の最優先の中心とし、[製品方向](PRODUCT-DIRECTION.md)からgoal、main、candidate、unconnected、hypothesisを確認できます。これはREADMEから実装と検証へ進む入口であり、Taskや会社のCurrent Truthを所有する台帳ではありません。

共通フロントは[公式 Cloudflare OS](CLOUDFLARE-OS-ADOPTION.md)を使う設計です。知識・会話・Task・agent の表示と操作をまとめ、変更は既存の各 governed owner へ返します。BecomeOne は能力の移植元で、移行後は公開 Kotodama の版・内容 digest に固定した consumer とします。接続・画面構成・実配備は未確定で、この方針だけでは新しい正本や実行権限は作りません。

## 要件と確認する場所

| 要件 | 実装・文書の入口 | 受入で確かめること |
|---|---|---|
| 普段の相談から仕事を始める | [README](../README.md)、[Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) | カジュアルな単体利用と組織利用が共存し、必要のない基盤を必須にしない |
| 日本語の原文、話者、時刻、訂正を保持する | [Voice](OVERVIEW.md#voice--最初に価値を体感する入口)、[Session / Conversation ledger](SESSION-CONVERSATION-LEDGER.md) | 文字起こし断片を確定した意図とせず、原文と後続訂正へ戻れる |
| 意図を同じ仕事と成果へ結ぶ | [Task / Session契約](SESSION-CONVERSATION-LEDGER.md)、[Review Workflow](REVIEW-WORKFLOW.md)、[Company Pack](STARTER-WALKTHROUGH.md) | Source、Intent、Decision、Work、Verification、Promotionを区別し、選択した一つのTask ownerへ戻す |
| 初回の許可範囲で自律的に進める | [Agent entrypoint](../AGENTS.md)、[Security](../SECURITY.md)、[自動改善ループ](IMPROVEMENT-LOOP.md) | 同じ許可を聞き直さず、期限・取消・対象は再確認する。ログインの本人操作は人が行う |
| 必要な文脈を小さく渡す | [Context](OVERVIEW.md#context-platform--会社の共有記憶)、[Session ledger](SESSION-CONVERSATION-LEDGER.md) | 出典・訂正・現在の担当を落とさず、アクセス不可や古い資料を再注入しない |
| 話す・録音する・仕事を止める操作を分ける | [Voice](OVERVIEW.md#voice--最初に価値を体感する入口)、[Discord runtime](DISCORD-RUNTIME.md)（main） | 呼びかけ、長時間・複数人、切断復帰、音質、負荷、背景の仕事の継続を同じ実経路で確かめる |
| 小さな成果を検証して学習へ戻す | [5-minute tour](FIVE-MINUTE-TOUR.md)、[Runtime](../runtime/README.md)、[Business Loop](OVERVIEW.md#ai-business-loop) | テスト件数だけでなく成果の有用性、失敗、rollbackと次の改善を確認する |
| 手元の環境で再現・停止・復旧できる | [Installation lifecycle](INSTALLATION-LIFECYCLE.md)、[Runtime](../runtime/README.md) | 対象profileでinstall、実行、停止、backup/restoreを検証する。構成検査を実稼働としない |
| 参加者と事業に価値を返す | [Community / Office](OVERVIEW.md#discord-の中に会社を作る)、[Business Loop](OVERVIEW.md#ai-business-loop) | 参加・相談・通報・復旧の体験と、顧客需要や費用を含む成果を実測する |
| 公開と非公開、権利の範囲を守る | [License scope](LICENSE-SCOPE.md)、[STATUS](../STATUS.md)、[ROADMAP](../ROADMAP.md) | Kotodamaが扱える範囲のMITと第三者条件を区別し、private source・認証・実会話を公開候補へ混ぜない |

これは要件の地図です。各項目が運用済みであることは意味しません。このcheckoutで実行できるものは現在のファイルとSTATUS、実稼働は担当環境の証拠で確認します。新しい正式な決定・訂正があれば、その対象行と根拠を更新します。

## 採用済みの土台と残る候補

[共通基盤 #18](https://github.com/Kotodama-Project/Kotodama-project/pull/18)と[必須CIの修復 #73](https://github.com/Kotodama-Project/Kotodama-project/pull/73)が、この地図の前提です。mainへ入った範囲は、MITとその適用範囲、公開repoの基本規則、再現可能なCI、Company PackとSession/Conversationの検証、Cloudflare等の限定candidateです。実運用の一括採用ではありません。

後続作業は、PRの本文だけでなく現在のhead/base、差分、レビュー、必須CIを確認して選びます。古いSHAや承認待ちの記述を、現在の停止条件として使い回しません。

mainには、[#43](https://github.com/Kotodama-Project/Kotodama-project/pull/43)由来の[ローカル確認・訂正Gateway](../runtime/local-review-gateway/README.md)と[既存Taskに束縛したCompany Pack作成](COMPANY-PACK-TASK-EXECUTION.md)、Discordから使う[最小構成](DISCORD-RUNTIME.md)（`runtime/discord-template`）も含まれます。三つは限定された別の実行経路であり、会話からTaskを自動作成・実行するconnectorはまだ接続されていません。

| 系統 | 次に確認する候補 | 判断の要点 |
|---|---|---|
| 仕事・文脈の継続 | [#44](https://github.com/Kotodama-Project/Kotodama-project/pull/44) → [#45](https://github.com/Kotodama-Project/Kotodama-project/pull/45) → [#46](https://github.com/Kotodama-Project/Kotodama-project/pull/46) → [#47](https://github.com/Kotodama-Project/Kotodama-project/pull/47) | 前提順にコードと契約だけをmainへ取り込む。日付付きのsnapshotと運用方針の写しは入れない |
| 知識と検索 | [#48](https://github.com/Kotodama-Project/Kotodama-project/pull/48)、[#61](https://github.com/Kotodama-Project/Kotodama-project/pull/61)、[#59](https://github.com/Kotodama-Project/Kotodama-project/pull/59) | 知識基盤の正本はこの系統（2026-09-24 owner判断）。schema適合と、判断に使える根拠・鮮度を分ける |
| 音声 | [#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69)、[#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) | Node runtime（`runtime/discord-template`）に一本化する（2026-09-24 owner判断）。別runtimeは取り込まず、方針文書とNodeに無い考え方を移す |
| 並列実行 | [Luna Task swarm](LUNA-TASK-SWARM.md)（[#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67)・[#85](https://github.com/Kotodama-Project/Kotodama-project/pull/85)を統合） | Linux・Windowsの必須CIと独立reviewを通したlocal fixtureの段階。実Codex/Lunaのlive受入は残件。契約候補#34〜#36はこのruntimeとの対応表を付けて取り込む |
| 別系統のcontrol-plane | [#49](https://github.com/Kotodama-Project/Kotodama-project/pull/49)と後続stack | 競合するOKFの表現を外し、#48の知識bundleにつないで取り込む。#57・#58のGit Stewardの調整コアは[runtime/git-steward](../runtime/git-steward/README.md)としてmainにある（candidate-only）。設計文書と業務演習は[#132](https://github.com/Kotodama-Project/Kotodama-project/issues/132)の後続 |
| 既存能力の移植 | [Migration Epic #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24)、[出典と権利 #25](https://github.com/Kotodama-Project/Kotodama-project/issues/25) | capabilityごとに出典・第三者条件・consumerを確認する。[A022の公開architecture候補](architecture/README.md)はowner・協調・監督・planの契約を再利用する入口（独立review記録、liveは未検証）。[A019のregistry契約候補](../migration/a019-registry-contracts.manifest.json)は[Task契約](../schemas/task-contract.schema.json)など4 schemasの入口（runtime・Task ownerは未統合） |

PRごとの処分と進み具合は[#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)にあります。名前の系統は[NAMES](NAMES.md)、公開リポジトリの関係は[REPOSITORIES](REPOSITORIES.md)にあります。PR一覧は作業選択のための入口です。件数やリンクの存在で全履歴読了、採用、配備を主張しません。元のPRが別branch向けでも、最終的にどのbytesがmainへ入ったかを確認します。

## 作業を一つ進める

1. 上のどの要件と利用体験を前進させるか、一文で固定する。
2. 正本、現在の担当、対象commitと作業範囲を確認する。既存Taskを別台帳へ複製しない。
3. 変更部分と未解決点を検証する。同じ入力と有効な証拠を何度も読み直さない。
4. 必須CIと対象に合った技術レビューを確認して統合し、結果を元の仕事へ返す。

Task契約を持つcheckoutでは、そのresolver / records / events / restart checkpointを使います。ない契約をあるものとして扱わず、別のTask正本を先に作りません。

公開Botの提供、配備、会社のCurrent Truth、Public Betaへの移行は、それぞれの対象に合う実行証拠と決定で判断します。コードのmain統合だけでそれらを完了扱いにしません。
