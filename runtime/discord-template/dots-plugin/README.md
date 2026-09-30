# DotsからDiscordとLumaイベントを使う

作成済みDotとKotodama Discord templateをつなぐlocal pluginです。Dotの既存plugin・computer・browserを使います。[OpenAIへの適合方針](../../../docs/OPENAI-ALIGNMENT.md)も参照してください。

## 操作

`/kotodama dots text:...`、または許可channelのBotへのmentionで受付します。agent channelでは依頼者の新しいmessageを受付できます。訂正・削除は古い返答を止めます。`/kotodama dots_stop request:...`で受付を取消せます。Dotの別の背景作業はChatGPTのActivityで確認・停止します。

Lumaの新規作成・既存イベント更新を準備できます。設定と説明の全文JSON、確認buttonを本人へ送ります。本人の許可は5分間、一つの内容・対象に一回だけ有効です。Dotが公式websiteで操作し、読戻しを記録します。有料ticketや招待送信は含みません。

## 事前条件

- Node 24以上、templateの固定依存、Discord Botのconfigとcredential。
- 作成済みDotがpluginを使えるcomputer/environmentへ接続されている。local skillには接続computerが必要で、そのcomputerとChatGPT appを開いておく。
- Dot ownerのDiscord operatorを一人、利用channelを明示する。
- LumaはDotのbrowserでloginする。手元のbrowserのloginはクラウドbrowserへ継承されない。

configの追加例:

```json
{
  "dots": {
    "enabled": true,
    "actorId": "100000000000000002",
    "channelIds": ["100000000000000003"],
    "requestTtlSeconds": 3600
  }
}
```

IDsは合成例です。actorは`discord.operators`、channelは`discord.textChannelIds`から選びます。既定はdisabled。Bot起動・slash command登録は[templateの手順](../README.md)を使います。

通常messageへの返答は同じchannelが既定です。`dots.replyMode`を`dm`にすると本人のDMへ返します。privateなslash相談と、正確な住所などを含むLumaの内容確認は本人のDMへ届けます。CodexCatchupの専用確認channelは既存adapter側の接続確認で扱います。

Luma候補の説明・場所・URLなど、このtransportが複製した詳細は既定7日で消去します。`dots.draftRetentionDays`で1〜30日に設定できます。起動時・読取時・稼働中の定期回収で適用し、内容を含まないdigestと操作状態は残します。元のSourceやTask ownerの記録を消す操作ではありません。

開始済みの操作は、受付期限の後でも同じclaimと不変のSource・現在の閲覧権限で読戻しを記録できます。これは新しい操作や期限後のDiscord送信の許可ではありません。期限後の結果はDotと保存済みreportで確認し、Botからの新しい返答には新しい受付を使います。

## Pluginの設定

portable manifestは`plugin.json`、MCP設定は`mcp.json`、運用skillは`skills/discord-luma/SKILL.md`です。公式SDKのstdio serverを使います。MCP hostへ次の環境変数を渡します。

- `KOTODAMA_DISCORD_ROOT`: 導入済み`runtime/discord-template`の絶対path。
- `KOTODAMA_DOTS_CONFIG`: 対象Bot configの絶対path。

serverはrunning templateのloopback controlを使い、hostのowner/pid/start timeを照合します。credential・control token・config pathをツール結果へ返しません。cacheへコピーしても指定したtemplateからSDKとcontrolを読みます。public packageに個人のpathやcredentialを埋め込みません。

登録は[OpenAIのlocal plugin手順](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)に従います。repoの編集だけでDotへのinstallやcomputer accessを完了したとは扱いません。実行中appを自動で再起動しません。

Dotへoperator/channel、返答先、監視期間を伝えます。`discord_requests`は呼ばれた時点の読取です。MCP Eventsや即時起動にはprotocol 2026-07-28のwebhook、callback検証、remote HTTPSと接続受入が別途必要です。固定間隔の監視も、設定と実際の新着受付を確認してください。

## 受入の流れ

1. 合成の相談をDiscordで受付し、Dotから同じID/revisionを読む。
2. `discord_reply`で返し、送信先とmessage IDを確認する。
3. 別の相談を訂正・削除し、古い返答が拒否されることを確認する。
4. Lumaの合成候補と全文JSONを確認する。未許可・別人・訂正後・期限切れで操作を取得できないことを確認する。
5. 本人の許可後、`luma_claim_operation`で一回だけ取得する。既存イベントは対象URLと設定を読み直し、変更があれば候補と許可を更新する。
6. websiteのURLと全項目を読戻し、`luma_report_event`へ記録する。`DOT_REPORTED_NOT_INDEPENDENTLY_VERIFIED`は別の確認までprovider PASSにしない。

`tests/dots.test.mjs`は受付・権限・訂正・重複送信・中断・Luma bindingと公式SDKのstdio接続を確認します。live Discord、Dot自身の呼出し、Luma website操作は別の受入です。
