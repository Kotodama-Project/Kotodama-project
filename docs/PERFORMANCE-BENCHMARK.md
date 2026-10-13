# 固定fixtureの性能計測CLI

#331の最初のslice。既存の`swarm-short`合成fixtureをfresh Python processで繰返し、
起動から終了までのwall time、fixture検証後のpeak RSS、同じ入力とコードかをJSONへ返す。
任意shell/外部provider/modelの実行器ではない。Task ownerや費用枠を変更しない。

Python 3.12と既存のhash固定Task swarm依存を用意した環境で実行する。
環境構築は[貢献手順](../CONTRIBUTING.md)と[Task swarm](LUNA-TASK-SWARM.md)に従う。

```sh
python -B tools/performance_benchmark.py --allow-local-fixture --fixture swarm-short --samples 5 --warmups 1
```

`--samples`は1〜20、`--warmups`は0〜3、`--timeout-seconds`は1〜120（既定30）。
各試行は同じinterpreterの新process。warmupも別processであり、常駐processのwarm測定ではない。
OS cacheはwarmの可能性がある。物理cold cache、マシン占有、CPU固定は行わない。
合成fixtureの一時データはrepositoryの`work/`内に作られ、正常終了時に削除される。
失敗時にはfixtureの調査が必要な場合があり、`work/`をGitへ追加しない。

## 出力の読み方

| 項目 | 意味 |
|---|---|
| `status` | 全要求sampleの既存意味検証がPASSし、code/input/result digestが揃ったときだけPASS |
| `code_snapshot` | 計測tool、wrapper、Task swarmコードと二つのdependency lockのpath→SHA-256。絶対pathや環境変数は出さない |
| `input_digest` | 固定profile、元のobjective、生成source pagesのdigest。元本文は出さない |
| `config_digest` | fixture、sample/warmup数、timeout、計測範囲のdigest |
| `attempts` | warmup/sample、exit code、失敗/拒否/timeout、wall ms、child peak RSS、既存VM/正しさの検証結果 |
| `summary` | warmupを除いたnearest-rank p50/p95。全sampleのwallと成功sampleのwallを分離 |
| `environment` | Python/SQLite/OS/CPU数と主要dependencyの実distribution version。lock digestはinstalled wheelの一致証明ではない |
| `missing` | 非対応/未計測値。RSSは非対応OSならUNSUPPORTED_PLATFORM、対応OSのcounter失敗はCOUNTER_UNAVAILABLE。一部欠測はPARTIALLY_MISSINGでscope.rss_samplesに件数と理由。成功sampleなしはNO_SUCCESSFUL_SAMPLE、PSS/heap/CPU/運用event-loop等は未計測 |

同じ入力の原文保持、ACK、訂正、restart、出典drift、独立reference結果は既存fixtureが検査する。
これは決定的reference処理の検証で、モデルの推論品質、利用者の成果、実provider、本番の受入ではない。
`LOCAL_PASS`はその範囲の意味。Taskの完了やPromotionを作らない。

wall timeにはPython起動、import、fixture作成、SQLite履歴生成、検証、cleanup、子の終了を含む。
RSSはLinux/macOSでchild自身がfixture/validation後に観測したhigh-water mark。
最後のJSON encode/exit、親processや全systemのRSSは含まない。warmup値は集計に使わない。

一つの失敗で後続を止め、未実行数を埋めない。終了コードは0=全sample PASS、1=sample失敗、
2=引数/同意/入力読取の拒否。childのraw stderrや不正JSONをreportへ反射しない。
code/inputが途中で変わった比較は`CODE_OR_INPUT_CHANGED`、同じ入力で結果digestだけが
異なる場合は`RESULT_CHANGED`とし、成功percentileを出さない。後者は入力digestを保持する。
試行開始後のI/O失敗は`BENCHMARK_IO_FAILED`で停止し、既済の試行とwall timeを残す。
コードの再確認ができないため、その場合も成功percentileを出さない。
最初のコード読取に失敗して試行を開始できない場合は、終了コード2の拒否となる。

## 比較と残る範囲

同じfixture/input/config、Python/SQLite、OS/CPU、同様のcache条件で比較する。
数sampleのp95はほぼ最大値になる。共有環境の外れ値をSLOや普遍的な速度とみなさない。
RSSの変化と出力bytes/VM work/入力保持を併せて判断し、品質を落として速くしたものを採用しない。
固定時間閾値をCI gateにせず、決定的な既存VM boundsと正しさを先に検査する。

knowledge/voice、常駐warm/cold、1k/10k/100k knowledge、段階別時間、p99、PSS/heap、
event-loop、長時間memory slope、cancel/drain、recorded replayはこのsliceに未実装。
このCLIのPASSを#331全体完了や全層対応へ読み替えない。

## 通常Taskの有限schedulerを計測する

Linux・Node 24では、既存の`TaskAdmission`をそのまま使う固定profileを選べる。
幅1/2/4と待機型・CPU型は同じ16 Tasksを使い、追加providerや依存は不要。

```sh
python -B tools/performance_benchmark.py --allow-local-fixture --fixture task-admission --width 1 --workload wait --samples 5 --warmups 1
python -B tools/performance_benchmark.py --allow-local-fixture --fixture task-admission --width 4 --workload cpu --samples 5 --warmups 1
```

`--width`は1/2/4（既定1）、`--workload`は`wait`/`cpu`（既定wait）。これらは
`task-admission`専用で、既存`swarm-short`の意味は変えない。Linux以外はこのprofileを
`PLATFORM_UNSUPPORTED`、Node不在は`NODE_UNAVAILABLE`として実行前に拒否する。

各Taskのactor/roomは異なる。waitは各40ms、cpuは各262,144回の固定整数演算で、
Python側の別方式の参照計算と全16結果を照合する。cpuは単一event loop内の同期処理であり、
幅を増やしてもCPU workerを追加しない。幅をまたいだinput/result digestの一致と、全Taskの
待機・実行・完了時間、throughput、初期待機数、実行中上限を返す。取消要求後の実処理終了までの
slot保持、queue超過拒否、writer barrierを同じschedulerで先に検査する。

外側Python observerがNodeの起動直前からexit/reapまでwallを測る。Linux `wait4`から
Node全期間のuser/system CPUとRSS high-waterを受け取るので、import・結果JSON化・終了も
対象になる。固定targetは**子を生成しない1 Node process**で、aggregate対象もその1 process。
Python observer・source事前確認・親の集計/保存は含まず、一般的なprocess tree観測器ではない。
各attemptに範囲・欠測を記録し、counter不明を0にしない。poll間隔の設定は最大5msで、
hostのscheduling遅延は別途加わる。

warmupを除いたnearest-rank p50/p95/p99と全試行を残し、一件失敗したら後続を停止する。
source/input/result/Node versionのdriftは比較を不成立にする。`qualification`は常に
`NOT_EVALUATED`。共有hostでの機構試験を静穏な比較やspeedupとみなさない。
観測負荷・静穏条件・PSS・event-loop lag・実Pipeline/owner/子worker・実provider費用・
CPU/RSS hard quota・通常Taskの取消/restart全体・既定幅の採用判断は#330/#331の残件。
