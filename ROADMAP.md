# 残す仕事

独自Company OSの開発は終了し、Discordから使えるOpenAI中心の製品へ絞ります。旧計画の全件再開や新repositoryの作成はしません。

1. **[Discord製品を一つの実利用経路で完成させる（音声repo #3）](https://github.com/Kotodama-Project/discord-voice-template/issues/3)。** 既存の音声repoへ必要な修正だけを引き継ぐ。発話者付きの逐次文字起こし、ゴール・仕事への整理、OpenAIでの分担・実行・検証、訂正・停止、Discordへの成果返送を実際のVCで確認する。認証・費用・実行隔離は構成を決めてから接続する。
2. **[稼働物とデータを必要な順に引き継ぐ（#442）](https://github.com/Kotodama-Project/Kotodama-project/issues/442)。** 実際のsource pin、保存データ、未処理の仕事、保持処理、reader/writer互換、復旧先を確認する。後継の実利用と読戻しが通った対象から切り替える。その後、不要な旧サービスとこのrepoのarchiveを判断する。

進捗・完了条件は上の二つのIssueに集約します。[#441](https://github.com/Kotodama-Project/Kotodama-project/issues/441)のCodex＋GitHub実案件は直接利用の一例であり、Discord版の移行完了ではありません。

## 開発しないもの

独自swarm/再計画loop、agent registry、全社Task/Project OS、Company Pack審査engine、OKF検索・階層engine、Cloudflare OS、汎用配備製品、独自管理GUI、Luma専用bridge、多provider抽象化、旧fixtureの性能競争。

Discord接続に必要な小さい永続状態、実行先との対応、取消・訂正・再送制御は開発対象です。これは旧業務OSの復活を意味しません。
旧Issueは旧実装計画として終了したまま、必要な利用者要件を製品Issueへ引き継ぎます。閉じたことを完成・移行の証拠にしません。
