# 所有者の目的

会話で示した原意・制約・訂正を保ち、必要な仕事を進め、成果を検証して次の仕事に活かす。この目的は継続します。
2026-10-21の所有者の補正により、**Discordで自動的に会話し、すぐ文字起こしし、ゴール・タスクへ整理し、AIが協調して実行する使いやすい製品**を中核として残します。

## 引き継ぐもの

- 相談・音声・文書から意図を理解し、曖昧な点だけ確認する。必要以上の承認や別画面での入力を要求しない。
- 目的と完了条件を保ち、途中訂正を同じ仕事へ反映する。原文を推測で上書きしない。
- 必要なAIが分担し、依存する仕事を順に進め、実成果を検証する。止める・再開する・成果を確かめる操作もDiscordからできる。
- 既存projectの資料・判断・成果へ辿り、次の仕事に活かす。コード以外の調査や資料作成も目的に含む。
- 既存の許可は引き継ぎ、雑談・引用・他参加者の発話を新しい実行権限にしない。

## 実装を小さくする

OpenAIに会話・推論・分担・実行を任せ、言霊はDiscord固有の接続、話者・原依頼・訂正、OpenAI sessionとの対応、取消・復旧・成果配送に絞ります。
接続のための永続状態は必要です。独自Company OS、汎用Task/Project DB、causal ledger、OKF、全8階層engine、専用GUI、多provider基盤は必須実装にしません。

所有者はOpenAI APIの従量課金利用を許可し、ChatGPT subscriptionとCodex App Serverも選択肢として示しました。各経路の利用条件、認証、具体的な上限を確認して使い分けます。API利用許可を、共有Botでの個人credential転用や無制限利用の許可と扱いません。

旧要件と設計の全文は[保存したowner intent](https://github.com/Kotodama-Project/Kotodama-project/blob/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b/docs/OWNER-INTENT-COMPANY-AGI.md)に残します。そこにある旧モデル固定・metered API除外・独自engineの実装方法は、現行の補正より優先しません。
[現在の方針](DECISIONS.md) · [製品の受入](https://github.com/Kotodama-Project/discord-voice-template/issues/3)
