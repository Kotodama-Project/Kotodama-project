# 構成

任意の[VoicePool](VOICE-POOL.md)は、同じinstallationのhost lockの下でBotをroomへ予約します。
Sourceのguild/channelからVoiceRoomを選び、返答・操作・解析・同意を部屋へ束縛します。
追加Botはvoice接続だけに使い、既存のTask ownerとSource履歴を共有します。

[ChannelWorkspaceWorker](CHANNEL-WORKSPACES.md)は既存workerの前でchannelとTask Sourceを照合し、
利用期限・base/candidate checkpoint・実行中処理を管理します。Task ownerを増やさず、
書込みは従来のTask worktreeと固定Docker verifierへ渡します。directoryはsandboxではありません。

`interaction-policy.mjs`は一つのintentをexecute / candidate / ignoreへ分類します。
実行候補の全actionは既存のadmissionで現在のgrantを確認してからTaskへ進みます。
不明話者、非operator、引用等の非明示候補、雑談はTaskの権限になりません。
clarify_onceはanalyzerの質問候補を使い、[一度だけ確認する規則](INTERACTION-POLICY.md)で
現在の許可・経路・既存の確認を照合してから送ります。回答をHuman Decisionにしません。

Discordのテキスト・音声 → 出典と版 → 意図・ToDo → 明示依頼 → CLI実行器 → 検証済み成果。

`assist` は一回の呼びかけでGPT-Live会話を開き、その話者との複数ターンで同じWebSocketを使います。Lunaのbackend結果は同じセッションのcommentaryへ返し、回答ごとの音声セッションは作りません。`minutes` はVADと専用文字起こしを使い、音声を返しません。どちらも同じ意図抽出器とTask ownerを使います。

`voice.transcriptSource: "local"` ではDiscordの話者別PCMをローカルASRへ渡し、その確定した日本語テキストをSource Evidenceにします。呼びかけ前の発話は保存だけを行い、Live・Luna・Task実行を開始しません。呼びかけ時は確定テキストをLiveの開始履歴へ入れ、その後の音声は同じ話者のLiveセッションへ流します。Live側のtranscript deltaはUI補助に限り、Intentを確定しません。

単体構成はNode.jsとSQLiteで動きます。組織構成ではremote Task ownerを選びます。n8nは取込と呼出しを担当し、仕事の正本は持ちません。

参照した既存候補：Kotodama-project PR #69の部屋別契約、#71の発話制御、#59の文脈と入力の束縛、#67のCLI実行証拠。大きなPR stackやprivate runtimeのソースを丸ごとコピーせず、このテンプレートのコードを新規作成します。参照PRの未受入部分を配備済みと表示しません。

原音の永続保存は既定で行いません。文字起こしとその訂正、資料と仕事の履歴はインストール先のprivate data directoryに保持します。録音・外部処理への同意、閲覧範囲、モデルと費用上限を初回に設定し、停止・取消を実行時に照合します。

固定VCの自動入退室は、一つの直列化した音声制御が扱います。起動時、対象VCの入退室イベント、10秒間隔で人間の在室と現在の対象範囲を照合します。Botは人数に含めません。対象外の参加者がいる間は、新しい音声処理・再生を止めて退出します。手動停止の設定はSQLite内のVC別設定で保持し、仕事の台帳を増やしません。

接続待ちと復旧待ちは接続個体に結び付けます。停止・設定取消・終了後に遅い接続が復活したり、新しい接続を古い失敗処理が破棄したりしません。終了時の文字起こしは旧epochの出典として確定し、その出典から実行・音声回答を再開しません。

Discord再生はLive出力と別の世代・閲覧許可・source revisionに束縛します。利用者の発話開始、権限変更、mode変更、queue overflowではplayerと未再生PCMを先に破棄します。Liveには停止指示を送りますが、そのACKを再生停止の証明には使いません。音声会話終了はLiveセッションだけを閉じ、既に許可されたTaskは取り消しません。


## Capability lanes

音声とテキストは同じactionを使います。`worker.actions`が唯一の実行grantであり、
`src/capability-lanes.mjs`の固定写像は種類と既定を表すだけです。laneの設定や別台帳はありません。

| lane | action | A019 / A022との対応 | 既定と境界 |
|---|---|---|---|
| 読取・調査 | `research`、`summarize` | inspect / Read-only | 明示依頼と現在のgrantがあれば追加確認なし |
| 編集 | `write_file`、`develop` | reversible_change / Reversible write | 既定無効。明示grant後も隔離worktree・検証を経てneeds_reviewへ |
| 試験 | 単独actionなし、`worker.verify` | 編集の検証 | 編集に必須。networkなしの固定Docker imageで実施 |
| 依頼者への返却 | TaskのDM・応答 | 同じTaskのread_result | 送信直前に本人と現在の閲覧権限を再確認 |
| 外部送信・公開・push・merge・deploy・credential変更・破壊的操作 | actionなし | privileged_change / Sensitive write等 | このruntimeでは表現・grantできない |

読取workerの`cwd`は対象directoryであり、読取可能範囲を強制するsandboxではありません。
実際の範囲とnetworkの可否はCodexのsandboxと実行ホストの設定に依存します。
実装のsandbox、検証用Docker、権限の再確認は別の境界です。runtimeが一回のCodex実行の
内部tool stepを一件ずつ認可しているとは主張しません。worker開始前・checkpoint・
fallback前・各検証コマンド前と、実行中の監視で現在の権限を確認します。

[受付の契約](TASK-OWNER.md)に従って複合依頼全体を検査し、受付後はTaskごとに再認可します。
一件の権限取消で、既に完了した別Taskの成果を巻き戻すことはありません。
実Discord・実音声での拒否と停止の受入は[#154](https://github.com/Kotodama-Project/Kotodama-project/issues/154)で扱います。

## Runtime admission and recovery boundary

The conversation Pipeline records the current Source before it seeks a bounded
analysis slot. Global, room and reader limits share one scheduler; a finite
priority queue may supersede a passive entry, but does not erase its Source.
Reservations count analysis requests, not provider billing. SQLite daily and
cumulative counters survive process replacement. A queued operation revalidates
Source revision, reader access and current policy before reservation/dispatch and
after the model returns. Cancelled operations retain their slots until they settle.
Archive post-processing and other model adapters have separate controls; this is
not an installation-wide financial budget.

A write worker has two execution boundaries: Codex's configured sandbox for
implementation, and a required operator-managed immutable Docker image for
verification. Verification sees a read-only candidate, no network, no host HOME,
no credential mounts, and bounded scratch/resources. A missing verifier is an
explicit refusal, not a host-command fallback. The host collector does not execute
candidate files and disables Git external diff/text conversion; file reads bind
both descriptor and directory entry, reject links/special files and bound the read.
Docker process termination must be observed at the daemon, not inferred from the
client exit. Failed cleanup leaves the Task uncertain.

Running Tasks are rechecked every second. Discord read access is tri-state
(allowed, denied, unavailable) and checked once per distinct channel; results are
reused for at most three seconds and dropped on channel, role, thread and member
events. A definitive denial stops the Task at that check. Rate limits, Discord
server errors and transport failures are unavailable, tolerated for at most five
seconds (from the start of the first failing check) and three consecutive checks,
then the Task stops as before. Each check has a two-second wall-clock limit, a
check still in flight counts as unavailable, and Tasks are checked concurrently.

Startup preserves Task IDs: queued becomes paused, running/stopping becomes
uncertain. Only paused/cancelled/failed may explicitly resume after current grant
and Source checks. An uncertain execution is never automatically replayed. Remote
Task owners remain authoritative; this does not add another remote recovery ledger.

## Growing history and slow connections

Local model context reads use indexed current reader/room projections before
their source and Task limits. Source corrections invalidate indexed Task bindings
in the same transaction. Original bodies, revisions and audit events remain
retained. The first upgrade backfills projections once; older single-writer
changes mark them for rebuilding on the next upgraded open. Budget totals are
maintained transactionally. Complete listing/export APIs and first backfill still
scale with history; this is one SQLite writer per installation.

Transcript overlap indexes target matching utterances and fragments, and settled
delivery promises are released. Late corrections keep the same utterance identity.
Original session evidence remains retained. A model-requested conversation end
disables the session before asynchronously draining its own transcript callback.
Local ASR deadlines cover connection and body reading, with response cancellation
on refusal and classified errors.

Local control, import and remote-owner admission have finite request sets and
bounded HTTP bodies. Imports share one writer lane; timed-out dispatched work
keeps its admission until it actually settles. Notification receipt admission is
separate from ingestion. Shutdown stops intake and waits for dispatched work
before closing SQLite. An uncertain import/owner drain leaves the host lock and
store intact for a retry; transport cancellation does not prove a remote write
was undone. Deferred notifications use indexed, finite rounds so blocked
recipients and new arrivals cannot indefinitely delay other recipients.

These are local runtime improvements. Multi-region routing, tenant isolation in
a shared hosted service, provider quotas/billing, production database failover,
backup/restore and global load/latency acceptance require their own deployments
and measurements.

The existing required `Trusted repository validation` workflow calls the complete
Discord reusable matrix and fails unless its result is success. Failure, skipped,
cancelled and missing matrix results cannot produce a green required context.
This candidate does not mutate GitHub administration settings.

## Deterministic Company Pack worker

`create_company_pack`は明示コマンド専用のbuiltinです。通常のmodel workerへ渡さず、runtimeを含むリポジトリの固定Python executorを起動します。利用者の`worker.workspace`にあるscriptは実行しません。Linuxのowned process groupと固定Docker imageが必要で、host検証やmodelへのfallbackはありません。

Task ownerは既存のlocal SQLite一つです。executorは現在のrunning Task/Source/Intentを読取り、Task状態を更新しないreceiptを返します。Task ID/revisionからoperation keyを決め、Context/Grantの確認は既存Pipelineが維持します。作成後のPackはreadonly/no-network Dockerでhash検査し、Hostでも再読します。全ファイルとreceiptをartifactへ束縛し、Taskは`needs_review`です。

出力は専用の`dataDir/worktrees/company-pack-operations`内、ダウンロード束は`company-pack-results`内です。どちらも通常のGit Task worktreeと重ねません。channel workspace使用時も同じTask owner・期限guardを通しますが、Company Pack自体はGit checkoutではありません。実pipelineの観測と実Discord/Human受入を分けます。

## Native correction

Discordのbutton/selectは現在のTask/Sourceの版を参照するだけで、UI状態を保存の正本にしません。modalの明示送信は既存Pipelineの現在grantを通り、local ownerの同一transactionでSource履歴・意図・Taskを更新します。他Taskも同じSourceを参照する場合や関連処理が実行中または終了不明なら変更せず、remote ownerへは未対応として拒否します。旧版のフォームと、送信直前に変わった出典は受け入れません。

modalはDiscordの[LabelとText Input](https://docs.discord.com/developers/components/reference#label)を使い、messageのbutton/selectは既存のAction Rowへ置きます。SDKで構造を検査していますが、実Discordでの人の操作確認は別です。

modalの初期応答にはnetwork照合やSource本文の取得を挟みません。値を自動表示せず、静的な空欄を即時に開きます。submitはmembership/Source/grant照合の前にdeferし、検証後にだけ既存ownerへ書きます。遅いpermission応答を模した試験を用意し、実Discordの期限内応答は人の受入で確認します。
