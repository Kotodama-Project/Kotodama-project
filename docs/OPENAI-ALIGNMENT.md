# OpenAIへの役割分担

2026-10-22の選択は、**GPT-Liveの会話、公式ASRの確定文字起こし、Responsesの意図整理、Codex App Serverの仕事実行**です。[製品のモデル・認証](https://github.com/Kotodama-Project/discord-voice-template/blob/main/docs/MODELS.md)と[実装PR #4](https://github.com/Kotodama-Project/discord-voice-template/pull/4)を正本にします。

| 仕事 | 担当 |
|---|---|
| 音声会話・確定文字起こし | OpenAI。Discordの話者別入力、暫定/確定表示、割込みは接続側 |
| 目的・依頼・質問・提案の整理 | Responses API。確定した本人の明示依頼だけを実行へ渡す |
| 分担・実装・検証・継続 | Codex App Server。必要な協調はCodexに任せ、生成と検証をworkspace sandbox内で行う |
| 原文/訂正、依頼と実行の対応、取消、成果返送 | 音声repoの小さい接続状態。既存Task ownerを正本にし二重書込みしない |

最初の製品は既存workspace・Codex・Task経路を再利用します。Agents APIと別の実行loopを並行して追加しません。将来、実際の提供形態で別の公式基盤が必要になった場合だけ再評価します。

所有者はAPI課金と既存キーの再利用を許可しました。新規workerはAPI認証を隔離した一時認証で利用します。本人のChatGPT契約を使う場合は専用のCodex homeを明示し、APIとの自動切替をしません。音声とResponsesのAPI料金は契約利用枠とは別です。個人ログインを共有・hostedサービスの認証へ無条件に転用しません。

発話単位の確定ASRと会話のLiveを使い、暫定文字列は実行に使いません。原音の永続保存は任意で、既存記録の後処理・保持policyを勝手に変更しません。jobとthread/turn、入力revision、取消・照合待ち・配送状態を保持し、接続断を理由に同じ仕事を新規投入しません。

検証の正本は[製品の確認状況](https://github.com/Kotodama-Project/discord-voice-template/blob/main/docs/ACCEPTANCE.md)です。API疎通、合成課題、sandbox、CI、実Discord音声、移行・利用者受入は別の証拠として扱います。実Bot・DB・未処理依頼・録音の切替は[#442](https://github.com/Kotodama-Project/Kotodama-project/issues/442)に従います。
