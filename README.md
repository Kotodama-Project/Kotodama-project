# Kotodama / 言霊

**会話で決めた目的を、Codexで成果まで進める。目的・訂正・判断・検証はGitHubに残す。**

言霊はOpenAIの製品を使うための、小さな運用リポジトリです。
2026-10-21に独自Company OSの開発を終了し、OpenAIフルスタックへ方針を変更しました。
独自agent、Task DB、swarm、検索エンジン、管理画面、配備基盤は提供しません。
[English](README.en.md) · [変更の理由](docs/DECISIONS.md) · [旧版と移行](docs/RETIREMENT.md)

## まず一件を終わらせる

1. 実際に成果を作るリポジトリをCodexで開く。
2. 目的、完了条件、制約、元資料を伝える。[短い依頼の型](templates/project-brief.md)を使っても構いません。
3. Codexに調査・実装・必要な分担・検証を任せ、訂正は同じチャットへ伝える。
4. 成果を実際に確かめ、変更と検証をPRへ残す。未確認の結果は未確認のまま記録する。

新しいサーバー、APIキー、プラグインのインストールは不要です。
利用するOpenAI製品のログイン・権限と、必要な元資料へのアクセスは必要です。
[5分で始める](docs/FIVE-MINUTE-TOUR.md) · [依頼から完了まで](docs/WORKFLOW.md)

## やること・やらないこと

| 必要なこと | 使うもの | 言霊で作らないもの |
|---|---|---|
| 調査、計画、実装、分担、検証、再開 | Codexのチャットと既存の機能 | 独自実行ループ、worker、swarm、Task状態DB |
| 継続する仕事、定期確認 | 利用可能なDots・scheduled tasks | 常駐daemon、独自scheduler |
| 文書・資料・共有 | ChatGPT Work / Spaceと既存の保存先 | Company OS、独自GUI、専用ポータル |
| 外部サービスへの接続 | 既存の公式・接続済みplugin | Discord/Luma等の専用bridgeを先回りして開発 |
| 原意、訂正、採否、成果の根拠 | 対象repoの文書、Issue、PR、CI | 独自台帳、13段の審査経路、OKF検索・階層エンジン |
| 後から同じ背景を思い出す | OpenAI memory＋元資料の再確認 | 自作memory/Context Platform |

製品で足りない具体例が再現された場合だけ、公式OpenAI APIや最小の接続を検討します。
APIを使うためのAPIラッパーや、将来の汎用基盤は作りません。
[OpenAIへの役割分担と資料](docs/OPENAI-ALIGNMENT.md)

## 何をもって役に立ったとするか

実際の仕事で、途中の訂正を保ち、求めた成果と検証へ辿れること。
追加の手間が減らなければ、その手順や言霊の利用自体を減らします。
文書数・テスト数・agent数を成果の代わりにしません。

## 旧版を使っている場合

現在のmainは旧BotやPython packageの更新先ではありません。
旧実装は[固定した履歴](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b)から参照できます。
既存サービスや保存データは自動移行・停止・削除していません。
稼働中のconsumerは、[移行手順](docs/RETIREMENT.md)に従って実際の参照先を確認してください。

[現在地](STATUS.md) · [残る作業](ROADMAP.md) · [文書の地図](docs/PROJECT-MAP.md) · [貢献](CONTRIBUTING.md)

コードと文書は[MIT](LICENSE)。[セキュリティ報告](SECURITY.md) · [問い合わせ](SUPPORT.md) · [行動規範](CODE_OF_CONDUCT.md)
