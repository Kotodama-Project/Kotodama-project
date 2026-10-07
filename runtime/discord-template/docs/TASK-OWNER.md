# Task owner

既定は`owner.kind=local`です。インストール先のSQLiteを一つのTask ownerとして使います。JSON/CLIの`task.id`は不変で、訂正と再開は同じIDの新しいrevisionになります。

[capability lane](ARCHITECTURE.md#capability-lanes)は4つの既存actionの固定写像です。
`worker.actions`以外のgrantを作らず、音声とテキストで権限を分けません。

`owner.kind=remote`を選ぶ場合、接続先は次のprivateサービス契約を実装してください。ローカルTaskへのfallbackや二重書込はしません。既存の組織版ownerにこの契約を接続するadapterが必要です。

`POST /v1/owner`、Bearer認証、入力`{version:1,method,args}`、成功`{version:1,ok:true,result}`。

扱うメソッドは `ingest`、`source`、`createTask`、`reviseTask`、`task`、`taskInternal`、`tasks`、`claim`、`bindContext`、`assertContext`、`finish`、`cancel`、`cancelQueued`、`confirmStop`、`resume`。これは信頼済みサービス間の契約であり、一般利用者へそのまま公開するAPIではありません。

受付は現在の設定snapshotで全actionを照合し、全Taskの作成と再認可が完了してから
実行キューと受付通知へ進みます。途中で失敗した既知のqueued Taskは
`cancelQueued(id, actor, expectedRevision)`で、そのrevisionとqueued状態が一致する場合だけ
取消します。返値は取消後のTask（revisionは一つ進む）です。新しいrevisionや実行中のTaskを
取消しません。remote ownerもこの比較付き操作を実装する必要があります。
取消の確認やremote作成の成否が不明な場合は`ADMISSION_CLEANUP_UNCERTAIN`を記録して
新しい受付を止めます。Taskが消えた、未実行である、取消済みとは推測しません。

受付後は各Taskの現在の認可で実行を継続します。一件が実行済みになった後のgrant取消は
他のTaskの成果を巻き戻すtransactionではありません。実行前に拒否されたqueued revisionは
比較付き取消を試み、実行中は既存のcheckpointと監視で停止します。

sourceはprovider/guild/channel/source ID、actor、readers、revision、本文、finalityを保持します。Taskには依頼元と実行に使用したすべてのcontext sourceを束縛します。ownerは現在の本人・権限・出典を検査し、CAS・重複抑止・取消を永続化します。

実行の候補状態はqueued/running/needs_review/failed/stopping/cancelled/stale/uncertainです。`needs_review`は利用者が成果を確認できる候補であり、会社側のTask完了やPromotionではありません。組織のlifecycleへの対応は既存ownerが担当します。

成果ファイルはworker hostが所有します。remote構成では、そのhostの認可済みartifact readerを接続する必要があり、別ホストのファイルパスをローカルの実ファイルとして扱いません。

Taskは `intentIds` と全構成操作の `requiredActions` を保持します。複合依頼の代表actionだけで認可せず、実行前・実行中に全操作を現行grantへ照合してください。直接コマンドの操作・title・受入条件もSource fingerprintに束縛し、同じ配送IDの別payloadは拒否します。

remote接続は同時8件、要求・応答それぞれ4,000,000 bytes、要求開始から応答本文の読取完了まで15秒に制限します。満杯では送信前に `OWNER_BUSY`、大きすぎる要求は `OWNER_REQUEST_LIMIT`、応答は `OWNER_RESPONSE_LIMIT` で拒否します。読取の期限超過は `OWNER_TIMEOUT` です。

送信済みの書込が期限超過・停止・通信切断で中断された場合や、成功結果を検証できない場合は `OWNER_RESULT_UNCERTAIN` です。接続先での取消や未実行を証明するものではなく、自動再送・local ownerへのfallbackはしません。同じTask ID・source revisionと接続先の永続状態で結果を確認します。取消に応じない要求は実際に完了するまで枠を保持し、その間の同一書込payloadを `OWNER_WRITE_PENDING` で拒否します。停止は新規要求を拒否し、取消と最大15秒のdrainを行います。`OWNER_DRAIN_UNCERTAIN` の場合は既存のTask ownerとデータ領域の所有を保持し、未確定の処理を照合してください。

## 明示Company Packコマンド

`create_company_pack`はlocal owner限定です。remote構成ではSourceの取込・Task作成前に拒否し、localにTaskを複製しません。明示Sourceから保存済みIntentへ結び、同じTask IDとrevisionをPythonのread-only SQLite bindingへ渡します。Task/Work Order/capabilityの代替recordを生成しません。Pythonの`authority_verified: false`は記録の読戻しが本人性の証明ではないことを示し、実行の現在grantは既存runtimeが検査します。

結果とartifact hashは既存`finish`のCASと`result`の再読へ戻します。実行中の再起動は既存のuncertain回復を使い、自動再実行しません。権限を外した後も、本人のSource閲覧権限が維持される履歴の読取りは別です。

## 明示swarm調査

`swarm_research`の最初の入口は操作者の明示slashです。既定無効、日次枠0で、
local owner限定です。analyzer、通常会話、trusted CLI request、remote ownerからは
受け付けません。専用Codex homeがない場合もSource/Taskを書込む前に拒否します。

既存Task ID/revision、依頼Sourceと最大9件の選択した履歴、actor/grantと期限を
privateな実行入力へ束縛します。選んだSourceの全文を維持し、上限超過は拒否します。
Pythonの実行DBとowner入力は同じTaskへの実行記録であり、Task状態の別の正本ではありません。
日次予約は既存SQLite ownerが持ち、同版の二重実行や時計の巻戻りで枠を増やしません。

全条件と別verifierの記録、限定読取profile、元の成果bytesを検査してから、同じrevisionの
`finish`へ返します。結果は`needs_review`または`failed`です。取消を入力に固定してから
owned process groupを止め、停止・無効化が確認できなければ`uncertain`に保ちます。
Pythonの同版読戻しは外側が保存した初回receipt SHAを要求します。Nodeは同版を再dispatchせず、
既存Taskのartifact hashで成果を再読します。実利用の意味的受入とHuman GOは利用者に残します。

## native UIからの訂正

local ownerの`correctTask`は、Taskと現在Sourceの期待revisionを一つのSQLite transactionで照合します。既存`source.corrected`で関連Taskを無効化し、同じTask IDを`reviseTask`で更新します。このため無効化と再受付を通る場合はTask revisionが二段階進みます。原文は`source_versions`、訂正者・時刻・interactionと前の版はSource metadata、因果の参照は既存eventに保持します。

actionとrequiredActionsは既存Taskから保持します。現在の操作者・閲覧範囲・実行grantを再確認し、別人、古いUI、関連する実行中/停止中/終了不明を拒否します。modalはprivate本文を含まない空の入力欄を即時に表示します。submitは先にdeferし、network認可の後、Source/Task版・Discord accessGenerationをatomic変更直前とenqueue前に再検査します。remote契約にこの原子的操作はまだ含めず、`TASK_CORRECTION_REQUIRES_LOCAL_OWNER`で書込み前に拒否します。

共有Sourceの訂正は、別Taskのprimary Sourceまたはcontext bindingがある場合に拒否します。他Taskをstaleにしたりresult参照を消したりしません。音声の手動訂正は`manual_correction`とし、archiveの自動置換から外します。元のASRとarchive参照は以前のSource revisionへ保存されています。
