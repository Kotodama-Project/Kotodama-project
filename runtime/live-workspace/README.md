# Live voice workspaces

## 採用する方向と今回の範囲

音声フロントエンドの標準接続先を **OpenAI Live API / `gpt-live-1`** とする。
会話を止めずに開発処理を既存Work ownerへ渡し、チャンネルごとに担当の作業環境を持つ。
2026-09-12の依頼を実装方針として反映したソース候補であり、merge・本番切替・
provider認証・課金開始・実行権限の付与を済ませたという意味ではない。

**今回の状態: 共通runtimeとOpenAI SDK接続アダプターは実装、オフライン回帰試験済み。
実Discord/Slack/Teams、既存のcanonical Source/Intent/Work owner、本人PCのagentや
VM/container provisionerへの接続は未完。音声から実PRまでの本番E2Eは未検証。**
`development_to_pr`という操作名やadapterの存在だけで自動開発を利用可能と表示しない。

既存の[Codex requirements bridge](../codex-task-bridge/README.md)の
`DRAFT_REQUIREMENTS` / read-only / tool-disabled grantは変更しない。
既存Workの正本、KB、agent registry、schedulerをここに複製しない。
外部アダプターの別タスクは [Issue #68](https://github.com/Kotodama-Project/Kotodama-project/issues/68)。

## 利用経路

```text
Discord / Slack / Teams / Kotodama Web の認証済み・同意済み入口 [未接続]
  -> provider + tenant/guild + channel + optional meeting の分離キー
  -> ChannelWorkspaceHub -> チャンネル担当workspace + OpenAI Live session
  -> session.delegation.created + 観測されたtranscript断片
  -> 既存Source/Intent owner.resolve [必須・実owner未接続]
  -> 既存Work owner.authorize / admit / dispatch [必須・実owner未接続]
  -> 許可済みの本人PC / container / VMで変更・検査・PR候補作成
  -> 元のチャンネルへstatus / 必要時の発話 -> 独立検証と受入
```

GrillUを固定質問フォームとして追加するのではなく、依頼の意図、訂正、制約、
受入条件を確定する汎用Intent層に接続する。必要な条件が既に揃う依頼では
不要な質問を追加しない。曖昧な引用、雑談、話者不明、未確定の文字起こしは
開発命令にしない。`resolve()`は未確定時に`null`を返せる。

通常は静かに聴取する。認証済みのaddressed/wake/操作イベントを持つ入口が
`allowReply(principal)`を呼んだ間だけ、primary WebSocketの音声を再生する。
これは音声モデルへの指示だけでなく出力側でも制限する。作業statusは通常
`session.thinking.append`で通知し、発話許可期間だけ`session.commentary.append`を使う。

## ファイル

| ファイル | 実装 |
|---|---|
| `core.mjs` | channel identity、同時joinの集約、期限、Live状態機械、PCM入出力、出力発話制御、Source/Work入力binding、再送抑止、非同期handoff |
| `openai.mjs` | 公式`LiveWS`用の接続factoryと`client.live.create`によるWebRTC signaling helper |
| `discord-slots.mjs` | 同一guildで同一botを別VCへ奪い合わないtransport枠、切断未確認時の枠保持 |
| `live-workspace.test.mjs` | 合成provider/authorityによる正常系・拒否系と、実ファイル生成/Node構文検査の限定試験 |
| `../../tests/test_live_workspace_runtime.py` | 既存Python unittest discoveryからNode試験を実行。Node欠落を黙ってskipしない |

## 既存ownerの接続契約

このmoduleは内部API。外部HTTP/RPC、ブラウザ、モデルにそのまま公開しない。
`principal`をリクエスト本文から信用してはならない。`true`を返す仮のauthorizerを
本番のdefaultにする実装はない。

- `authorize({scope, principal, operation, workspace?, source?, admission?, audience?})`:
  実際のprovider本人性、tenant/channel ACL、同意と保持の版、source読取権限、
  現在のWork/Capability Grantを評価し、許可時だけ`true`を返す。
- `ensureWorkspace({scope, principal})`:
  既存ownerがdurable/idempotentに確保し、`{roomKey, ref, kind, expiresAt}`を返す。
  `kind`は`paired_host` / `container` / `vm`。`expiresAt`はUnix時刻ミリ秒で最大30分。
  `ref`は私的な実行先の参照であり、ユーザー指定の任意path/commandではない。
- `intentOwner.resolve({roomKey, sessionId, delegationId, offsetMs, observed,
  transcriptComplete:false, signal})`:
  観測断片を既存の話者別Source Evidenceへ照合して、`sourceRef`, `sourceDigest`,
  `revision`, `principal`, `objective`, `acceptance[]`, `sourceFinal:true`,
  `addressed:true`を返す。これらの真偽値はモデルの自己申告を信用するためのものではない。
  Source/Work ownerが実記録から本人・確定・宛先・訂正を検証する必要がある。
- `admit({requestKey, inputDigest, scope, principal, workspace, source,
  operation:'development_to_pr', signal})`:
  実行前に既存の正本へ記録し、同一requestKeyの変更内容が違えば拒否する。
  戻り値は`requestKey`, `roomKey`, `principal`, `sourceDigest`, `inputDigest`,
  `workspaceRef`, `executorKind`, `operation`, `expiresAt`, `workRef`, `revision`,
  `grantRef`, `contextDigest`。この候補はbindingと期限を照合するが、署名や実権限を
  文字列の存在だけで検証したことにはしない。
- `dispatch({admission, source, signal})`:
  既存workerへidempotentに接続する。直前のsource/grant/contextを再確認し、
  共有resourceのfencing、予算、scope、取消を実workerにも強制する。
  戻り値の`requestKey`, `workRef`, `revision`を照合する。受理するstateは
  `submitted`, `needs_review`, `failed`, `cancelled`, `interrupted`。
  producerの`success`から独立検証やTask完了を生成しない。
- `reconcileWorkspace({scope, principal})`:
  失敗・終了したprovider/workspaceの状態を実際に確認する。
  `hub.reopen()`はこの確認なしに曖昧な実行を再開しない。

requestKeyはLive session IDではなく、チャンネル、principal、canonical sourceRef、
source revision、操作から作る。Liveの再接続や別delegation IDで同じ依頼が来ても、
既存ownerのdurable admission/dispatchが同じ仕事に戻す。メモリのMapだけによる
exactly-onceや電源断耐性は主張しない。source訂正は既存ownerの版更新・取消経路で扱う。

本人PCのペアリングは、許可した作業フォルダと操作範囲へ限定する。音声APIが
PC権限を直接付与するわけではなく、ローカルagent/connectorが必要。
コード編集・テスト・PR作成を事前に許可できるが、mainへのmerge、本番配備、
secret/ACL変更、破壊的操作、課金増加まで同じgrantへ混ぜない。

## OpenAI SDKの接続

既存hostのreview済み・hash-locked依存関係で`openai`と`ws`を用意し、公式
`OpenAI`と`LiveWS`をfactoryへ渡す。今回の変更は依存の自動インストール、
秘密の作成、host環境の変更を行わない。

```javascript
import OpenAI from 'openai';
import { LiveWS } from 'openai/resources/live/ws';
import { ChannelWorkspaceHub } from './core.mjs';
import { openAILiveConnector } from './openai.mjs';

// workOwner / intentOwner / mediaSink are authenticated host adapters, not model tools.
export function mountLiveVoice({ workOwner, intentOwner, mediaSink }) {
  return new ChannelWorkspaceHub({
    owner: workOwner,
    intentOwner,
    connect: openAILiveConnector({ OpenAI, LiveWS, apiKey: process.env.OPENAI_API_KEY }),
    onAudio: (roomKey, pcm) => mediaSink(roomKey, pcm),
  });
}
```

API keyはサーバー側だけ。接続先は`https://api.openai.com/v1`に固定し、SDKの
自動再接続・自動retryを使って依頼を再実行しない。primary WSでは最初に
`session.start`を送り、`session.started`まで音声入力しない。

**重要な実仕様:** `session.delegation.created`はID/target等のmetadataで、依頼本文ではない。
`session.input_transcript.delta`には発話完了/doneイベントがない。断片を受信順に保持し、
過去の観測範囲をIntent ownerへ渡すが、それを完成した依頼とは扱わない。
`session.output_audio.delta`はprimary WSではevent_idなし。形式はmono PCM16LE、
16 kHzまたは24 kHzで、DiscordのOpusをそのままappendしない。

`createWebRTCSession()`は認証済みサーバー用のsignaling helperだけ。
JSONの`client.live.create({session, transport:{type:'webrtc', sdp}})`を使い、
WebRTCに`audio.format`を付けない。ブラウザへprovider keyやWork権限を渡さない。
**WebRTC画面、sidebandのWork接続、ブラウザの再生制御は今回未実装。**
このhelperだけで日常利用可能な会議や開発入口が完成したとは表示しない。

## 音声・保持・障害

media gateway側でOpus decode、resample、時刻同期を行う。複数人の音声を
単に交互にappendして時間を伸ばしてはならない。`appendPCM()`は単独track、
`appendMix(principals, pcm)`は時刻を合わせたmix用で、含めた全trackの本人・
同意・現在権限を検査する。Live transcriptから本人性を逆算しない。
実mix、ASRの話者対応、DAVE、echo/overlap処理は外部media adapterの受入対象。

moduleは音声をディスクへ保存しない。transcript観測はメモリで最大64 KiB、
イベントは20,000件、delegationは128件、同時handoffは4件、Hub既定8室。
上限時に黙って切り捨てた文脈から実行せず停止する。再生queueとSDK送信bufferも
制限し、遅い認可処理による際限ない音声滞留を避ける。
`store:false`はLive session保存の指定であり、providerの全ての保持がゼロになる
保証ではない。既存の同意・分類・保持・削除方針を別途適用する。

失効、退室、transport切断、provider errorでは音声を閉じ、AbortSignalをworkerへ渡す。
grantの短い期限もdispatchのAbortSignalへ束縛する。**signal送信やsocket.closeは、
実worker停止、VM停止、費用停止のreceiptではない。** 外部状態はownerが確認する。
新規参加者へ過去の会話内容を開示してよいかはownerが判定し、認可変更時には
接続側からもroomを閉じる。旧録音やprivateな出力をpublic repositoryへ入れない。

Discordのtransport枠は1 bot / guild / 1 VCを守る。複数VCの同時利用には
適切な数の認可済みbotか、自前WebRTC roomへの導線が必要。`group`名の変更で
制約を回避したことにしない。切断不明の枠は再利用しない。

## 検証と切替

```text
node --test runtime/live-workspace/live-workspace.test.mjs
python -B -m unittest discover -s tests -p test_live_workspace_runtime.py -v
```

全provider、本人性、同意、Work ownerはテスト内の合成fixture。
1ケースだけ一時ディレクトリに実ファイルを書き、実Node構文検査を実行し、
Hub再起動後も保存receiptから再生成を抑止する。これはモデルによる開発、
実canonical owner、分散exactly-once、本番Task完了の証拠ではない。

本番切替前に、同一経路で「実VC発話→実Source→実Work→実workerの変更・
テスト→PR→元の会話への応答」を確認する。別途、二人同時発話、権限取消、
再起動、bot容量不足、grant失効、訂正、artifact ACL、課金上限を確認する。
現実の配備receiptなしに既存の`NO_GO_UNPUBLISHED`を変更しない。

rollbackは呼出側でこのadapterを無効化し、voice transportを閉じ、既存ownerで
未確定work/leaseをreconcileした上でこの変更をrevertする。既存brief bridgeを
残し、Work記録、作業フォルダ、source、VMを都合よく削除しない。

## 一次資料（2026-09-12照合）

- [OpenAI Live guide](https://developers.openai.com/api/docs/guides/live)
- [OpenAI公式SDK: Live型とprotocol](https://github.com/openai/openai-node/blob/3c4e4d26e3aebd422bc73787e4fcbd1773607785/src/resources/live/live.ts)
- [公式LiveWS](https://github.com/openai/openai-node/blob/3c4e4d26e3aebd422bc73787e4fcbd1773607785/src/resources/live/ws.ts)
- [SDK eventとWS endpoint](https://github.com/openai/openai-node/blob/3c4e4d26e3aebd422bc73787e4fcbd1773607785/src/resources/live/internal-base.ts)
- [SDKのplatformSocket](https://github.com/openai/openai-node/blob/3c4e4d26e3aebd422bc73787e4fcbd1773607785/src/internal/ws-adapter-node.ts)
- [Discord接続制約](https://discordjs.guide/voice/voice-connections)
- [Slack Calls API](https://docs.slack.dev/apis/web-api/using-the-calls-api/)
- [Teams application-hosted media](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots)

公式の公開時刻はこの変更の受入根拠にしない。接続schemaは上記SDK commitへ固定して照合した。
