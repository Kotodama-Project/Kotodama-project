# 方針の決定

## 2026-10-26 — 実利用を基準にした置換と既存接続の活用

使えることを優先し、原意・訂正・継続中の仕事・権限・成果・配送記録を保持します。下記の旧開発終了は、独自基盤全体を再構築しない方針です。必要なUI・保存・接続まで機能名で一律に禁止する意味には使いません。実例と受入条件を示し、最小の差分を製品repoへ実装します。

後継への置換は、実Discordの依頼→実行途中の訂正→訂正を反映した成果の読戻しを確認し、別のシナリオで停止・翌日または再起動後の再開も確認した機能から個別に行います。既存の共有範囲と未処理仕事・保存データの引継ぎ、切戻しも確認します。旧sourceの削除やAPI単体の成功だけで退役済みとは扱いません。自社SaaSとしての提供には、別の許可済みインストールでも設定・データ・権限・使用量を分離して再現できることが必要です。

Tailscaleは既存Linux実行機へのprivateな運用接続として活用します。既存SSH経路を再利用し、BotとCodex App Serverは実行機内で接続します。Task ownerは単独の正本を維持します。実機の到達性、アプリの稼働、利用者の受入はそれぞれ確認します。実際の端末情報はprivateな運用記録に置き、外部公開や既存の無関係なサービス変更は行いません。

実利用の条件と確認状況は[製品の受入記録](https://github.com/Kotodama-Project/discord-voice-template/blob/main/docs/ACCEPTANCE.md)、移行残件は[#442](https://github.com/Kotodama-Project/Kotodama-project/issues/442)へ集約します。

## 2026-10-21 — OpenAIへの集約とDiscord製品の継続

所有者はOpenAIの既存技術で可能な限り置き換え、不要な独自基盤を減らすことを求めました。
最初の整理ではmainをCodex＋GitHubの運用文書へ縮小しましたが、Discordで会話から仕事が進む利用体験まで開発対象外にしたのは広すぎる解釈でした。所有者の補正に従い、その部分を訂正します。

### 残す目的

Discordで自然に話す・文字起こしを確認する・目的と仕事へ整理する・AIが協調して実行と検証を進める・同じ場所で成果と訂正を扱う。この体験と、原意・上位制約・判断・学びを保つ目的は継続します。詳細は[所有者の目的](OWNER-INTENT-COMPANY-AGI.md)に置きます。

### 開発先

既存の[discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template)を製品コードの集約先にします。新repoや旧Company OS全体は作り直しません。
音声repo、旧本体、実稼働の私有拡張は分岐しているため、音声・訂正・実行隔離・保存の必要な変更を選択して引き継ぎます。出典とライセンスを保ち、private dataや履歴を公開へ丸ごとコピーしません。

このrepoは移行の入口として維持します。後継で実体験が通り、未処理の仕事・保存データ・既知障害・consumer・復旧先の引継ぎが確認できてからarchiveを判断します。BecomeOne等の移行元や別repoを一括archive/renameしません。

### OpenAIと製品の責任

- 会話、要求整理、分担、実行、再開、検証はOpenAIの公式製品・実行基盤へ寄せる。
- Discordの音声/テキスト接続、話者、原文/訂正、仕事とOpenAI sessionの対応、取消・配送・再起動復旧は製品側の最小実装として残す。小さい永続storeを許容する。
- 仕事の成果と判断は、そのprojectの既存文書・成果物・Issue・PRへ返す。OpenAI側の計画や業務状態を別OSへ二重登録しない。
- Codexアプリの成功はDiscord製品の成功ではない。実音声→実仕事→成果返送と途中訂正・停止・復旧を確かめる。

### 費用と認証

所有者はOpenAI APIの従量課金利用を許可しました。旧owner intentのmetered API除外は現行方針ではありません。
ChatGPT subscription、本人専用Codex CLI、Codex App Server、APIは候補に含めます。利用形態ごとの公式認証条件、利用可否、具体的な費用上限を確認します。個人のログインを共有Botの全利用者の認証として無条件に転用しません。

### 全体の再構築を行わない旧基盤

独自Company OS、swarm・再計画loop、agent registry、汎用Task/Project OS、OKF検索・全階層engine、Company Pack審査runtime、専用GUI、Cloudflare OS、万能adapter、多provider抽象化、旧fixtureの性能競争。
Discord製品に必要な接続を「専用bridgeだから不要」と一律に除外しません。必要な利用体験に直接効く最小部分だけを実装します。
必要な機能の判断には、2026-10-26の実利用を基準とした補正を適用します。

### 引き継ぐ責任

実稼働物、未処理の仕事、録音・文字起こし、保持条件、reader/writer、鍵と復旧先は[移行手順](RETIREMENT.md)で確認します。既知の保持処理障害や互換未受入はsource削除で消えません。
OpenAI利用は旧local-firstや保持・可搬性保証を自動継承しません。共有範囲と元資料の権限を維持します。

進捗は[製品Issue](https://github.com/Kotodama-Project/discord-voice-template/issues/3)と[移行Issue](https://github.com/Kotodama-Project/Kotodama-project/issues/442)へ集約します。旧Issue全件の再開はせず、必要な要件と既知欠陥だけ引き継ぎます。
