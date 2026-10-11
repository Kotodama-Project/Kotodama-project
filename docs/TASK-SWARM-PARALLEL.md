# 通常Taskの有限queueと読取専用並行実行

#330 の初期実装です。Discord pipeline が持つ同じ Task owner の仕事を、有限の参照queueへ入れます。
Task内の三つのswarm workerとは別の、Task間の実行待ちを扱います。

既定は同時実行1です。`worker.taskLimits.maxConcurrentReadOnly` を2〜4に設定した場合だけ、
既存 `CliWorker` がread-only sandboxと空のfilesを要求する `research` / `summarize` を並行できます。
同じactorまたはroomのTaskは同時実行しません。`develop` / `write_file` / `create_company_pack` /
`swarm_research` と未知のactionは全体排他です。writerがqueueへ入った後のTaskは、writerを追い越しません。
関連するrequiredActionsにwriteが一つでもあれば、そのTaskも全体排他です。

## 設定と単位

`worker.taskLimits` は次の部分設定を受け付けます。

```json
{
  "maxConcurrentReadOnly": 1,
  "maxQueued": 32,
  "maxQueuedBytes": 65536,
  "maxInputBytes": 524288,
  "maxResultBytes": 8388608
}
```

- `maxConcurrentReadOnly`: 1〜4。write系の実行中はread-onlyも開始しません。
- `maxQueued`: 0〜256。待機件数です。実行開始枠とは別に検査します。
- `maxQueuedBytes`: 0〜1,048,576。queueに保管するTask ID / revision / actor / roomなど参照記述子のUTF-8 bytesです。
  Source本文やTask本文をqueueへ複製しません。本文全量のサイズとは異なります。
- `maxInputBytes`: 1,024〜8,388,608。contextSourcesを含めworkerに渡すTaskと取得したcontextをJSON化したUTF-8 bytesです。
- `maxResultBytes`: 1,024〜67,108,864。owner.finishへ渡す結果JSONのUTF-8 bytesです。
  artifact本文の上限は既存 `worker.maxArtifactBytes` も引き続き適用します。

待機件数/参照bytesを超えるbatchは、最初のTaskを始める前に全体を拒否します。
作成済みの未実行Taskは同じownerの `cancelQueued` で処理し、別のTaskを作りません。
入力・結果の上限超過は成功結果へ昇格せず、既存Taskに失敗を返します。
queue statusは `pipeline.taskAdmission.status()` でrunning / queued / queuedBytes / limitsを返します。

## 順序、取消、終了

実行可能な古いTaskを選び、可能なら直前と別のactor/roomを選びます。
同じactor/roomが枠を占有する場合でも、独立したactor/roomのread-only Taskを選択できます。
任意の優先度による追い越しは導入していません。

同一Task ID / revisionの再enqueueは既存実行を再利用します。訂正で古くなった待機revisionや
取り消された待機Taskは開始しません。認可待ちで遅延した旧revisionの通知は、現在のownerと
照合して容量計算から除外し、新revisionの待機枠を取り消しません。実行中の取消ではworkerがsettleするまで枠を維持します。
停止を確認できない `STOP_UNCONFIRMED` は新しい仕事の開始を止め、ownerのuncertainを維持します。

終了時は待機Taskを開始せず、実行中workerへ取消を要求してsettleを待ちます。
未実行のowner Taskは保持され、次の起動時に既存 `reconcileInterrupted` がpausedへ移します。
実行途中のTaskは既存のuncertain/recovery手順に従います。queueは新しい永続Task台帳を作りません。

実行中にpolicyの並行数が減った場合、既に開始したworkerは維持し、新規開始を新しい上限まで待たせます。
actionの許可・現在のTask revision・Sourceの整合性は既存のauthorize/ownerで実行時にも検査します。

## 検証と残る範囲

`task-parallel-queue.test.mjs` は有限queue、全件拒否、重複、actor/room、writer排他、取消後の実終了待ち、
動的上限、入力/結果bytes、uncertain、再起動時のowner状態を合成workerで検証します。
`task-parallel-config.test.mjs` は既定1と設定範囲、read-only分類を検証します。

この上限はprocess RSS・CPU使用率・provider課金額の強制制限ではありません。それぞれの計測と
resource/cost admissionは#330の残作業です。実provider・本番負荷での高速化、最適な並行数、
swarm_researchの複数Task同時実行は未検証です。並行数1で従来の直列動作へ戻せます。
Taskをneeds_reviewへ返す条件や、swarm内の全criterionを含む独立reviewは変更しません。
