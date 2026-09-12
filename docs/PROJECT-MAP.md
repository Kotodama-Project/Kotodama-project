# プロジェクトの地図

Kotodamaの目的は、会話から意図・仕事・成果・学習をつなぎ、人とAIが同じ目的・文脈・権限を共有して働けることです。これはREADMEから実装と検証へ進む入口であり、Taskや会社のCurrent Truthを所有する台帳ではありません。

## 要件と確認する場所

| 要件 | 実装・文書の入口 | 受入で確かめること |
|---|---|---|
| 普段の相談から仕事を始める | [README](../README.md)、[Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) | カジュアルな単体利用と組織利用が共存し、必要のない基盤を必須にしない |
| 日本語の原文、話者、時刻、訂正を保持する | [Voice](../README.md#voice--最初に価値を体感する入口)、[Session / Conversation ledger](SESSION-CONVERSATION-LEDGER.md) | 文字起こし断片を確定した意図とせず、原文と後続訂正へ戻れる |
| 意図を同じ仕事と成果へ結ぶ | [Review Workflow](REVIEW-WORKFLOW.md)、[Company Pack](STARTER-WALKTHROUGH.md) | Source、Intent、Decision、Work、Verification、Promotionを区別し、選択した一つのTask ownerへ戻す |
| 初回の許可範囲で自律的に進める | [Agent entrypoint](../AGENTS.md)、[Security](../SECURITY.md) | 同じ許可を聞き直さず、期限・取消・対象は再確認する。ログインの本人操作は人が行う |
| 必要な文脈を小さく渡す | [Context](../README.md#context-platform--会社の共有記憶)、[Session ledger](SESSION-CONVERSATION-LEDGER.md) | 出典・訂正・現在の担当を落とさず、アクセス不可や古い資料を再注入しない |
| 話す・録音する・仕事を止める操作を分ける | [Voice](../README.md#voice--最初に価値を体感する入口)、Voice候補 [#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69) / [#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) | 呼びかけ、長時間・複数人、切断復帰、音質、負荷、背景の仕事の継続を同じ実経路で確かめる |
| 小さな成果を検証して学習へ戻す | [5-minute tour](FIVE-MINUTE-TOUR.md)、[Runtime](../runtime/README.md)、[Business Loop](../README.md#ai-business-loop) | テスト件数だけでなく成果の有用性、失敗、rollbackと次の改善を確認する |
| 手元の環境で再現・停止・復旧できる | [Installation lifecycle](INSTALLATION-LIFECYCLE.md)、[Runtime](../runtime/README.md) | 対象profileでinstall、実行、停止、backup/restoreを検証する。構成検査を実稼働としない |
| 参加者と事業に価値を返す | [Community / Office](../README.md#discord-の中に会社を作る)、[Business Loop](../README.md#ai-business-loop) | 参加・相談・通報・復旧の体験と、顧客需要や費用を含む成果を実測する |
| 公開と非公開、権利の範囲を守る | [License scope](LICENSE-SCOPE.md)、[STATUS](../STATUS.md)、[ROADMAP](../ROADMAP.md) | Kotodamaが扱える範囲のMITと第三者条件を区別し、private source・認証・実会話を公開候補へ混ぜない |

これは要件の地図です。各項目が運用済みであることは意味しません。このcheckoutで実行できるものは現在のファイルとSTATUS、実稼働は担当環境の証拠で確認します。新しい正式な決定・訂正があれば、その対象行と根拠を更新します。

## 採用済みの土台と残る候補

[共通基盤 #18](https://github.com/Kotodama-Project/Kotodama-project/pull/18)と[必須CIの修復 #73](https://github.com/Kotodama-Project/Kotodama-project/pull/73)が、この地図の前提です。mainへ入った範囲は、MITとその適用範囲、公開repoの基本規則、再現可能なCI、Company PackとSession/Conversationの検証、Cloudflare等の限定candidateです。実運用の一括採用ではありません。

後続作業は、PRの本文だけでなく現在のhead/base、差分、レビュー、必須CIを確認して選びます。古いSHAや承認待ちの記述を、現在の停止条件として使い回しません。

| 系統 | 次に確認する候補 | 判断の要点 |
|---|---|---|
| 仕事・文脈の継続 | [#43](https://github.com/Kotodama-Project/Kotodama-project/pull/43) → [#44](https://github.com/Kotodama-Project/Kotodama-project/pull/44) → [#45](https://github.com/Kotodama-Project/Kotodama-project/pull/45) → [#46](https://github.com/Kotodama-Project/Kotodama-project/pull/46) → [#47](https://github.com/Kotodama-Project/Kotodama-project/pull/47) | 引継ぎ、reader権限、実行入力、訂正の接続を前提順に確認する |
| 知識と検索 | [#48](https://github.com/Kotodama-Project/Kotodama-project/pull/48)、[#61](https://github.com/Kotodama-Project/Kotodama-project/pull/61)、[#59](https://github.com/Kotodama-Project/Kotodama-project/pull/59) | schema適合と、判断に使える根拠・鮮度を分ける |
| 音声 | [#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69)、[#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) | 二つのruntime ownerを並立させず、Task・原文の既存ownerへ接続する |
| 並列実行 | [#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67) | 非candidateの受入、拒否後のpayload増加などの未解決点を修正してから採用する |
| 別系統のcontrol-plane | [#49](https://github.com/Kotodama-Project/Kotodama-project/pull/49)と後続stack | 記載された実装の欠落やownerの重複を解消し、既存の知識系と合流する |
| 既存能力の移植 | [Migration Epic #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24)、[出典と権利 #25](https://github.com/Kotodama-Project/Kotodama-project/issues/25) | capabilityごとに出典・第三者条件・consumerを確認する |

PR一覧は作業選択のための入口です。件数やリンクの存在で全履歴読了、採用、配備を主張しません。元のPRが別branch向けでも、最終的にどのbytesがmainへ入ったかを確認します。

## 作業を一つ進める

1. 上のどの要件と利用体験を前進させるか、一文で固定する。
2. 正本、現在の担当、対象commitと作業範囲を確認する。既存Taskを別台帳へ複製しない。
3. 変更部分と未解決点を検証する。同じ入力と有効な証拠を何度も読み直さない。
4. 必須CIと対象に合った技術レビューを確認して統合し、結果を元の仕事へ返す。

Task契約を持つcheckoutでは、そのresolver / records / events / restart checkpointを使います。ない契約をあるものとして扱わず、別のTask正本を先に作りません。

公開Botの提供、配備、会社のCurrent Truth、Public Betaへの移行は、それぞれの対象に合う実行証拠と決定で判断します。コードのmain統合だけでそれらを完了扱いにしません。
