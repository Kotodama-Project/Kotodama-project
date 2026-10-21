# 現在地

方針更新: 2026-10-21。Discordの利用体験を残すという所有者の補正を反映しています。

| 対象 | 状態 |
|---|---|
| 製品の目的 | Discordの会話→逐次文字起こし→ゴール・仕事→OpenAIでの協調実行・検証→成果返送を継続 |
| 製品コードの集約先 | 既存[discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template)。旧本体/私有拡張との修正差分・現実環境での受入が残る |
| このrepoのactive source | 移行の入口、目的と判断、Codex直接利用の手順、GitHub用の検査。起動できるBotは含まない |
| 独自Company OS | 開発終了。独自swarm、汎用Task/Project OS、知識engine等は復活させない |
| 旧source | [50ca4d2](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b)に保全。実稼働pinや他repoの修正とは区別する |
| Discordの証拠 | 音声repoに過去の実テキスト依頼・Codex実行・成果DM・訂正の記録あり。現在の音声E2E成功を意味しない |
| OpenAIへの接続 | 音声と仕事実行の認証・利用条件・費用上限の確定が必要。Codexアプリや個人CLIの利用から共有Botの接続成功を推論しない |
| 旧環境 | サービス・consumer・DB・未処理の仕事・保存データは未移行。限定棚卸しと保持処理の既知障害は[#442](https://github.com/Kotodama-Project/Kotodama-project/issues/442)で追跡 |
| Repositoryのarchive | 未実施。後継の実利用と残件・復旧先の引継ぎ後に判断する |
| 公開提供 | 旧Company OS Public Beta計画は終了。新しいDiscord製品の公開提供や招待は未受入 |

検査結果は各PRのCI、製品受入は[音声repoのIssue #3](https://github.com/Kotodama-Project/discord-voice-template/issues/3)を正本にします。文書・ローカル・CIの成功を実音声・移行・利用者受入の成功へ読み替えません。
[残る作業](ROADMAP.md) · [方針変更](docs/DECISIONS.md)
