# 同じTask内で検証と修正をつなぐ

[#350](https://github.com/Kotodama-Project/Kotodama-project/issues/350)の最初の縦断実装です。
目的・記憶・要件分解・並行実行・批判・統合・学習・再計画という全体目標は
[#50](https://github.com/Kotodama-Project/Kotodama-project/issues/50)と
[#328](https://github.com/Kotodama-Project/Kotodama-project/issues/328)に残ります。
この版は、既存ownerに束縛したversion 2入力と、目的ごとに用意した有限planを使い、
並行作業→独立critic→不足根拠の修正→再検証→統合候補までを同じ実行でつなぎます。
入力形式は[Taskの目的契約](TASK-OBJECTIVE-CONTRACT.md)を参照してください。

## 実装した範囲

| 機能 | この版の動作 |
|---|---|
| 目的と分解 | callerが与える1〜3件のworkと1件のcriticからなる有限DAG。目的、担当基準、資料spanはjobごとに指定 |
| 子の文脈 | 元の依頼・訂正履歴・goal参照・制約・未知・受入条件を必須で保持し、指定した資料spanだけを追加 |
| 並行実行 | 既存`OwnerFile`と`SwarmState.claim/report/accept`を使用。別のTask台帳を作らない |
| 独立批判 | workerと異なる既存actor、重複しないinvocation、実際に渡した入力digest、全報告digestと全基準を照合 |
| 修正 | `failed`の実行済みcriticからのみ最大1回。criticに渡された不足spanと失敗基準だけを次planへ渡す |
| 統合 | 最終criticが参照するclaimと報告間のconflictを、出典付きの`integrated_candidate`へ決定的に集約 |
| 学習 | 全基準passedの場合だけ`learning_candidate`を作る。`unadopted`かつ`next_context_eligible=false` |
| 予算・再開 | 同じTask/revision・run ID・SQLite内で消費を集計。完了後は外部receipt hashによる再読のみ。未完runは復旧判断を要求 |

plan生成器、再帰的な分解、途中work間の依存を持つ多段DAG、実provider、金額・token予算、
knowledge採用→次のfresh session入力への接続は未実装です。今は明示したlocal simulationのみを
受け付けます。合成のpassedは実モデルの品質改善や本番運用の受入を証明しません。
この変更は既存の固定3worker runner、Discord入口、Taskの完了処理を切り替えません。

## planと子の入力

`closed_loop_contract.validate_plan`が受けるJSONは、`version: 1`、元入力全体の
`parent_input_digest`、`jobs`です。各jobは次の4項目だけです。

| 項目 | 制約 |
|---|---|
| `job_id` | 重複のない英小文字開始の英数字・`_`・`-`、最大56文字。`critic`は予約 |
| `purpose` | 目的に応じた担当内容。空欄不可、最大2,000文字 |
| `criterion_ids` | `R`依頼、`S`出典、`U`未知、`I`比較、`A1...`受入、`O1...`制約、`Q1...`未知条件の部分集合 |
| `selected_spans` | 元Taskの現在Sourceを指す1〜32個のspan。元のoffsetを保持 |

初期planの担当基準の和集合は全基準を覆う必要があります。修正planは失敗基準と不足spanを
過不足なく覆い、範囲を広げません。同一内容のplanをIDだけ変えて再試行しません。
上位objectiveと親入力は不変です。新たなSourceが必要なら、このrunで勝手に取得・追加せず、
既存ownerの次revisionを待ちます。

`closed_loop_context.derive_child_view`は必須文脈と選択spanの本文・SHA-256を作ります。
子入力には親入力digest、初期plan digest、job ID、前critic digestを持たせます。
報告のquoteは元Sourceと一致するだけでなく、実際に渡した1個のspan内に収まる必要があります。
criticにも同じ文脈境界を使い、未配布のSourceを既知として修正理由にできません。
各dispatchのJSON全体を保存し、そのdigestをbackend receiptと照合します。
criticのplan内`payload_digest`は、まだ成果がない時点の入力templateに束縛します。
実dispatch時には依存する報告と各digestを加え、その全入力digestを別途receiptへ固定します。
最終criticの検証は、実際に渡した報告集合と一致することを要求します。

## 実行入口

Python APIは`closed_loop.execute_closed_loop(owner_path, payload_path, supplied_plan, backend,
worker_actors=..., critic_actor="verifier", repair_planner=...)`です。
`repair_planner(gap)`は外部呼出しをしないpureなデータ変換という境界です。
現在のbackendは`synthetic=True`を明示し、`produce`と`review`から実入力digestに束縛した
結果を返します。provider用adapterを追加するには、実配送・runtime証拠・費用を別途接続する必要があります。

install済みwheelでは次の入口を使えます。新しい権限やTaskは作らず、既存ownerのactorを指定します。

```sh
python -m kotodama_core.task_swarm.closed_loop \
  --owner PRIVATE_OWNER_JSON --input PRIVATE_TASK_INPUT \
  --plan PRIVATE_FINITE_PLAN --simulation PRIVATE_SCENARIO_JSON \
  --worker worker-a --worker worker-b --critic verifier
```

source checkoutでは`PYTHONPATH=runtime`を指定し、module名を`task_swarm.closed_loop`にします。
scenarioは`work`、`critics`、`repair_plan`の3項目です。`work`は`r0-<job_id>`・
`r1-<job_id>`から完全な報告JSONへのmap、`critics`は`"0"`・`"1"`から完全なcritic JSONへのmap、
`repair_plan`は上記planまたは`null`です。CLIは成功判定や引用を補完しません。
critic JSONは`parent_input_digest`、初期`plan_digest`、`round`、`report_digests`、
`validations`を持ちます。各validationは`criterion_id/status/evidence/gap_reason/source_spans`です。
passedには実在するjob/claim番号が必要で、failedには説明と実配布済み不足spanが必要です。

完全な入力・owner・scenarioを組み立ててCLIから保存・再読まで動かす例は
`tests/test_task_swarm_closed_loop.py`の
`test_cli_runs_a_fully_declared_scenario_through_owner_and_state`です。
同ファイルの計測fixtureは、workerが報告から落としたmemory観測をcriticが見つけ、
そのspanだけを再配布して修正します。固定のecho成功や固定3jobを達成条件にしません。

stdoutは統合候補とreceiptを含みます。実本文を含むため、private出力として扱ってください。
再読には呼出し元が保存した`--receipt-sha256`を渡します。同じdirectoryから取得したhashを
期待値に置き換えません。未完run、artifact改変、owner変更、期限超過、新しいplanでの再実行は拒否します。
ownerが有効な間の完了済み再読だけは、objectiveの実行期限後も許します。

## 停止と証跡

全試行数は元の4〜6件、並行数は指定actor数の最大3件、critic予約1件です。
criticの呼出しも試行に数えます。repairには残試行数がwork数+critic1件以上必要です。
`blocked/not_run`、同じplan、予算不足、2回目の不足は停止し、未解決を候補に残します。
negative criticをacceptして修正を解放せず、新jobを同じDBへ一度だけ追加します。
初期planは書き換えません。同じextensionの再送は同一内容だけ許し、別内容は拒否します。

全dispatchの入力合計512 KiB、保存artifact合計2 MiBを上限にします。receiptは実際の
試行数・round数・入力/成果bytes・経過秒を記録します。RSSやモデル費用を0と推測しません。
中断したleaseの自動再配送は行わず、`RUN_RECOVERY_REQUIRED`で止めます。
Python APIのcallbackは`timeout`と`cancel_event`を守る必要があります。任意のPython
callbackをthreadから強制終了する機能はありません。取消を無視するcallbackでは、その戻りまで
待つ可能性がありますが、期限後の結果は公開・acceptしません。これは硬いprocess時間制限の
保証ではなく、その保証を必要とするprovider接続は後続です。CLIのsimulationは固定JSONを返します。
完了receiptの再読では、全artifactと保存されたexecution snapshotも照合します。
候補がpassedでもownerのTask、knowledge、Current Truthを書き換えません。
