# Kotodama / 言霊

**Discordで話す。目的と仕事に整理する。OpenAIのagentが協力して進め、確認した成果を同じ場所へ返す。**

言霊が残すのは、会話から目的・訂正・実行・成果・学びをつなぐ体験です。
独自Company OSの開発は終了しましたが、この体験は継続します。
2026-10-21の縮小でDiscord製品まで開発対象外にした判断を訂正しました。
[English](README.en.md) · [残す目的](docs/OWNER-INTENT-COMPANY-AGI.md) · [判断の経緯](docs/DECISIONS.md)

## 目指す使い方

1. DiscordのテキストやVCで自然に相談する。必要ならAIが音声で応答する。
2. 発話者付きの文字起こしが逐次見え、誤りや依頼の訂正を同じ仕事へ反映できる。
3. 会話からゴールと必要な仕事を整理し、明示された依頼・既存の許可の範囲で進める。雑談は勝手に実行依頼へ変えない。
4. OpenAIの公式実行基盤に分担・実装・検証・再開を任せ、進捗と成果をDiscordへ返す。
5. 原依頼、訂正、採否、成果、検証へ戻れ、次の仕事に活かせる。

これは製品の目標です。現在のmainをcloneしてもDiscord Botは起動しません。

## 開発先と現在地

製品コードは既存の **[discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template)** へ集約します。音声会話・文字起こし・明示依頼の実行に絞った公開候補がすでにあるため、新しいrepositoryや旧Company OS全体は作り直しません。

その候補には実Discordのテキスト依頼から実Codex実行・成果返送までの[過去の確認記録](https://github.com/Kotodama-Project/discord-voice-template/blob/ce571e94fd59464ba0d014688348fe7c905f9c27/docs/ACCEPTANCE.md)があります。発話表示・確定ASR・Responses・Codex App Server接続は[製品PR #4](https://github.com/Kotodama-Project/discord-voice-template/pull/4)で実装し、現在の[確認状況](https://github.com/Kotodama-Project/discord-voice-template/blob/main/docs/ACCEPTANCE.md)を製品側に記録します。実VCの連続利用と既存Botの切替は受入が残っています。旧本体・音声repo・稼働中の私有拡張は分岐しており、そのまま配備できる後継版とは扱いません。

製品化は **[音声repoのIssue #3](https://github.com/Kotodama-Project/discord-voice-template/issues/3)**、既存サービス・保存データの移行は **[このrepoのIssue #442](https://github.com/Kotodama-Project/Kotodama-project/issues/442)** で追跡します。
このrepoは移行の入口として維持し、後継の実利用・残件の引継ぎ・復旧手段が確認できてからarchiveを判断します。現時点で別repoのrename/archiveやサービス停止は行いません。

## 作る範囲を小さくする

| 必要なもの | 担当 |
|---|---|
| 会話理解、音声AI、要求整理、分担、実行、検証 | OpenAIの公式製品・API。Discordでの利用経路と認証・費用条件を確認して選ぶ |
| Discord音声/テキスト、発話者、逐次表示、訂正、進捗・成果の返送 | 音声repoの小さな接続部分 |
| 依頼とOpenAI sessionの対応、取消、再起動復旧、重複配送防止 | 接続に必要な最小の永続状態。独自の業務OSには広げない |
| 原意、制約、判断、成果の根拠 | 元の会話と対象projectの既存文書・成果物。コードの仕事はGitHub Issue・PR・CI |

独自swarm、全社Task/Project DB、汎用知識engine、13段の審査、専用GUI、複数provider抽象化は復活させません。
Codexアプリで仕事を完了できることと、Discordから同じ体験を使えることは別に確認します。
[OpenAIへの役割分担](docs/OPENAI-ALIGNMENT.md)

## 移行中の利用

現在のmainは旧BotやPython packageの更新先ではありません。
旧実装は[固定した履歴](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b)に保全しています。
稼働中のBot、未処理の仕事、録音、文字起こし、保存データは未移行で、自動停止・削除していません。
[移行手順](docs/RETIREMENT.md)に従い、必要な修正と実際のconsumerを照合します。

Codexを直接使う仕事は今も[短い手順](docs/FIVE-MINUTE-TOUR.md)で進められます。これはDiscord版の代替受入ではありません。

[現在地](STATUS.md) · [残る作業](ROADMAP.md) · [文書の地図](docs/PROJECT-MAP.md) · [貢献](CONTRIBUTING.md)

コードと文書は[MIT](LICENSE)。[セキュリティ報告](SECURITY.md) · [問い合わせ](SUPPORT.md) · [行動規範](CODE_OF_CONDUCT.md)
