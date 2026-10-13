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
| 目的と分解 | callerが与える1〜3件の並行workと1件のcritic。目的、担当基準、資料spanはjobごとに指定 |
| 子の文脈 | 元の依頼・訂正履歴・goal参照・制約・未知・受入条件を必須で保持し、指定した資料spanだけを追加 |
| 並行実行 | 既存`OwnerFile`と`SwarmState.claim/report/accept`を使用。別のTask台帳を作らない |
| 独立批判 | workerと異なる既存actor、重複しないinvocation、実際に渡した入力digest、全報告digestと全基準を照合 |
| 修正 | `failed`の実行済みcriticからのみ最大1回。criticに渡された不足spanと失敗基準だけを次planへ渡す |
| 統合 | 最終criticが参照するclaimと報告間のconflictを、出典付きの`integrated_candidate`へ決定的に集約 |
| 学習 | 全基準passedの場合だけ`learning_candidate`を作る。`unadopted`かつ`next_context_eligible=false` |
| 予算・再開 | 同じTask/revision・run ID・SQLite内で消費を集計。完了後は外部receipt hashによる再読。保存済みterminal checkpointからは再配送せず確定処理だけを再開 |

plan生成器、再帰的な分解、途中work間の依存を持つ多段DAG、実provider、金額・token予算、
複数の学びの検索・採用と再帰的な改善は未実装です。
[一つの学びを次のTaskへ渡す限定経路](TASK-LEARNING-REUSE.md)は、別の独立reviewとowner判断を要求します。
今は明示したlocal simulationのみを
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
初期plan全jobの選択spanの和集合も32個までです。33個以上はrun directoryを作る前に
`LOOP_CONTEXT_LIMIT`で拒否するため、有効な初期planに直して同じTask/revisionで再試行できます。
既にadmitしたrunの修正roundや実配送bytesの上限超過は、初期planの事前拒否とは異なり、
元のrunと消費済み予算を保持して停止します。
上位objectiveと親入力は不変です。新たなSourceが必要なら、このrunで勝手に取得・追加せず、
既存ownerの次revisionを待ちます。

`closed_loop_context.derive_child_view`は必須文脈と選択spanの本文・SHA-256を作ります。
子入力には親入力digest、初期plan digest、job ID、前critic digestを持たせます。
報告のquoteは元Sourceと一致するだけでなく、実際に渡した1個のspan内に収まる必要があります。
criticにも同じ文脈境界を使い、未配布のSourceを既知として修正理由にできません。
各dispatchのJSON全体を保存し、そのdigestをbackend receiptと照合します。
criticのplan内`payload_digest`は、まだ成果がない時点の入力templateに束縛します。
実dispatch時には依存する報告と各digestを加え、その全入力digestを別途receiptへ固定します。
criticの検証は、初期planと受け付けた修正extensionの全work job集合に報告が過不足なく
一致することを要求します。呼出側は保存済み実入力と別保存のdispatch digestを渡し、
viewの親・plan・job・自己digest、報告集合、templateとの結合を再照合します。
第2ラウンドは、保存済みの前critic入力・応答と受け付けたextensionを必須にします。
前応答の全基準を再検査し、failedだった各基準が実際の修正jobの報告を引用する必要があります。
空や一部だけの修正対象指定で、この検査を省略することはできません。
これらは保存証拠の整合性検査であり、純粋関数だけでactorの権限や出典本人性を保証しません。

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

## terminal checkpointからの限定再開

全workと最終criticの報告を保存・検証した後、同じ`execution.sqlite`へterminal checkpointを
固定します。以後はplan extensionを追加できません。checkpointは元入力、plan、actor、
実配送入力、報告、critic、統合・学習候補と、accept対象のjob/token/epochを束縛します。
各acceptはjob・attempt・checkpointの進捗を同じSQLite transactionで更新し、取消や期限で
拒否したtransactionは3者ともrollbackします。

この境界以後のprocess終了では、同じowner、入力、plan、actorを指定して
`resume_finalization=True`で確定処理だけを明示再開できます。CLIでは次のように
`--resume-finalization`を渡し、simulationを指定しません。

```sh
python -m kotodama_core.task_swarm.closed_loop \
  --owner PRIVATE_OWNER_JSON --input PRIVATE_TASK_INPUT \
  --plan PRIVATE_FINITE_PLAN --resume-finalization \
  --worker worker-a --worker worker-b --critic verifier
```

再開は現在のowner/source/actor/learning採用判断・取消・実行期限を再検査し、保存された
同じtoken/epochだけをacceptします。backend、critic、repair plannerを呼ばず、試行予算を
追加消費しません。未報告lease、未完work、checkpointのないrunは再配送しません。
OSがprocess終了時に解放する非待機lockを使い、並行finalizerは有限に拒否します。
電源断やfilesystem/SQLiteの耐久性全体、lease更新、未知のrunの自動復旧は保証しません。

receiptのcanonical bytesはDBへ固定し、既存の未公開stageはJSON内容が等しくても
bytesが異なれば拒否します。DB・成果・stageの不一致を上書き修復しません。
新receiptはcheckpoint digestを持ち、再読時もDBの固定bytesと照合します。
旧writerが作ったcheckpoint項目のないreceiptは、従来の外部hashとartifact検証で再読できます。
receiptの経過秒はcheckpoint以前の観測範囲を明記し、中断後の時間を推測しません。

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
待つ可能性があります。acceptは既存SQLite transaction内の取得後とcommit直前に取消・
run期限を検査し、拒否時はそのjobとattemptの更新をrollbackします。以前にcommitした他jobの
進捗は取り消しません。既受理jobへの同内容acceptも現在の取消・期限を検査します。
SQLite外のEventや時計とcommitを一つの原子操作にはできず、最後の検査後の変更は次の操作で
検出します。これは硬いprocess時間制限の保証ではなく、provider接続の受入は別途必要です。
CLIのsimulationは固定JSONを返します。
`cancel_event`は呼出し内の停止信号で、永続的な取消記録ではありません。一般的なbackend失敗や
このEventの変化だけでは、ownerの明示取消を記録しません。

receiptは未公開の同一directory内ファイルへ書込み・fsync・再読し、owner/source/取消/期限と
全artifactを再検査してからrenameで`receipt.json`へ確定します。その最後の資格検査を通過して
確定した後は、追加のguardで戻り値を失わせず同じbytesのSHA-256を返します。一時停止信号や失効が
最後の検査後に変わることは、確定済みreceiptのanchor返却を撤回しません。明示的な永続取消は
同じOS lockで順序づけ、finalizerがlockを持つ間は受理せず`FINALIZATION_BUSY`を返します。callerはこのanchorを
外部で保持します。process kill、電源断、DBとfilesystemとcallerへの返却の完全な原子性、
未完workの自動復旧はこの境界の保証に含めません。上記の明示再開は、保存済みterminal
checkpointと有効な現在資格がある場合に限ります。

workerの完了順によらず、criticへ渡す報告、後続context、統合conflictはjob ID順に組み立てます。
各report内のclaim/conflict順は保持します。同じ検証済み報告とcritic結果からは統合・学習候補の
bytesが一致します。経過時間などを含む実行receipt全体の一致は要求しません。
完了receiptの再読では、全artifactと保存されたexecution snapshotも照合します。
候補がpassedでもownerのTask、knowledge、Current Truthを書き換えません。

## 同じrunの明示取消

API-onlyの`closed_loop.cancel_closed_loop(owner_path, payload_path)`は、既存Task/revisionの
runだけを取り消します。新しいrunやTaskを作らず、owner入力、Source、保存入力、初期planを
照合し、finalizerと同じOS lockを取ってから同じSQLite DBへ取消をcommitします。
`closed_loop_cancellation`が実装本体で、CLI、Node queue、provider停止操作は追加しません。

```python
from kotodama_core.task_swarm.closed_loop import cancel_closed_loop

cancellation = cancel_closed_loop(owner_path, payload_path)
```

返却値は`version/run_id/binding_digest/initial_execution_plan_digest/owner_ref/requested_at`です。
`initial_execution_plan_digest`は保存された初期runtime planのhashで、supplied planの
`initial_plan_digest`とは区別します。同一要求の再送は最初の記録を返し、run期限後でも
現在ownerが有効なら読めます。期限後の新規取消、owner失効、変更されたSourceや入力は拒否します。
receiptのentryが既にあれば`RUN_CANCELLATION_RECEIPT_PRESENT`で拒否します。壊れたreceiptも
上書きせず拒否し、その存在を成功と認定しません。完成済みrunは従来のanchor再読を使います。

取消commit後は通常入口、fresh processのresume、monitor、各実行guard、stateの変更操作が
`RUN_CANCELLED`で止まります。monitorはbackendのEventへ停止を通知しますが、callbackの強制終了や
外部ACKは保証しません。取消commitより前のclaimはin-flightとして保持します。直前guardと物理的な
backend呼出しは原子的ではなく、既claimの呼出しが必ず0回になるとは保証しません。
未知のidentity、lease、attempt、予算とreserveはそのまま残し、取消を
理由にpendingへ戻したりpermitを解放したりしません。取消後のstatus snapshotは`cancelled`と
取消記録を返し、jobを更新しません。backendや検証の元例外は、拒否されたcleanupで置き換えません。
永続取消は既に記録したmonitor理由より優先します。一般エラーや`stop_unconfirmed`を別の取消へ
変換せず、取消状態を再読できない場合も元の実行例外を保持します。

取消の解除API、checkpoint前の自動復旧、外部実行のexactly-once保証は含みません。
`tests/test_task_swarm_closed_loop_cancellation.py`で実process中断後の取消・fresh process拒否、
元の入力と履歴の保持、finalizerとの排他、stage保存後の拒否、一時停止との区別を確認します。

## 担当ごとの証拠契約

新規runは証拠契約2を初回dispatch前に固定します。`r0-critic-template.json`の
`evidence_contract_version: 2`と`required_evidence_jobs`はruntime planのpayload digestに入り、
既存execution DBのplan/jobへ束縛されます。criticが返した担当表やreceiptの版だけで
契約を選びません。新規runを旧契約へ下げるオプションはありません。

各条件の初期担当は、変更不能なsupplied planの`criterion_ids`から導きます。
passedは担当の**全job**のclaim参照を必要とし、担当外・重複・一部だけの参照を拒否します。
failed/blocked/not_runでも、与えた参照を担当外へ向けることはできません。
R/S/U/I/O/Qは全初期jobに割当てます。任意のsupplied planでは宣言した割当の一致を保証し、
rootの条件が全leafに展開された保証は、別のSource検査済み初期plannerに依存します。
自然文や同じ文章だけから階層を推測しません。

修復jobの影響先は、実際にadmitされたrepair planの失敗条件を担当した初期leafの和集合です。
修復後は、そのleafと重なる条件に元のreportと修復reportの両方を要求します。
以前passedだった共通条件も再評価し、Iは全reportを引き続き要求します。
共通条件の修復は全leafへ波及する保守的な規則で、旧reportの自動置換ではありません。
実際のworker入力も初期/修復planから再構成し、保存入力とruntime payload digestに照合します。

契約2のreceiptは`version: 2` / `coordinator: closed_loop_v2`、checkpointは`version: 2`です。
normal、最終処理の復旧、外部anchorでの再読、学びの元run検査で同じ規則を使います。
保存済みの契約1は、DBに束縛された旧templateを根拠にそのまま読みます。
完了済みv1はcheckpoint導入前・導入後の両方を保持し、新checkpointを後付けしません。
未完v1は有効なterminal checkpointがある場合だけ従来どおり明示復旧でき、
checkpointなしからの再dispatchや版の書換えは行いません。

表の追加分も既存512 KiB入力・2 MiB artifact予算に含みます。最大64条件・6reportの
関係を扱い、新しいhistory scanやcacheは追加しません。全担当を引用したことは、主張の真偽、
モデル品質、owner採用、Current Truthや閉ループ全体の完成を意味しません。

## 検証済みgapからの部分修正（#365）

新規runは、初期planの条件割当と実criticから修正対象を決定します。
失敗条件を担当するleafだけに1つずつ修正jobを作り、元のreportは保持します。
独立側のworkerを再実行せず、最終criticは保持側を含めて全担当証拠を再検証します。
共有条件を担当する修正は、関係する全leafの条件にも寄与するため、
一方の修正証拠だけでは合格しません。修正は最大1回、元のattempt/期限/ownerの範囲です。
対象・spanを予算に合わせて間引くことはせず、入らなければ停止します。

最初のcritic templateに`repair_planning_contract: 1`を固定し、
既存DB内の初期planのdigestへ束縛します。修正時の`repair-impact.json`には、
実gap、初期担当、修正対象、保持report、修正前のattempt identityと残予算を記録し、
修正criticのtemplateにそのfile hashを固定します。復旧・anchor再読・学習originも
同じ根拠を再構築します。修正後の残予算を修正前の値と比較してはいけません。
markerやimpactの欠落を旧方式へ戻す理由にしません。真正な旧v1/v2は保存された契約で
読み、旧runへこのmarkerを後付けしません。任意callbackは候補の提供だけができ、
決定的な修正planと一致しない提案は受理されません。

現在の保存済みgapから、実行せず提案を調べる入口:

```sh
python -m kotodama_core.task_swarm.repair_planning --owner owner.json --input input.json
```

source checkoutではmodule prefixを`task_swarm`として、既存のruntime import経路を使います。
この入口は既存owner/Source/初期planを読み直し、`admitted: false`のproposal/impactを返します。
初期criticが未報告、取消済み、期限切れ、gapなし、または必要な保存証拠が欠ける場合は拒否します。
learning grant、保存済みcontext binding、checkpoint、またはDB release certificateが束縛したrelease-progressにlearning contextが残るrunのstandalone inspectionは、
現在のlearning decisionを読む入口がないため`LOOP_REUSE_INSPECTION_UNSUPPORTED`で拒否します。
profile2ではcheckpoint前でもrelease-progressのSHAを既存DB証跡に照合し、learning context/bindingの残存を拒否します。progressの欠落・改変も拒否します。
旧記録にgrant・保存binding・checkpoint・DB release証跡のいずれも残らない場合のlearning現在性は保証しません。
learningの通常実行・anchor再読・terminal resumeは既存の現在decision検査を使います。
新規実行は既存のclosed-loop simulation入口から自動plannerへ接続します。
未知leaseやcheckpoint前の一般的な再開は許可しません。

二度以上の修正と、Source訂正を跨ぐ完了jobの再利用は未対応です。実行依存の対応範囲は以下の二葉 A→B に限ります。
構造上の証拠検査とlocal simulationの結果を、実providerの成果や全体loop完成とは扱いません。


## 受理済み A に依存する B（#366）

Source producer→candidate 検証→実行の入口では、owner が束縛した Source の `frontier.requires` から一つの依存を再導出し、ちょうど二つの atomic leaf を扱います。低水準の `execute_closed_loop` は既存 v1 と同様に呼出側の明示 plan を実行します。raw specification v2 だけでは Source 由来を証明せず、その保証は producer と candidate 検証を通した入口に限ります。独立 frontier は従来の specification v1、A→B は specification v2 です。分岐、合流、循環、別 Task、三葉以上の依存 graph は拒否します。owner と Task input v2 の契約は変わりません。元 Source、訂正履歴、root 条件、各 leaf の criterion 割当は両方の worker と critic に保たれます。

新規 A→B run は dispatch 前に execution contract 3 と descriptor の digest を SQLite の不変 plan に固定します。A、prerequisite critic、B、global critic の四呼出しを最低単位とし、上限 4–6 attempts は同じ run 台帳で数えます。prerequisite critic は A・B・owner と異なる actor です。A 専有の A_i を全て検査し、全 claim が元 Source に supported、conflict がなく、全 gate が passed の時だけ A を scoped accept します。root/shared/I 条件の最終検査は global critic に残ります。前段の unknown/failed は不変 blocked evidence となり、A は未受理、B/global critic は pending のままです。完了 receipt や learning は作らず、CLI は exit 3 を返します。

[公開plan schema](../schemas/task-swarm-plan.schema.json)もこの2項目を対で要求します。旧planでは両項目を省き、片方だけ・未知版・不正digestは拒否します。依存の形・予算・ownerとreleaseの一致はruntimeが検査します。specification v2、evidence v2、repair profile 2、execution/checkpoint/receipt v3はそれぞれの契約の版です。

hash の循環を避けるため、Source/view/gate だけから prerequisite core を作り、descriptor は core digest、envelope は core と descriptor digest、DB job は envelope 全体の digest を束縛します。reader は各段を元 input/plan から再導出します。B の入力には元 Source と別の `prerequisite` lane として A の report/result hash/release certificate を渡します。元 Source を生成 claim で置換しません。B の inference も実 Source 引用を要し、global critic は全担当 leaf の証拠と、各 B の実入力 digest・prerequisite lane を受け取って再検査します。synthetic fixture は A の値変更が B の計算値を変え、別計算の critic が確かめます。これは実モデルの意味品質の保証ではありません。

A の受理と release stage の保存は既存 SQLite transaction で一緒に確定します。state の B claim は A の accepted 行と一致する release を要求し、単独の `accept(A)` では開きません。operation lock は確認・保存・claim の間だけで、backend 呼出し中は保持しません。取消 Event と期限は transaction の最後にも観測し、失敗なら A と stage を共に rollback します。外部 Event の変化と SQLite commit の完全な同時性は保証しません。

`--resume-finalization` は従来の終端復旧に加え、release 保存済みで B が pending・試行数 0 の場合だけ、明示した `--simulation` から B/global critic を継続できます。A と prerequisite critic を再実行せず、token/epoch/予算をリセットしません。release 前、B の lease/不明な実行結果、改変された proof、二重実行は拒否します。blocked の再読は呼出し 0 で同じ evidence を返します。stage が壊れていても既存 owner の durable cancellation は利用できます。

B 専有条件だけの失敗は repair profile 2 により一度だけ修復できます（合計六呼出し）。repair B にも同じ accepted A と release が必要です。A/shared 条件の失敗は unresolved のまま止め、古い B を残して A だけを修復することはありません。checkpoint/receipt v3 は preaccepted A の result/ref/owner/時刻を、残りの acceptance と分けて固定し、finalization CAS に raw stage を含めます。終端の最後の資格確認→receipt 公開→同じ anchor 返却は従来の境界を維持します。

旧 writer の完了 v1（checkpoint 前・後）、未完 checkpoint v1、evidence v2/profile1 の修復済み・終端未公開・取消済み run は明示した旧形式の reader を維持します。新 run で legacy へ下げる opt-out はありません。core package の allowlist は新しい三 helper を含み、provider を呼ばない配布検証を行います。Task owner 更新、knowledge 自動採用、一般 DAG、実 provider、性能 SLO はこの slice の対象外です。
