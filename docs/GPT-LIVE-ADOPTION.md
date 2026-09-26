# GPT-Live の採用方針

> [!IMPORTANT]
> 状態は **candidate-only / `NO_GO_UNPUBLISHED`** です。この文書は製品の方針であり、配備済みの Bot、公開招待、Public Beta、本番での実行、Final Human GO を意味しません。provider を選んだことは、実 VC で動いた証拠ではありません。

- **採用の決定（2026-09-12、日本時間）**: OpenAI の GPT-Live 1（`gpt-live-1`）／Live API を、Kotodama の主なクラウド音声 provider にします。Discord の API ではありません。
- **runtime の一本化（2026-09-24、owner 判断、[#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)）**: 音声の runtime は main の Node runtime（[`runtime/discord-template`](../runtime/discord-template/README.md)）だけにします。[#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) の Python による Live 制御（`runtime/live/*`）と [#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69) の workspace 基盤（`runtime/live-workspace/*`）は取り込みません。
- **出典**: #71 の head `b3fda59` にあった `docs/GPT-LIVE-ADOPTION.md`（最後に変更した commit は `4d1c49c`）。日本語で書き直し、Node runtime の現状と違う記述を直しました。違いは「[#71 の設計との違い](#71-の設計との違いと後継の-issue)」にまとめています。
- **正本**: 実装の事実は `runtime/discord-template` のコードと [README](../runtime/discord-template/README.md) です。この文書と食い違うときはコードを正として、この文書を直します。

## 製品としての振る舞い

- **既定（`voice.naturalConversation: false`）**: 普段は黙って聞きます。挨拶、相槌、頼まれていない進み具合の発話はしません。話すのは呼びかけられたとき（呼び名、`conversationStart: "speech"` での操作者の話し始め、または `/kotodama voice mode:start_conversation`）だけで、返すのは確認済みの結果だけです。
- **自然会話（`voice.naturalConversation: true`）**: 明示的に選ぶ方式です。挨拶や普通の会話にも応じ、短い無言では会話を終えません。会話の判断役（Luna）が使える tool は、資料の短い抜粋を読む、この Bot の状態を読む、会話を終える、の 3 つだけで、外部を操作する権限はありません。
- **仕事を頼む**: 認証された参加者がはっきり頼んだときだけ、許可された操作（`worker.actions`）の範囲で仕事にします。名前が出ただけ、他人の依頼の引用、アイデアの議論、資料の読み上げは実行の許可になりません。対象が足りない依頼は実行せず、意図の候補として残します。
- **進み具合と成果**: 仕事が走り始めたら依頼者へ DM で件名と仕事の ID を届け、完了したら同じ DM へ成果を届けます（[#101](https://github.com/Kotodama-Project/Kotodama-project/pull/101)）。
- **会話の終了と仕事の取消は別**: 会話を終えても（`end_conversation`、自然会話の終了 tool）、すでに許可された仕事は取り消しません。沈黙も取消ではありません。
- **確認は必要なときだけ**: 誰に話しかけたか、依頼が足りているか、あいまいさ、訂正、どこへ返すかを判断し、確認は一度に一つまでにする考え方（GrillU の一般化、Interaction Policy）は [#145](https://github.com/Kotodama-Project/Kotodama-project/issues/145) で扱います。分類器の確信度は権限ではありません。

## Node runtime の構成（main の現状）

```text
Discord の固定の 1 VC（discord.voiceChannelId）
  -> 在室者の確認（bot を除く全員が、音声処理の対象であること）
  -> 話者ごとの受信（Discord の user ID ごとに別の session。bot の音声は取らない）
  -> 文字起こし: transcriptSource "live"（Live の文字起こし）または "local"（ローカル ASR の確定文）
  -> 会話の開始: conversationStart "wake"（呼び名）または "speech"（操作者の話し始め）
  -> assist: その話者の Live session（gpt-live-1、store:false）を開き、複数ターンで使い続ける
       -> Luna analyzer が確定した文から意図を整理 -> 既存の Task owner と限定 worker
       -> 確認済みの返答だけを session.commentary.append で同じ session へ返す
       -> Discord の再生（出力の世代・聞いてよい人・source revision に束縛）
  -> minutes: 文字起こし専用の session（gpt-live-transcribe）。音声は返さない
```

| 項目 | main の Node runtime |
|---|---|
| 対象の VC | 設定した一つの VC だけです。別の VC へ利用者を追いかけません。対象外の人がいる間は、新しい音声処理と再生を止めて退出します。 |
| 話者 | 話者ごとに別の Live session を使います。bot（自分と他の bot）は在室者の判定と受信から除きます。 |
| 同意 | `voice.consentMode` は `owner_managed`（運用者が対象者を設定し、説明と同意に責任を持つ）か `participant_opt_in` です。どちらでも本人の明示の opt-out を守ります。 |
| 文字起こし | `transcriptSource: "live"`（既定）は話者の音声を Live session へ送り、その文字起こしを使います。`"local"` はローカル ASR の確定した日本語を Source Evidence にし、呼びかけ前は Live を開かず、音声をクラウドへ送りません。どちらの文字起こしも誤り得る認識結果で、確定した意図や実行の権限とは扱いません。 |
| 会話（`assist`） | SDK の `LiveWS` で `gpt-live-1` を使い、`store: false` を設定します。呼びかけ後は同じ session を複数ターン使い、返答は `session.commentary.append` で返します。返答ごとに新しい session は作りません。Live が使えないときは失敗として止まり、別の protocol へ自動で切り替えません。 |
| 出力の許可 | 既定の方式では、アプリが返答を渡すまで Live の音声を再生しません（頼まれていない音声は捨てます）。再生は出力の世代・聞いてよい人・source revision に束縛し、在室者や権限が変われば止めます。 |
| 割り込み | 利用者が話し始めたら、ローカルの再生と未再生の queue を先に捨て、同じ session へ `session.instructions.append` で停止を指示します。停止指示の ACK を、再生が止まった証明には使いません。 |
| 議事録（`minutes`） | SDK の `OpenAIRealtimeWS` の transcription intent と `gpt-live-transcribe` で文字起こしだけを行い、音声は返しません。 |
| 利用量と上限 | Live の利用秒は累積値で置き換えて記録し、1 接続・1 日・累計の上限を持ちます。既定の方式では人の入力が 120 秒（既定）なければ Live だけを閉じ、Bot はその VC に残ります。 |
| 原音の保存 | 既定では保存しません。`archive` の接続設定と `voice.storeAudio: true` を明示したときだけ、最大 60 秒の区切りで[保存接続](../runtime/discord-template/docs/ARCHIVE-RUNTIME.md)へ渡します。900 秒の区間を返す機能はありません。 |

## #71 の設計との違いと後継の Issue

#71 の文書は、別の runtime を前提に書かれていました。Node runtime と違う点は Node を正とし、Node に無い考え方は後継の Issue で扱います。

| #71 の記述 | main の Node runtime | 扱い |
|---|---|---|
| 旧 Realtime の protocol ではなく、古い SDK は Realtime に fallback しない | 会話（`assist`）は Live API。議事録（`minutes`）の文字起こしだけは SDK の `OpenAIRealtimeWS`（transcription intent、`gpt-live-transcribe`）を使う | 「会話を別の protocol で代用しない」と書き直した |
| 返答ごとに新しい reply session を開く | 同じ session を複数ターン使い、返答は `session.commentary.append` | Node を正とする。古い返答の音声は、出力の世代と再生前の再確認で止める |
| 静かな進み具合は `session.thinking.append` で伝える | `session.thinking.append` は送らない。進み具合と成果は DM とテキストで伝える | 声で静かに伝える方法は [#144](https://github.com/Kotodama-Project/Kotodama-project/issues/144) |
| 挨拶も相槌もしない | 既定（`naturalConversation: false`）に当たる。`true` は明示的に選ぶ自然会話で、挨拶にも応じる | 両方を書いた |
| 任意の 900 秒の区間 | 無い。原音の保存の区切りは最大 60 秒 | 15 分の区間を返す機能は [#148](https://github.com/Kotodama-Project/Kotodama-project/issues/148) |
| `RoomHub`（部屋ごとの作業場と worker の結び付け） | 無い。作業場（`worker.workspace`）はインストールごとに一つ | [#143](https://github.com/Kotodama-Project/Kotodama-project/issues/143) |
| `BotLeases`（複数の VC の同時運用と Bot pool） | 無い。1 インストール = 1 Bot = 固定の 1 VC | [#142](https://github.com/Kotodama-Project/Kotodama-project/issues/142) |
| GrillU を一般化した Interaction Policy | 呼びかけ中心。analyzer が意図を整理し、足りない依頼は候補に残す | [#145](https://github.com/Kotodama-Project/Kotodama-project/issues/145) |
| `code.inspect`・`code.edit`・`code.test` を所有者の許可の範囲で自動実行 | `worker.actions`（`research`・`summarize`・`write_file`・`develop`）の設定と、Linux の固定 Docker image での検証 | 声で始まった仕事に自動で許す操作の種類は [#146](https://github.com/Kotodama-Project/Kotodama-project/issues/146) |
| SQLite の重複実行の防止と、結果の分からない操作の保留 | 再起動時は待ち（queued）を一時停止（paused）、実行中（running）を状態確認中（uncertain）として保持し、自動で再実行しない | Node の仕組みを正とする |
| Slack・Teams | 無い | [#70](https://github.com/Kotodama-Project/Kotodama-project/issues/70) |
| 移行の受入 gate（下の節） | 未受入 | 実音声の受入手順は [#154](https://github.com/Kotodama-Project/Kotodama-project/issues/154) |

## 守る境界

- **データ**: `store: false` を設定していますが、これは Zero Data Retention の主張ではなく、provider のデータ方針の確認の代わりにもなりません。Live で処理するには、音声を OpenAI へ送ることへの同意が必要です。同意がないのに、黙ってクラウド処理を有効にしません。
- **Live に渡す文脈**: `session.commentary.append` や `session.instructions.append` で渡す内容はモデルから見えます。secret を入れません。
- **話者と権限**: 混ざった音声を直近の話者のものとせず、モデルが推測した名前や声の似かたを権限に使いません。分類器の確信度も権限ではありません。
- **実行と発話は別**: Live の委譲イベント（delegation）は ID と時刻を運ぶだけで、依頼の本文や実行の許可ではありません。文字起こしの断片、モデルが作った ID、委譲だけでは tool を動かしません。
- **Discord**: 正規の Bot だけを使い、self-bot や暗号化（DAVE）の回避はしません。Node runtime は `@discordjs/voice` と DAVE 用の `@snazzah/davey` を使います。一つの Bot は一つのサーバーで一度に一つの VC にしか接続できないため、複数の VC には正規に用意した複数の Bot が必要です（[#142](https://github.com/Kotodama-Project/Kotodama-project/issues/142)）。
- **PC・VM・container**: API は PC へのアクセスや VM を自動では与えません。会話の入力に、一般の shell、Docker socket、Proxmox の管理者 credential、home directory 全体を渡しません。作業場のディレクトリは VM・container・sandbox ではありません。Node の書込みの仕事は、実装を Codex の sandbox、検証を network なしの固定 Docker image で行います（[構成](../runtime/discord-template/docs/ARCHITECTURE.md)）。
- **VC の owner は一つ**: 同じ VC を二つの runtime に持たせません。別の agent 実行器とつなぐ場合も、VC の owner は一つにします（[runtime の README](../runtime/discord-template/README.md)）。

## 移行の受入 gate（未受入）

#71 の gate を、Node runtime だけを使う前提で書き直しました。どれもまだ受け入れていません。実音声での手順と記録は [#154](https://github.com/Kotodama-Project/Kotodama-project/issues/154) で用意します。

1. **一つの owner**: 一つの VC の受信と仕事の実行の owner は `runtime/discord-template` だけです。既存の Source・Intent・Task・証拠の契約を保ちます。
2. **SDK と費用**: 固定した版の公式 SDK で、開始と終了の応答、上限付きの PCM queue、接続の切断、利用秒の累積、無入力と最大時間の上限を実 API で確かめます。遅延と費用は推測せず実測します。
3. **Discord の実 VC**: DAVE に対応した受信と送信を、識別された 2 人、割り込みと発話の重なり、再参加で確かめます。許可の外では再生がゼロであることを確かめます。同じサーバーの二つの VC の同時運用は [#142](https://github.com/Kotodama-Project/Kotodama-project/issues/142) の後です。
4. **声から成果まで**: 話した依頼が、話者の分かる確定した意図、隔離された変更、試験、PR や receipt まで、打ち直しなしで進むことを示します。雑談、引用された指示、未知の話者、話者の付け替え、同意や許可の取消、重複の配送、時間切れ、訂正の否定の対照も示します。
5. **実行の隔離**: 実行器の読み書きと外部通信の範囲、部屋ごとの分離、実際の子プロセスの停止、状態確認中の仕事の照合、再起動後の復旧を確かめます。PC へのアクセスを許すなら範囲を明示し、音声から権限を推測しません。
6. **戻せること**: 変更は Node runtime の中で行い、戻すときも Node runtime の中で revert します。別の runtime へは切り替えません。戻す前に、実行中と状態確認中の仕事を照合します。ローカル ASR の経路は選択肢として残し、15 分の区間を返す機能は [#148](https://github.com/Kotodama-Project/Kotodama-project/issues/148) で扱います。
7. **Slack・Teams**: それぞれの接続の gate を通るまで対応を宣伝しません。Slack の Calls API は外部の通話を表すもので、Huddles の生の音声を取れる証拠ではありません。Teams のリアルタイム media には、それぞれの Graph 権限、配備、動作環境の条件があります。三つが同じ media API を持つとは扱いません（[#70](https://github.com/Kotodama-Project/Kotodama-project/issues/70)）。

## 根拠と検証

上の表の根拠は次のファイルです。

- 実装: [`src/voice-providers.mjs`](../runtime/discord-template/src/voice-providers.mjs)（`assist` と `minutes` の接続、出力の許可、割り込み）、[`src/voice.mjs`](../runtime/discord-template/src/voice.mjs)（話者ごとの受信、同意、再生）、[`src/voice-control.mjs`](../runtime/discord-template/src/voice-control.mjs)（固定 VC の入退室）、[`src/config.mjs`](../runtime/discord-template/src/config.mjs)（設定と既定値）
- 試験: [`tests/voice.test.mjs`](../runtime/discord-template/tests/voice.test.mjs)、[`tests/voice-room.test.mjs`](../runtime/discord-template/tests/voice-room.test.mjs)、[`tests/voice-control.test.mjs`](../runtime/discord-template/tests/voice-control.test.mjs)、[`tests/wake.test.mjs`](../runtime/discord-template/tests/wake.test.mjs)、[`tests/speech-admission.test.mjs`](../runtime/discord-template/tests/speech-admission.test.mjs)

手元では `runtime/discord-template` で次を実行します。GitHub CI も Linux と Windows で同じ試験を実行します。

```sh
pnpm install --frozen-lockfile --ignore-scripts
pnpm test
pnpm check
```

これらは SDK と Discord を模した合成の試験です。実音声、Discord の token、OpenAI の key は使いません。合成の試験の PASS は、実 VC での受入ではありません。実 VC の確認状況は[確認状況](../runtime/discord-template/docs/ACCEPTANCE.md)にあります。

#71 にあった `runtime/live/*`、`tests/test_live_candidate.py`、`.github/workflows/live-candidate.yml` は取り込んでいません。その試験の結果も、この runtime の証拠には使いません。

## 一次資料（2026-09-12 に #71 で確認）

以下は #71 の作成時に確認した資料です。この取り込みでは内容を確かめ直していません。Node runtime が実装で参照している資料は [runtime の README](../runtime/discord-template/README.md) にあります。

- OpenAI の発表（表示された公開日 2026-09-10）: https://openai.com/index/introducing-gpt-live-1-in-the-api/
- Live quickstart: https://developers.openai.com/api/docs/guides/live
- WebSocket・PCM の protocol: https://developers.openai.com/api/docs/guides/voice-websockets
- client delegation: https://developers.openai.com/api/docs/guides/live-delegation
- 文字起こし・session・利用量の意味: https://developers.openai.com/api/docs/guides/live-conversations
- Discord の音声接続と DAVE: https://docs.discord.com/developers/topics/voice-connections
- Discord の暗号化の展開: https://discord.com/blog/every-voice-and-video-call-on-discord-is-now-end-to-end-encrypted
- discord.js の接続数: https://discordjs.guide/voice/voice-connections
- Slack Calls: https://docs.slack.dev/apis/web-api/using-the-calls-api/
- Teams の media の要件: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots

## English summary

Kotodama adopts OpenAI GPT-Live 1 / Live API as its primary cloud voice provider (decided 2026-09-12). Since the owner decision of 2026-09-24 (#30), the only voice runtime is the Node runtime in `runtime/discord-template`; the separate Python runtime of #71 and the workspace base of #69 are not taken in. This page is the Japanese rewrite of the #71 policy document, corrected to match the Node runtime: one Live session per speaker is reused across turns and receives verified results via `session.commentary.append`, `minutes` transcribes through `OpenAIRealtimeWS` with `gpt-live-transcribe`, and ideas the Node runtime lacks are tracked in #142 to #146, #148, #154, and #70. The status stays candidate-only and `NO_GO_UNPUBLISHED`; synthetic tests are not real voice-channel acceptance.
