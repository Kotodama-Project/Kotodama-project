# 実音声の受入手順と記録

この手順は [Issue #154](https://github.com/Kotodama-Project/Kotodama-project/issues/154) の準備物です。
**未実施の受入を完了にしません。** 診断結果は local observation / candidate-only で、
`NO_GO_UNPUBLISHED` のままです。既存の [確認状況](ACCEPTANCE.md) を上書きする証拠ではありません。

[普段の使い方](../README.md)、[運用](OPERATIONS.md)、[設定と人の分担](DISCORD-SETUP.md)、
[構成](ARCHITECTURE.md) を前提にします。製品としての受入は
[製品方向](../../../docs/PRODUCT-DIRECTION.md)、
[Voice の要件](../../../docs/OVERVIEW.md)、
[音声の採用方針](../../../docs/GPT-LIVE-ADOPTION.md) に戻します。

## 準備と中止

既存の専用インストールと許可を使い、別の Bot・Task owner を作りません。
実施者が説明・同意、参加対象、現在の閲覧範囲、音声の利用枠と残量を確認します。
有効なログイン・同意を試験ごとに求め直しません。範囲を超える参加者・作業・費用が必要なら
`BLOCKED` とし、権限や上限を自動で広げません。CLI の診断自体は credential 不要です。

実施前に runtime の commit、OS、ASR の種類、モード、開始条件、出力設定を控えます。
commit の申告と実行中 bytes の一致は別です。
[Issue #157](https://github.com/Kotodama-Project/Kotodama-project/issues/157) の読み戻しが
未実施なら binding は `UNVERIFIED` のままにします。テスト用の合成話題だけを使い、
原音・本文・参加者名・Discord ID・host・path・token は公開しません。

試験前に、操作者が選んだ実行中インストールの設定 snapshot を private な場所で読み戻し、
対象 runtime の設定と一致することを確認します。公開記録には内容・path・識別子を載せず、
確認時刻・適合状態（CONFIRMED / UNVERIFIED）と下の数値だけを残します。
読み戻せない、設定が変わった、実行中の適用が確認できない場合は開始せず `BLOCKED` とします。

B は連続区間の予定秒数 `caseDurationSeconds` を 1800 以上に決めます。
各入力・回答接続の `maxSessionSeconds` は予定区間を覆い、終了時刻の境界にも余裕が必要です。
既定値 1200 秒ではこのケースは `BLOCKED` です。日次・累計の**残量**も各々予定区間以上かを
確認し、さらに同時入力と AI 回答接続の予約秒数を合算した予定消費を覆う必要があります。
日次上限 0 は利用可能な無制限枠ではありません。累計上限が未設定なら `NOT_CONFIGURED` と
記録し、設定済みの場合は既存 usage から残量を確認します。診断 CLI は累積 usage を集計せず、
この適合確認を代行しません。日付変更を利用して不足する許可や累計枠を補いません。

上限・残量が不足する場合は `BLOCKED` と記録し、上限を自動で増やしません。
計画された session rotation や手動の再開は別の観測です。連続区間の終了を隠して
B の連続応答 `PASS` へ読み替えません。試験中の設定変更・枠不足では中止し、
変更前後の観測を一つの連続した受入へ合算しません。

別の通話・Task が同じインストールで動く時間を避け、各ケースの開始・終了 UTC を記録します。
別の活動が混ざった場合、下記 CLI の installation 全体の件数を特定の会話へ帰属させません。
外部の Task owner を選んでいる場合、Task の確認はその owner で行います。
ローカル `task.created` が 0 件でも「仕事が作られなかった」の証拠にはなりません。

想定外の発話・処理対象外の音声・権限の不一致・意図しない Task・残高不足・音声の暴走で中止します。
`/kotodama voice stop_speech` は発話だけ、`voice pause` は音声処理、`voice leave` は退出、
`/kotodama stop` は指定した仕事の取消です。対象を区別し、他のプロセスや仕事を止めません。
中止したケースは `FAIL` または `BLOCKED`、実行していないケースは `NOT_RUN` と記録します。

## 実施順

最初に短い連続応答を確認し、失敗したら長時間試験へ進みません。
次に二人で 30 分、割り込みと切断復帰、最後に三人の帰属とモードの受入を行います。
下表の人数は人間の人数で、Bot を含みません。

| ID / 対象 | 条件と手順 | 確認するもの・合格条件 |
|---|---|---|
| A / 継続応答 | 一人。`transcriptSource=local`、`conversationStart=wake`、`naturalConversation=false`、`assist`。呼びかけ付きの一問に続き、返答完了後 2〜3 秒で呼びかけなしの質問を三回。ヘッドホンあり・なしを別ケースにし、間は現在の idle 時間を超えて待つ | 各ケース 4 回中 4 回の返答を実聴し、途中で会話が失われない。`voice.local_turn` は入力側の補助であり、返答数には使わない。失敗時は #147 へ本文なしの結果を返す |
| B / 二人・30 分 | 二つの本人アカウントで 30 分以上継続。交互の発話、短い続き、長めの間、`assist` / `minutes` の切替を入れる。予定する質問回数と連続区間の秒数を実施前に記録し、上記の設定 snapshot・session 上限・日次/累計残量の適合を確認。不足は BLOCKED | 実時間 1800 秒以上、予定した返答の実聴、minutes では音声回答しないこと、勝手な終了・再接続ループ・意図しない Task がないこと。中断時間と実聴できなかった回数も残す |
| C / 割り込みと出力 | 二人。既存の設定値（例: prefill 120ms、queue 上限 500ms）を記録する。Bot 発話中に本人が話し始める試験を複数回行い、割り込み開始と最後に聞こえた Bot 音声を同じ計測時計で観測 | 試験前に合意した停止時間の目標と、各回の実測値・計測の分解能を比較する。目標や計測がなければ `NOT_MEASURED`。provider の停止 ACK・イベント間隔を実聴停止時間にしない。途切れと体感遅延は別の観測にする |
| D / 切断・再参加・停止 | 二人。まず許可済みの通常接続で会話する。操作者がこの Bot の接続だけを一度切断し、設定どおり復帰するか確認。その後 `voice pause`、再起動後の停止保持、明示的 `voice resume` を別ケースで確認 | 再参加後も続きの入力・回答を確認。停止中に新たな音声処理・再生が始まらず、二重接続しない。復帰までの秒数は実測する。既存 Task を自動で再実行しないことは Task owner で確認する（PB-G1） |
| E / 三人の帰属 | 三つの本人アカウントで順番に発話し、二人の重なりも確認する。共有マイクなど帰属不明の入力は、準備済みの `unattributedUsers` 設定で別の否定ケースにする | private な出典の入力トラック・話者・時刻を本人が照合し、取り違えの件数だけを公開する。帰属不明の入力から実行・音声回答を開始しない。別人による確認を記録する（PB-G5） |
| F / 一つの会話の体験 | まず仕事の依頼を含まない雑談だけの区間を設ける。次に出典付き catch-up、既存許可内の限定作業、訂正、成果確認を順に試す | 雑談区間では正本の Task が増えず、catch-up の出典へ戻れ、限定作業の検証結果が返る。訂正は同じ Task ID / revision と履歴へ戻る。native UI・自由文・音声の未接続経路は `BLOCKED_DEPENDENCY` で残す（PB-G10、#151・#152） |

A の補足と既存修正の範囲は
[Issue #147](https://github.com/Kotodama-Project/Kotodama-project/issues/147) にあります。
C の計測は同意済みの方法で本人が行い、原音を公開しません。
現行イベントには再生の実聴終了を対応付けた計測がないため、下記ツールでは測れません。
120ms / 500ms は設定値であり、それを記録しただけでは実測の受入になりません。

15 分 rotation（#148 / PB-G2）、削除 receipt（#149 / PB-G3）、実行中 bytes の一致
（#157 / PB-G4）、二つの VC と発話から PR までの隔離経路はそれぞれ別の受入です。
この手順の実施で代用しません。未接続・未採用の機能は `BLOCKED_DEPENDENCY` とし、
一つの VC で動いたことを二つの VC の成功として記録しません。

## 本文を出さないローカル診断

テンプレートのディレクトリで Node 24 を使います。追加の依存、設定ファイル、API key、
Discord 接続は不要です。`DB_FILE` は既存の private な `kotodama.sqlite` を指します。
下記の日付と commit は書式を示す合成の例であり、受入証拠ではありません。

```sh
node bin/voice-diagnostics.mjs --help
node bin/voice-diagnostics.mjs --db DB_FILE --since 2026-01-01T00:00:00.000Z --until 2026-01-01T00:30:00.000Z --revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

PowerShell でも同じ一行コマンドです。実施した UTC の `[since, until)` と 40 桁の
commit に置き換えます。DB や `debug.log` を Git / Issue にアップロードしないでください。
稼働中 SQLite をファイル一個だけコピーすると WAL の記録を失う可能性があるため、
稼働中 DB をそのまま読み取り専用で読むか、運用者の整合した backup を使います。
ツールは DB の表・Task・設定を書き換えません。SQLite の WAL / 共有メモリの扱いは
エンジンに従うため、稼働中ディレクトリ全体の bytes 不変を主張するものではありません。

出力は固定した項目だけの JSON です。会話・ID・session 名・理由の自由文・path を出しません。
`voice.consent`、source / Task の本文、`debug.log` は集計しません。
未知のイベントと未知の本文項目は出力せず、累積 `voice.usage_snapshot` を足し合わせません。

| 出力 | 読み方 |
|---|---|
| `event_counts` | 固定した六つの voice イベントとローカル `task.created` の件数。入力数・イベント数であり、返答を聞けた回数や全 Task owner の件数ではない |
| `local_turn_flags` | 呼びかけ・eligible・Live 有効・会話継続の各 boolean の true / false / unknown 件数。欠損や型違いを false に置き換えない |
| `local_asr_ms` | `audioMs` は入力音声長、`queueMs` は ASR 待ち、`elapsedMs` は ASR 呼出し時間（失敗も含む）。samples、invalid、min、p50、p95、max。nearest-rank 集計。聞こえるまでの応答時間ではない |
| `status` | `OBSERVED` は集計できたという意味だけ。`NO_MATCHING_EVENTS` は対応する記録なし。`INCOMPLETE_FIELDS` は欠損・型違い・不正本文あり。いずれも受入の PASS ではない |
| `unmeasured` | 実聴返答数、割り込み停止時間、出力 queue、参加人数、モード受入は常に null。人の計測と混同しない |
| `declared_revision` | 操作者の申告。`revision_verified=false` で、稼働中 bytes や過去イベントの版を証明しない |

最大 24 時間・選択イベント 10000 件、DB 本体と `-wal`・`-shm`・`-journal` の
合計 256MiB、本文の読取は必要な二種類だけで一件 8KiB までです。関連ファイルも通常
ファイルだけを許可し、接続前・読取 snapshot 取得後・出力前に合計容量を再確認します。件数上限では `REFUSED` と終了コード 1 を返し、切り捨てた成功を出しません。
window を短くして再集計します。本文上限・欠損は `INCOMPLETE_FIELDS` として残します。
時間窓の検索は索引のない既存 DB を走査し得ます。検査の間に writer が増やす容量や
大きな運用 DB での実行時間を厳密に封じるものではありません。容量上限で拒否された
場合は、運用者が整合した小さな backup を準備します。WAL だけを削除して縮めません。
ファイルの選択・OS の読取権限は操作者の責任で、別ユーザー向けのアクセス制御 API ではありません。
診断失敗は固定コードだけを返します。集計のために runtime の Store を起動しません。

## 公開用の記録様式

下の様式を新しい記録へコピーし、実施した欄だけ埋めます。未測定値を 0 にせず、
本文・名前・ID を含まない数値と状態を記載します。問題の説明は公開前に人が確認します。
`claims` を true に直して受入を表すのではなく、人の観測を別欄に記録してください。

```markdown
### 実音声確認（#154、未実施は NOT_RUN）
- 実施日（UTC）: NOT_RUN
- runtime の commit（40 桁）: NOT_RUN
- 稼働中 bytes の読み戻し: UNVERIFIED
- OS: NOT_RUN（linux / windows / macos）
- transcriptSource / naturalConversation / 開始条件 / モード: NOT_RUN
- ヘッドホン: NOT_RUN（あり / なし）
- 設定 snapshot の確認時刻（UTC）/ 実行中設定との適合: NOT_RUN / UNVERIFIED
- 連続区間の予定秒数 caseDurationSeconds: NOT_RUN（B は 1800 以上）
- maxSessionSeconds / 終了境界の余裕秒数: NOT_RUN / NOT_RUN
- 日次上限 / 使用済み / 残量 / 予定予約秒数: NOT_RUN / NOT_RUN / NOT_RUN / NOT_RUN
- 累計上限 / 使用済み / 残量: NOT_RUN / NOT_RUN / NOT_RUN（上限未設定は NOT_CONFIGURED）
- 設定・枠の適合: UNVERIFIED（CONFIRMED / BLOCKED。不足項目だけ記録）
- 計画された rotation・再開: NOT_RUN（連続応答 PASS の代用にしない）
- prefill / queue 上限 / idle の設定値: NOT_RUN
- 実時間（秒）/ 人数: NOT_MEASURED
- 他の通話・仕事の混在: UNKNOWN
- 正本の Task owner: UNKNOWN（local / remote。host や ID は書かない）

| ケース | 状態（NOT_RUN / PASS / FAIL / BLOCKED） | 公開可能な観測 |
|---|---|---|
| A 連続応答 | NOT_RUN | 実聴回数 / 予定回数: NOT_MEASURED |
| B 二人30分 | NOT_RUN | 実時間・途切れ・返答漏れ: NOT_MEASURED |
| C 割り込み | NOT_RUN | 事前の目標ms・各回の実測ms・分解能ms: NOT_MEASURED |
| D 切断復帰・停止保持 | NOT_RUN | 復帰秒・停止中の再開件数・二重接続件数: NOT_MEASURED |
| E 三人・帰属不明 | NOT_RUN | 取り違え件数・帰属不明からの実行件数: NOT_MEASURED |
| F 雑談→仕事→訂正 | NOT_RUN | 雑談中の正本Task増分・出典照合・同じ履歴: NOT_MEASURED |
| 未接続の経路 | BLOCKED | 対応する Issue 番号のみ |

- 機械集計: 未実行（診断 JSON を確認してから添付。DB は添付しない）
- 別の人による観測確認: NOT_RUN（名前は書かない）
- 中止の理由・残る不具合: 未確認
- 受入した対象としなかった対象: なし / すべて未受入
- Public Beta: NO_GO_UNPUBLISHED
```

記録後は [Issue #154](https://github.com/Kotodama-Project/Kotodama-project/issues/154) へ返し、
必要な修正を #147 等へ分けます。[gate 追跡 #156](https://github.com/Kotodama-Project/Kotodama-project/issues/156)
と [確認状況](ACCEPTANCE.md) は、別の reviewer が根拠を確かめた範囲だけ後続 PR で更新します。
一回の実聴、local/CI の成功、診断 JSON の存在だけでは Public Beta や Final Human GO にしません。
