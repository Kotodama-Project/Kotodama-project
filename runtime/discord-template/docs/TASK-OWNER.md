# Task owner

既定は`owner.kind=local`です。インストール先のSQLiteを一つのTask ownerとして使います。JSON/CLIの`task.id`は不変で、訂正と再開は同じIDの新しいrevisionになります。

`owner.kind=remote`を選ぶ場合、接続先は次のprivateサービス契約を実装してください。ローカルTaskへのfallbackや二重書込はしません。既存の組織版ownerにこの契約を接続するadapterが必要です。

`POST /v1/owner`、Bearer認証、入力`{version:1,method,args}`、成功`{version:1,ok:true,result}`。

扱うメソッドは `ingest`、`source`、`createTask`、`reviseTask`、`task`、`taskInternal`、`tasks`、`claim`、`bindContext`、`assertContext`、`finish`、`cancel`、`confirmStop`、`resume`。これは信頼済みサービス間の契約であり、一般利用者へそのまま公開するAPIではありません。

sourceはprovider/guild/channel/source ID、actor、readers、revision、本文、finalityを保持します。Taskには依頼元と実行に使用したすべてのcontext sourceを束縛します。ownerは現在の本人・権限・出典を検査し、CAS・重複抑止・取消を永続化します。

実行の候補状態はqueued/running/needs_review/failed/stopping/cancelled/stale/uncertainです。`needs_review`は利用者が成果を確認できる候補であり、会社側のTask完了やPromotionではありません。組織のlifecycleへの対応は既存ownerが担当します。

成果ファイルはworker hostが所有します。remote構成では、そのhostの認可済みartifact readerを接続する必要があり、別ホストのファイルパスをローカルの実ファイルとして扱いません。

Taskは `intentIds` と全構成操作の `requiredActions` を保持します。複合依頼の代表actionだけで認可せず、実行前・実行中に全操作を現行grantへ照合してください。直接コマンドの操作・title・受入条件もSource fingerprintに束縛し、同じ配送IDの別payloadは拒否します。

remote接続は同時8件、要求・応答それぞれ4,000,000 bytes、要求開始から応答本文の読取完了まで15秒に制限します。満杯では送信前に `OWNER_BUSY`、大きすぎる要求は `OWNER_REQUEST_LIMIT`、応答は `OWNER_RESPONSE_LIMIT` で拒否します。読取の期限超過は `OWNER_TIMEOUT` です。

送信済みの書込が期限超過・停止・通信切断で中断された場合や、成功結果を検証できない場合は `OWNER_RESULT_UNCERTAIN` です。接続先での取消や未実行を証明するものではなく、自動再送・local ownerへのfallbackはしません。同じTask ID・source revisionと接続先の永続状態で結果を確認します。取消に応じない要求は実際に完了するまで枠を保持し、その間の同一書込payloadを `OWNER_WRITE_PENDING` で拒否します。停止は新規要求を拒否し、取消と最大15秒のdrainを行います。`OWNER_DRAIN_UNCERTAIN` の場合は既存のTask ownerとデータ領域の所有を保持し、未確定の処理を照合してください。
