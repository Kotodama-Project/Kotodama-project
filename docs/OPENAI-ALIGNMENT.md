# OpenAIへの役割分担

確認日: 2026-10-21。公式資料上の能力と、このaccount・Discord環境で実際に使えたことを区別します。
**OpenAIへ思考と実行を寄せ、Discordで使うための接続部分を残します。**

| 仕事 | 方針 |
|---|---|
| 自然な音声会話・即時文字起こし | 既存GPT-Live/Realtime経路を評価し再利用。Discordの話者別入力、暫定/確定表示、割込みは接続側で扱う |
| ゴール・タスク整理、分担、実装、検証、再開 | 一つの公式OpenAI実行基盤へ委譲。独自swarmや固定人数のworker編成を作らない |
| Discordの依頼と実行の対応 | 原依頼/訂正revision、依頼者、送信先、OpenAI sessionとの対応を小さく保持 |
| 取消、再接続、再起動、通知 | 既存sessionと状態を照合し、二重実行・重複配送を防ぐ。音声停止と仕事の取消を区別 |
| 資料・背景・成果 | 元資料と対象projectの既存保存先。利用できる公式tools/pluginsを使い、汎用知識engineを作らない |

## 実行器の選択

共有・無人のbackendには[Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview)のmanaged harnessを候補にします。session、compaction、recoveryと[multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)を使い、Responses上に旧planner/worker loopを作り直しません。利用account、必要tool、実行環境、費用の受入は別です。

本人専用の実行には既存の[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)/CLI、継続会話や承認UIの組込みには[Codex App Server](https://learn.chatgpt.com/docs/app-server)を評価します。本人のheadless認証が可能なことと、共有・hosted Botへ同じ個人credentialを転用できることは同じではありません。[認証](https://learn.chatgpt.com/docs/auth)と各提供形態の条件に従います。対応するSign in with ChatGPTを使う場合も提供条件・利用者ごとの認証を確認します。

所有者はAPI課金利用を許可し、ChatGPT subscriptionとApp Serverも選択肢に含めました。音声と仕事実行の費用・上限を分けて確認し、利用可能な経路を一つ選びます。Codex desktopの画面をBotから操作する構成にはしません。

## 音声と仕事の接続

[GPT-Live](https://developers.openai.com/api/docs/guides/live)と[delegation](https://developers.openai.com/api/docs/guides/live-delegation)は会話と裏の仕事を接続する候補です。[Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription)のdelta/completedを扱う場合は、Discordの話者・時刻・区間と対応させます。混合音声の推測で本人や権限を決めません。

まず既存音声repoの会話・文字起こしを実測し、不足する表示・実行接続だけを修正します。Live、別音声assistant、独立ASRを無条件に三重で動かしません。未確定文字列をそのまま外部操作へ送らず、原文と訂正を分けます。

Discordの現行音声接続は[公式Voice仕様](https://docs.discord.com/developers/topics/voice-connections)に従います。長い仕事の結果は[interactionの期限](https://docs.discord.com/developers/interactions/receiving-and-responding)だけに依存せず、許可した通常のBot message/thread/DMへ返します。

## 最小限の永続状態

DiscordのjobとOpenAI session、最後の入力revision、取消、送信待ち/通知待ち、照合待ちの状態は製品側に必要です。[sessionの継続](https://developers.openai.com/api/docs/guides/agents-api/sessions)と[eventの復旧](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)に従い、切断時に新sessionへ同じ仕事を再投入しません。

この接続状態を保持するstoreは、廃止したCompany OSの業務台帳と区別します。OpenAIの内部計画を二重管理するTask/Project OSや汎用queue clusterは作りません。

## 確認する境界

- Codexを直接使う手順は有効ですが、Discordからの利用・即時表示・実音声・成果返送の受入を代替しません。
- memoryは背景の補助であり、実行許可や現在の正本を自動更新しません。
- local-first、原音保持、共有範囲、復元の旧保証は自動継承しません。実consumerとデータを移す前に確認します。
- この文書は構成方針です。API接続、共有Botの認証、実配備、利用者受入が完了したという証拠ではありません。
