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

単なる提案・質問を実行依頼に変えません。既定の音声開始方式では「ことだま、」と呼びかけ、テキストではBotをメンションするか `/kotodama do` を使います。録音の停止と仕事の停止は別です。

## 最初の設定

この公開リポジトリを取得して `runtime/discord-template` へ移動してから、以下のコマンドを実行します。GPT-Live 1で自然会話を試す設定は[音声の設定例](docs/DISCORD-SETUP.md#自然会話を試す設定例)にまとめています。

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

固定ラウンジへ自動で入退室させる場合は `voice.autoJoin` を `true` にします（既定は `false`）。設定したサーバー・VCに人がいて、全員が現在の音声処理対象なら接続します。ローカルASRと既定の `conversationStart: "wake"` では、BotがVCにいても呼びかけ前のLive接続は作りません。`speech` では操作者の発話検出から開始します。無人が15秒続いた後の確認で、最後の文字起こしを確定して退出します。別のVCへ利用者を追いかけません。

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

音声会話はOpenAIの **GPT-Live 1（`gpt-live-1`）／Live API** をDiscordの音声接続につなぎます。「Discord Live API」という別のモデルAPIではありません。

以下の確定テキスト待ち・commentary返却は `naturalConversation: false` の方式です。`true` ではLive内のResponses委譲で会話し、ローカルASRの完了を待ちません。

`assist`は `gpt-live-1`、`minutes`のクラウド文字起こしはVADと `gpt-live-transcribe` を使います。ローカルASRも選べます。呼びかけ後は同じLiveセッションを複数ターンで再利用するため、回答ごとの接続待ちがありません。Luna analyzerが確定テキストから意図を整理し、確認済みの返答だけを `session.commentary.append` でLiveへ戻します。Liveの断片文字起こしや自発音声は仕事のSSOTになりません。

発話中に利用者が話し始めると、Botはローカル再生と未再生queueを直ちに止め、同じセッションへ停止指示を送ります。仕事の実行はそのまま継続します。「もういいよ」などをLunaが `end_conversation` と構造化した場合はLiveだけを正常終了し、BotはVCでローカル待機へ戻ります。出力は既定120msを蓄えてから再生し、500msを超えるqueueは破棄します。値は `voice.outputPrefillMs` と `voice.maxOutputQueueMs` で調整できます。

ローカルASR構成でLiveを開始していない待機中は、音声クラウドAPIを呼び出しません。Live利用秒とLunaのinput・cached input・output tokenを別々に記録します。Lunaへ渡す会話contextと最大出力も設定で上限を持ち、usage snapshotは累積値として置き換えるため二重加算しません。`naturalConversation: false` のLive会話は人の入力が既定120秒なければ閉じ、Botはローカル聞き役のまま残ります。`voice.conversationIdleSeconds` で30〜600秒に調整できます。

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

### 会話の開始と退出

呼びかけを文字起こしできない場合は、対象VCにいる操作者が `/kotodama voice mode:start_conversation` で会話を開始できます。`end_conversation` はLiveだけを終了します。無人時や退出操作ではDiscordから先に切断し、最後の確定済み入力を記録し終えます。退出後の入力から新しい仕事や返答は始めません。

VM別の配備はインストール、Bot、VC、データ領域、作業領域を分け、`agentBinding` に `agentId` と `vmId` を設定します。実行中の別VM・Bot・作業先への差し替えは接続を停止します。この設定自体はVMの実在や到達性を検証するものではありません。

`voice.contextCorrection` は既定で無効の試験機能です。Lunaによる短い訂正候補を原文とは別に保存します。音声で検証された訂正ではなく、話者別音声と全体音声を照合する既存の保存用パイプラインを置き換えません。

対象VCで呼び名を付けずに話し始めたい場合は `voice.conversationStart: "speech"` を明示設定します。許可された操作者の入力が一定時間続いたときにLiveを開始し、接続待ちの音声も渡します。無音と短い物音は除きますが、人の声を厳密に分類する機能ではないため、継続的な雑音でも起動する可能性があります。既存の利用上限は引き続き適用されます。

`voice.naturalConversation: true` は既存の自然会話方式を移した選択肢です。音声の応答はLiveとLunaで進め、ローカル文字起こし完了を待ちません。音声入力は20ms間隔で送信し、開始待ちのバッファを上限付きで保持します。会話終了はツール判断で行い、短い無言では終了せず、接続時間と累計利用上限は維持します。話者別のローカル原文は別経路で記録します。

### 夜間の通知

`notifications.quietHours.enabled: true` では、仕事の完了とLuma取込の通知を日本時間22時から翌9時まで保留します。保留は既存DBに残し、朝以降に宛先・出典の権限を再確認して送ります。利用者への直接の会話応答は保留しません。送信時の自動メンションは無効です。

### 原音と文字起こしの保存

既存の保存先を使う場合は `archive` の接続設定と `voice.storeAudio: true` を明示します。話者別の48kHz原音・全体音声・原文・訂正文を分け、既存の30日原音保持に接続します。保存の後処理は退出後に並列1で進め、音声会話は待ちません。再起動時には最後の永続フレームから再開し、正常退出時は最後のバッファも保存します。詳細は [保存接続](docs/ARCHIVE-RUNTIME.md) を参照してください。

個人でのLive会話では、プロジェクトの `README.md`、`CONTEXT.md`、`briefs/`、`docs/` から関連する短い抜粋を出典付きで読む機能があります。最大3資料・6000文字に絞り、資料の記載と実環境の確認を区別します。他の参加者がいるときは個人資料を読み上げません。

## 任意のエージェント実行器との接続案（未実装）

**以下はKotodama側に追加する接続契約の案です。OpenClaw adapterやサブエージェント起動は未実装・未検証です。**

- KotodamaがVCを所有する場合：client delegationを受け、確定Source・Intent・現在の許可を既存Task ownerで解決し、認可済みTaskだけをremote owner adapterからOpenClawの `sessions_spawn` 等へ渡す。結果は検証・必要な秘匿処理を経て、同じTaskとLiveの委譲IDへ返す設計です。
- OpenClawがVCを所有する場合：KotodamaのSource/Intent/Task契約をtoolまたはremote ownerとして接続する設計です。このテンプレートの音声接続は同時起動せず、同じBot/VCの所有者を一つにします。

どちらもVM・Bot・VC・Task・source revision、対象操作と期限、重複抑止、取消、結果の閲覧範囲をadapterで検査します。actor文字列や委譲イベントだけを認証・依頼本文・許可と扱わず、音声APIキーや全会話を子へ渡しません。音声終了と仕事取消は別に扱い、結果を一つのTask ownerへ戻します。[remote owner契約](docs/TASK-OWNER.md)への接続実装と実経路の検証が必要です。

実装時の一次資料：[OpenAI client delegation](https://developers.openai.com/api/docs/guides/live-delegation?delegation-mode=client)、[OpenClaw sub-agent tool](https://docs.openclaw.ai/tools/subagents/tool-reference)、[OpenClaw Discord voice](https://docs.openclaw.ai/channels/discord/voice-channels)。
