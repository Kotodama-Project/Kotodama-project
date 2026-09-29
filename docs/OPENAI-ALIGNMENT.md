# OpenAI Dotsを中心にしたKotodama

2026-09-30のユーザー方針に従い、Dotsを日常の対話・継続作業の第一候補とします。DevDayの発表と現行ドキュメントを読み、OpenAIが提供する機能を使えるところから採用します。会社の知識、Source、permission、訂正、Task、成果、検証証拠は既存の各ownerへ戻します。

## 今回の採用方針

Dotsの常駐agent、クラウドcomputer、継続作業、音声、プラグインを利用する方向です。Kotodamaは会社の文脈・許可・検証と、DiscordやLumaなど必要な接続を提供します。Cloudflare edgeは配信・接続の候補、公式Cloudflare OSは専用画面が必要な部分の候補として維持します。Dotsの利用だけで正本や権限を移しません。

モデル呼出しを「Dots接続済み」と表示しません。Dots製品、Agents API、GPT-Liveは別の経路です。今回のプラグインは作成済みDotから使うツールで、モデル呼出しやAPIキー作成を追加しません。

## DevDayと現行資料

確認日は2026-09-30 JST。9月29日の発表を中心に、関連する9月のAPI更新と現行ページを照合しました。全発表の完全な棚卸しではありません。

- [Dots発表](https://openai.com/ja-JP/index/introducing-dots/)、[利用方法](https://learn.chatgpt.com/docs/dots)、[連絡方法](https://learn.chatgpt.com/docs/dots/channels)、[computerとapps](https://learn.chatgpt.com/docs/dots/computers-and-apps)、[制御](https://learn.chatgpt.com/docs/dots/controls): 常駐作業と既存pluginを使える。現在の連絡先ガイドはChatGPT、Slack、Teamsで、Discordは記載されていない。textingの現行ガイドはcoming soon。発表された機能を、全アカウントへ提供済みとは扱わない。
- [製品更新](https://learn.chatgpt.com/docs/changelog)、[API更新](https://developers.openai.com/api/docs/changelog)、[廃止一覧](https://developers.openai.com/api/docs/deprecations): 製品の提供条件・APIの追加・移行期限を分けて確認する。既存設定のモデルは、実際の経路が利用可能か確認してから変更する。
- [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview): durable session、進捗、MCP、sandboxを使う独自agentの候補。9月29日のcomputer use追加は、Dot製品の接続を証明しない。既存Task ownerへつなぐ場合は別途検証する。
- [GPT-Live](https://developers.openai.com/api/docs/guides/live)、[delegation](https://developers.openai.com/api/docs/guides/live-delegation): 会話を続けながらbackendへ委譲できる。現在のDiscord音声経路を維持し、Dotsのnative callとの接続は未確認とする。
- [Plugin package](https://developers.openai.com/plugins/build/plugins)、[MCP server](https://developers.openai.com/plugins/build/mcp-server): portable `plugin.json`、`mcp.json`、`skills/`を採用。公式SDKで接続を検証する。
- [MCP Events](https://developers.openai.com/plugins/build/mcp-events): protocol `2026-07-28`、永続subscription、署名とcallback検証を持つwebhookが必要。今回のlocal stdio読取ツールをMCP Eventsや即時通知とは表示しない。remote HTTPSとEventsは別の接続受入が必要。
- [Lumaイベント仕様](https://docs.luma.com/reference/post_v1-events-create): 日時、timezone、description、場所の公開範囲、capacity、visibility、participant approvalを独立した値として扱う。今回の操作はDotの公式browserを使い、API接続済みとは表示しない。

同じOpenAI系列の複数ページは、独立した性能検証ではありません。発表、資料上の対応、アカウント状態、一連の実操作を分けます。

## DiscordとLuma

[Dotsプラグイン](../runtime/discord-template/dots-plugin/README.md)は既存BotのSourceを使う窓口です。指定した依頼者とchannelの相談を読み、本人へ返答します。Sourceの訂正・削除、権限の失効、期限切れを反映し、普通の相談で新しいTaskを作りません。

Lumaでは新規作成と既存イベントの更新を準備できます。Discordで操作・対象・設定・説明全文を確認し、本人がbuttonで許可した候補を一回だけ取得します。Dotがwebsiteで操作し、URLと全項目を読戻して報告します。未知の結果を再実行せず、Dotの報告を独立したprovider検証へ昇格しません。

実接続は、作成済みDot、Bot、plugin、running host、Luma loginを同じ窓で受け入れてからです。local code/SDK試験だけではDotのDiscord返答やLuma操作の完了を証明しません。

## Botの選択肢

既存Kotodama Botを最初の候補とします。Node templateとSource管理を直接使い、作成済みDotへの入口を一本化しやすいためです。Bot・channel・operatorをconfigで固定します。

CodexCatchup Botも検討対象です。稼働実装、Task owner、既存outboxとの接続を確認してからadapterを作ります。名前だけでNode control APIとの互換を判断しません。運営用の専用channelを維持する構成を優先します。

Dots専用Botはtemplateを別config・別dataDir・別Discord applicationで使う案です。権限と運用を分けやすい一方、Bot登録と運用が増えます。同じdataDirを複数Botが共有しないことが条件です。

比較段階では既存の稼働Botを更新・停止・置換しません。まず一つのBotで相談、返答、訂正、Luma確認を受け入れ、その結果を他のBotへ適用します。
