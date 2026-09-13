# Kotodama Discord Template

**Discordで話す・頼むところから、意図、仕事、成果へ。**

個人やコミュニティが自分のDiscordで使い、使って分かった不便さを直していくためのMITライセンスのテンプレートです。Cloudflare、n8n、組織全体の導入は必須ではありません。

現在は開発候補です。ローカル試験と実Discord・音声・利用者の受入は[確認状況](docs/ACCEPTANCE.md)で分けています。

## できること

- 「この会話を整理して」：読取可能な履歴と添付テキストを、出典・取得範囲付きの一つの資料にします。
- 「ことだま、どう思う？」：人間中心の会話を聞き、呼ばれたときに答えます。
- 「議事録モードにして」：音声を返さず、文字起こしから意図・決定・ToDoを整理します。
- 「このファイルを直して」：許可した仕事をCLI実行器へ渡し、変更候補と実際の検証結果を確認します。
- 訂正、仕事の停止・再開、成果の取得、別の人やチャンネルとの分離を扱います。
- 任意でLumaのイベント運営とn8nをつなげます。無料Lumaではブラウザ・CSVを使います。

単なる提案・質問を実行依頼に変えません。音声では「ことだま、」と呼びかけ、テキストではBotをメンションするか `/kotodama do` を使います。録音の停止と仕事の停止は別です。

## 最初の設定

最初に[新しいBotの作成手順](docs/DISCORD-SETUP.md)を確認してください。CLIでできる準備と、ログイン・本人確認・サーバー認証を人が行う箇所を分けています。

Node.js 24以上、Git、pnpmを用意します。書込みを伴う参照workerはLinuxで実行し、WindowsはCLIクライアント・読取workerとして利用できます。Codex Desktopの専用機能には依存しません。

```sh
pnpm install --frozen-lockfile
node bin/kotodama.mjs init --guild YOUR_GUILD_ID --app YOUR_NEW_APPLICATION_ID --operator YOUR_USER_ID --channel YOUR_TEXT_CHANNEL_ID --workspace /path/to/your/repository
node bin/kotodama.mjs doctor --json
```

生成した `.kotodama/config.json` で次を設定します。

1. Botが使うテキスト・音声チャンネルと、操作する人。
2. 音声チャンネルと `voice.participantIds` の処理対象。既定の `owner_managed` では、人間側が説明・同意確認の責任を持ち、Botは確認を繰り返しません。参加者クリックを使う運用は `participant_opt_in` で選べます。
3. 待機中の文字起こし方法。`voice.transcriptSource: "local"` とOpenAI互換のローカルASR endpointを設定すると、日本語の確定テキストをSource Evidenceとして保存し、呼びかけ前はGPT-Liveを開きません。設定しない場合は従来どおりLiveの文字起こしを使います。
4. CLI実行器の実ファイル、モデル（既定はLuna）、作業対象、許す操作、検証コマンド。[モデルと任意のフォールバック](docs/MODELS.md)。
5. 音声の一回・一日あたりの上限。既定の一日上限は0なので、設定前に音声APIへ接続しません。

ローカルASRを使う最小設定例です。endpointはHTTPS、loopback、private LAN、またはtailnet内だけを受け付けます。

```json
{
  "transcriptSource": "local",
  "wakeWords": ["ことだま", "ことたま", "言霊", "kotodama", "エージェント"],
  "localAsr": {
    "url": "http://127.0.0.1:9000/v1/audio/transcriptions",
    "protocol": "openai",
    "model": "tiny",
    "language": "ja",
    "initialPrompt": "ことだま コトダマ 言霊 エージェント"
  }
}
```

固定ラウンジへ自動で入退室させる場合は `voice.autoJoin` を `true` にします（既定は `false`）。設定したサーバー・VCに人がいて、全員が現在の音声処理対象なら接続します。ローカルASR構成ではBotがVCにいてもAPI接続は作らず、「ことだま、」という呼びかけ後だけLive会話を始めます。無人が15秒続いた後の確認で、最後の文字起こしを確定して退出します。別のVCへ利用者を追いかけません。

必要な環境変数は `.env.example` にあります。値は信頼できる実行ホストだけに置き、GitやCLIの引数へ書きません。`.env` を使う場合は `node --env-file=.env bin/kotodama.mjs ...` で読み込みます。

```sh
node --env-file=.env bin/kotodama.mjs register
node --env-file=.env bin/kotodama.mjs start
```

CLI実行器は既定で `--ignore-user-config` を付け、別用途のMCP設定を取り込みません。認証は実行ホストのCodex CLIログインを利用します。意図整理だけは、同じ音声APIキーでLunaを直接呼ぶ[Responses analyzer](docs/MODELS.md)も選べます。モデルはこのテンプレートの設定で選べます。

BotはDiscord側でも対象サーバーへ導入してください。Message Contentを有効にし、対象チャンネルの閲覧・履歴読取・送信・ファイル添付・音声接続・発話を許可します。Administratorは必要ありません。既存の同名コマンドを無断で上書きしません。

## 普段の使い方

| 操作 | Discord |
|---|---|
| 相談 | Botへのメンション、または `/kotodama ask` |
| 明示的に仕事を頼む | `/kotodama do` |
| 自分の仕事を見る | `/kotodama tasks` |
| 成果を読む | `/kotodama result` |
| 仕事を止める・再開する | `/kotodama stop` / `/kotodama resume` |
| 聞き役 | `/kotodama voice assist` |
| 議事録のみ | `/kotodama voice minutes` |
| 音声処理の運用・自分の停止設定 | `/kotodama consent` |
| VCへ接続 | `/kotodama voice join` |
| 録音を止める | `/kotodama voice pause` |
| 録音と自動接続を再開する | `/kotodama voice resume` |
| VCから退出して自動接続を止める | `/kotodama voice leave` |
| 発話だけ止める | `/kotodama voice stop_speech` |

`pause` / `leave` は再起動後も保持します。`join` / `resume` で解除でき、モード切替だけでは解除しません。`voice status` で自動接続、参加者待ち、手動停止、利用上限の状態を確認できます。

成果通知は依頼者へのDM、コマンド結果は依頼者だけに見える返信です。配送できなかった場合は重ねて自動送信せず、`result`から確認できます。成果は確認待ちとして返し、利用者の採用を代行しません。

`assist`は `gpt-live-1`、`minutes`のクラウド文字起こしはVADと `gpt-live-transcribe` を使います。ローカルASRも選べます。呼びかけ後は同じLiveセッションを複数ターンで再利用するため、回答ごとの接続待ちがありません。Luna analyzerが確定テキストから意図を整理し、確認済みの返答だけを `session.commentary.append` でLiveへ戻します。Liveの断片文字起こしや自発音声は仕事のSSOTになりません。

発話中に利用者が話し始めると、Botはローカル再生と未再生queueを直ちに止め、同じセッションへ停止指示を送ります。仕事の実行はそのまま継続します。「もういいよ」などをLunaが `end_conversation` と構造化した場合はLiveだけを正常終了し、BotはVCでローカル待機へ戻ります。出力は既定120msを蓄えてから再生し、500msを超えるqueueは破棄します。値は `voice.outputPrefillMs` と `voice.maxOutputQueueMs` で調整できます。

待機中のAPI呼出しは0にし、Live利用秒とLunaのinput・cached input・output tokenを別々に記録します。Lunaへ渡す会話contextと最大出力も設定で上限を持ち、usage snapshotは累積値として置き換えるため二重加算しません。Live会話は人の入力が既定120秒なければ閉じ、Botはローカル聞き役のまま残ります。`voice.conversationIdleSeconds` で30〜600秒に調整できます。

実装はOpenAI公式の[GPT-Liveセッション管理](https://developers.openai.com/api/docs/guides/live-conversations)、[client delegation](https://developers.openai.com/api/docs/guides/live-delegation?delegation-mode=client)、[サーバー側の再生制御](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)、[音声コスト最適化](https://developers.openai.com/api/docs/guides/voice-latency-cost?api=live)に合わせています。

## CLI・資料・連携

```sh
node bin/kotodama.mjs request --actor YOUR_USER_ID --action research --text "この資料の未決事項を整理して"
node bin/kotodama.mjs tasks --actor YOUR_USER_ID
node bin/kotodama.mjs import-discord --actor YOUR_USER_ID --limit 10000
node bin/kotodama.mjs export --actor YOUR_USER_ID --output ./meeting.md
node bin/kotodama.mjs import-luma --actor YOUR_USER_ID --file ./guests.csv
node bin/kotodama.mjs browser read --tab 0 --json
```

履歴取込は起動中のBotを停止してから行います。上限到達・取得失敗・未対応添付を明示し、読めなかった情報を「全件読了」に含めません。現在の添付本文取込はUTF-8のテキスト・Markdown・CSV・JSONです。その他の形式は取得状況に未対応として残します。

- [CLIでのブラウザ操作](docs/BROWSER.md)
- [無料Lumaとn8n](docs/LUMA-N8N.md)
- [Task owner接続契約](docs/TASK-OWNER.md)
- [構成・権限・出典](docs/ARCHITECTURE.md)
- [起動・停止・復旧](docs/OPERATIONS.md)

## 開発と公開

```sh
pnpm test
pnpm check
```

実サーバー、参加者、音声、認証情報、作業成果をこのGitへ入れません。変更は機能に合った検証と独立レビューを通し、普段使いのフィードバックを次の改善へ戻します。

[MIT](LICENSE)。同梱・利用する依存関係には各依存関係のライセンスが適用されます。[出典](docs/PROVENANCE.md)も参照してください。
