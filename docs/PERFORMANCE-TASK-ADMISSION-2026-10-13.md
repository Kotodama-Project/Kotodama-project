# TaskAdmission の固定比較記録（2026-10-13）

[#331](https://github.com/Kotodama-Project/Kotodama-project/issues/331)の有限fixture測定です。
[#389](https://github.com/Kotodama-Project/Kotodama-project/pull/389)のsource
`d2822b08b87eb1b5d29a5d37ac9264ee2390b58f`、tree
`f14778acf887af4a8efef2a0f475ec527d925fa3`を固定し、一度だけ比較しました。
[公開用JSON](PERFORMANCE-TASK-ADMISSION-2026-10-13.json)に全72試行の数値と各16件の結果を保存しています。

`status=PASS`は固定fixtureの正しさ・指紋一致・全試行完了です。
`qualification=NOT_EVALUATED`を維持し、既定幅・runtimeを変更していません。
この記録は#331全体、全Pipeline、provider/モデル品質、通常運用の性能受入を完了させません。

## 条件と測定範囲

Linux6.18.44 x86_64、Python3.12.14、Node24.19.0、Xeon Platinum8573C、logical CPU5、
cgroup quota4 CPU相当・memory上限16GiBの共有環境です。CPU affinityは変更せず、cacheをflushしていません。
warmupもfresh processで、OS cacheはwarmの可能性があります。Node binaryとsource6filesのSHA-256もJSONにあります。

16 Tasksのactor/roomは各々異なります。waitは各40ms、cpuは各262,144回の固定整数演算です。
幅1/2/4・各workloadを2 armsずつ、各armでwarmup1回とsample5回、各試行timeout30秒で実行しました。
順序は次の鏡像crossoverで、workload内の各幅pairがABBA/BAABになります。

```text
wait1 cpu4 wait2 cpu2 wait4 cpu1 cpu1 wait4 cpu2 wait2 cpu4 wait1
```

対象は**子を作らない1 Node processの起動から終了・回収まで**です。
wallは起動・import・scheduler検査・16 Tasks・drain・JSON化・終了と、observerのpoll待機を含みます。
poll間隔の設定は最大5msで、hostのscheduling遅延は別に加わります。
CPUはLinux `wait4`の全期間user+system、peak RSSはそのNodeの全期間high-waterです。
Python observer・source事前確認・集計harness・owner store・provider・通常Pipeline全体は対象外です。

## 観測値

各条件N=10、warmup12回を除外し、nearest-rank `sorted[ceil(N × p) - 1]`で集計しました。
このNではp95/p99は最大値で、安定したtail推定ではありません。JSONにはmin/max/p99と各Taskのqueue・実行・完了時間もあります。

| workload | 幅 | wall p50 / p95 ms | CPU p50 / p95 ms | peak RSS p50 / p95 MiB |
|---|---:|---:|---:|---:|
| wait | 1 | 693.81 / 712.62 | 53.64 / 68.20 | 31.371 / 31.492 |
| wait | 2 | 376.84 / 407.21 | 54.08 / 81.99 | 31.367 / 31.617 |
| wait | 4 | 211.23 / 219.10 | 50.52 / 57.43 | 31.492 / 31.492 |
| cpu | 1 | 102.69 / 107.91 | 105.44 / 110.34 | 35.875 / 36.000 |
| cpu | 2 | 106.72 / 112.99 | 107.54 / 112.37 | 35.750 / 36.000 |
| cpu | 4 | 102.19 / 107.09 | 105.87 / 110.84 | 35.875 / 36.000 |

waitの全期間p50比は幅1/幅2が1.84、幅1/幅4が3.28でした。これは固定された待機を重ねる局所結果です。
workload部分のthroughput p50は24.82 / 49.53 / 98.65 Tasks/sで、Node起動・終了は含みません。
cpuは**単一event loop内の同期処理**です。幅を増やしてCPU workerを追加せず、CPU並列化の向上を示していません。
RSSは同程度で、持続的なmemory slopeは未測定です。これらから既定幅の採用判断はしていません。

測定60回＋warmup12回は全PASS、失敗・skip・timeoutは0、全72 Node processを回収しました。
対象のwall/CPU/RSS counter欠測は0です。全16件のindex/valueは各workloadの全幅・全試行で一致し、
Python側の別方式の参照計算とも一致しました。source・input・result・Node版のdriftもありません。
queue上限、取消後settlementまでのslot保持、writer barrier、全件settlementも各試行で検査しています。

## 静穏観測と欠測

開始前10区間（約5秒）は最大0.0216 CPU相当、競合するPython/Node/test処理0、throttle0でした。
選択条件は0.20 CPU相当以下・競合0・throttle0で、製品SLOではありません。
計測armsの20.13秒に0.5秒間隔の設定で39回観測し、競合test/executor/Python/Node処理0、
cgroup throttled periods/usecの増分0でした。全観測の実間隔最大は約0.516092秒です。
終了後約3秒も観測しました。他担当のprocessは停止していません。

`OBSERVED_QUIET_LOCAL_WINDOW`はこの有限の観測を示します。共有hostの短い仕事をsnapshot間で見逃す限界があり、
排他的host確保の保証ではありません。host/cgroup CPU pressure interfaceとgovernorは取得不能でnullです。
CLIの`qualification=NOT_EVALUATED`を、この観測で上書きしていません。

Node72回のCPU合計5.852752秒に対し、arms区間のcgroup CPU増分は7.402628秒でした。
差1.549876秒にはobserver・harness・既存service等が含まれ、observerだけの値に分解できていません。
harnessのarms/postflight CPU保存値は0.683178秒ですが、前後のself-rusage生counterは保存されず再計算できません。
harnessの最終観測時点の累積peak RSSは133.5MiBで、事前のNode binary hash読取を含みます。
Node対象のRSSとは別範囲で、最終集計・exitまでの全observer peakでもありません。
PSS、heap、event-loop lag、全observer overhead、長期memory slope、通常Task cancel/restart全体は未測定です。

## 同じCLI条件を再現する

Linux、Python3.12、Node24.19.0を用意し、[CLIの測定条件](PERFORMANCE-BENCHMARK.md)を確認します。
別のcheckoutでsourceを固定し、実行前後と実行中の負荷・競合process・quotaを記録します。
次のコマンドは固定fixtureを再実行します。静穏性の確認や過去の数値の再現保証は行いません。

```sh
git clone https://github.com/Kotodama-Project/Kotodama-project.git task-admission-measurement
cd task-admission-measurement
git fetch --no-tags origin d2822b08b87eb1b5d29a5d37ac9264ee2390b58f
git checkout --detach d2822b08b87eb1b5d29a5d37ac9264ee2390b58f
python --version
node --version
mkdir -p work/task-admission-measurement
arm=0
while read -r workload width; do
  arm=$((arm + 1))
  python -B tools/performance_benchmark.py --allow-local-fixture \
    --fixture task-admission --width "$width" --workload "$workload" \
    --samples 5 --warmups 1 --timeout-seconds 30 \
    > "work/task-admission-measurement/arm-$arm.json" || exit "$?"
done <<'ORDER'
wait 1
cpu 4
wait 2
cpu 2
wait 4
cpu 1
cpu 1
wait 4
cpu 2
wait 2
cpu 4
wait 1
ORDER
```

JSONの`arms[].attempts[]`はwarmupを含む生sampleで、数値は丸めていません。
各`rows`は`metadata.raw_row_columns`の順の配列です。index/valueをobjectに戻すと元のresult digestを再計算できます。
`summary_by_condition`の統計はphase=`sample`だけから計算します。異なるwidthのconfig digestは異なり、
同じ条件の2 armsでは一致します。input/result digestは各workload内で一致します。
JSONは許可した数値・固定識別子・公開source情報から構成し、私的パス・PID・command・hostname・会話を含めません。
