# 複数の音声チャンネルとBotの割当

一つのinstallationで、最大8つのVoice channelを別々のVoiceRoomとして扱います。
単一のTask owner、Source履歴、利用上限を共有し、参加者・会話・モード・停止・接続の版は
roomごとに保持します。実装済み・実VCは未受入です（#142、#154）。

## 設定

`voicePool`を指定しない設定は従来の単一`discord.voiceChannelId`の動作です。
poolを指定すると、既存のvoiceChannelIdと`rooms`を合わせたチャンネルが対象になります。
以下のIDは合成例です。実際の設定はGit外へ保存してください。

```json
"voicePool": {
  "rooms": [
    {"channelId": "100000000000000005", "participantIds": ["100000000000000002"]},
    {"channelId": "100000000000000006", "mode": "minutes", "autoJoin": false}
  ],
  "bots": [
    {"applicationId": "100000000000000012", "botTokenEnv": "DISCORD_SECOND_BOT_TOKEN"}
  ]
}
```

`mode`、`autoJoin`、`participantIds`を省略したroomは既存の`voice`設定を使います。
Botは既存のメインBotと追加の最大7 Botです。追加Botにはguildとvoice stateのintentを使い、
テキストの二重取込や二つ目のTask ownerを作りません。application IDはlogin後に照合し、
同じBot・token環境変数・channelの重複を拒否します。Bot作成とtoken保存は人が行います。
`doctor`は追加Botの認証情報の有無だけを確認し、値や実接続の結果は表示しません。

このpoolでは原音保存・archive・rotationを有効にできません。単一VCの既存機能は維持します。
複数roomへ同じ保存先や投稿先を暗黙に流用せず、room別の保持・閲覧範囲を採用する前に拒否します。

## 操作と排他

Discordの`/kotodama voice`と`/kotodama consent`の`channel`で対象を選びます。
CLIでは`voice --actor ID --mode pause --channel ID`のように指定します。
pool全体のstatusは各roomを一覧で返し、複数roomで対象が曖昧な変更操作は拒否します。
同意・停止buttonは対象channelとnoticeの版を固定します。

Botを接続前に予約し、同じguildの別roomへ重ねて割り当てません。満杯なら
`VOICE_POOL_BUSY`で待機し、既存接続を移動させません。外部で既にVCへ接続しているBotも
使用中として扱います。接続失敗・破棄・gateway切断でその予約を解放します。
切断待ち中の遅い接続結果は、取消されたroomへ戻しません。

全roomは同じinstallationの既存host lockを持つ一つのruntimeが管理します。
二つ目のruntimeは同じdataDirでの起動を拒否します。独立dataDirや別host間の分散排他は
この実装の保証範囲ではありません。同じBotを別installationへ共有しないでください。
poolのBot/room構成を変更した場合は既存roomの利用を止め、runtimeを再起動して照合します。

返答・音声からの操作・解析・進捗は元Sourceのguild/channelからroomを選びます。
同意や参加対象の変更は該当roomへ適用し、他roomのepochや参加者を借用しません。
全体のoperator権限、費用上限、設定の読取失敗は従来どおりinstallation全体に適用します。

## 検証

`tests/voice-pool.test.mjs`で実VoiceRoomと合成のDiscord接続を使い、並行予約、満杯、
二重join、失敗・切断、遅い接続、room別の権限・同意・停止、構成拒否を確認します。
実Botの作成、実VCの同時接続、マイク品質と利用者の受入は#154に記録します。
合成成功は実Discord・providerの成功やPublic Betaの許可を意味しません。
