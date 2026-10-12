# 任意指定のrepository unittest runner

#331の速度・debug候補です。**全体性能は未評価で、必須CIは従来の
`python -m unittest discover -s tests -v` を使います。** この入口のPASSは
当該suiteの技術結果であり、速度改善、実モデル品質、本番運用の受入ではありません。

```sh
python -B tools/run_repository_tests.py --root . --output /tmp/kotodama-tests-one
python -B tools/run_repository_tests.py --root . --workers 2 --output /tmp/kotodama-tests-two --timeout 1200
```

現candidateはLinuxの`/proc`と所有process groupを使います。他OSでは実行前に
`PLATFORM_UNSUPPORTED`で拒否し、標準unittestを使います。既定は1 worker。
sourceはcommit済みのclean Git checkout、outputはその外の新directoryを指定します。
provider、追加依存、費用、Task owner、CI workflowを変更しません。

## 発見・実行・実結果

対象は固定の`tests/`、`test*.py`です。test filterやskip追加はありません。
所有子processでcanonical discoverを行い、全ordered occurrenceのIDと同IDのordinal、
class/module、連続module blockを親のplanへ保存します。duplicate IDをdedupしません。
各workerは同じsourceから再discoverし、全plan一致を実行前に要求します。
import失敗は標準loaderの`_FailedTest`として実行して非0にし、他caseを消しません。

1 workerはdiscoverの元suite objectをそのまま実行します。custom suiteのrunがiterationと
違う順序を選んでも、その実順序を保持し全ID＋ordinalのmultisetを照合します。
実setup拒否と未開始caseの対応が一意の場合だけblockedへ照合します。同scopeに
再入場してcaseを開始した後は古い拒否を使いません。複数候補・範囲が特定できない
custom fixtureや説明できない省略・追加はINCOMPLETEとし、2 workerでは使いません。
2 workerはdefining moduleの
全blocksを一つのshardへまとめ、case数の大きいmoduleから現在の小さいshardへ
決定的に割り当てます。各連続blockでmodule/classのteardown・再入場を維持します。
A/B/Aやsetup失敗は、後のAまで勝手に省略しません。custom suite・`load_tests`は
1 workerで保持し、2 workerでは`PARALLEL_UNSUPPORTED`として拒否します。

workerごとにtracked sourceのGit cloneとprivate TEMPを使います。共有のinterpreterは
読取りで使用し、dependencyをコピー・installしません。別module間の任意の外部資源や
順序依存が並行で安全だとは証明していません。全suiteの厳密比較が採用前の条件です。

raw stdout/stderr、event JSONL、worker result、source/runner/environmentのplan、
起動引数、memory samples、summaryをoutput内に保持します。error、failure、skip理由、
expected failure、unexpected success、subtestの実IDとtracebackを保存します。
setup拒否は実fixture error/skipへ結び付け、各planned occurrenceをblockedとして記録します。
親はraw eventsとID＋ordinalの全件・status/count、block内sequenceと実outcomeの
存在・順序を照合し、未知/重複/欠落を拒否します。start/stopだけを成功と推定しません。
反復subtestや実cleanupの複数errorは保持し、成功と失敗の矛盾を拒否します。
壊れたtail、crash、result欠落でもvalid event prefixとraw logを残します。
JSONは重複keyを拒否し、saved plan/resultは16MiB、eventは1行1MiB・各worker64MiBを
読取り上限にします。超過は非0で停止し、caseを省いて成功扱いにしません。これらは読取上限であり、
childが書くraw.log/discovery.log/event writerや全disk使用量のhard boundではありません。
raw書込みは時間制限とcleanupで止めるだけで、停止までの超過もあります。

終了値は0=全case成功、1=実test failure/error/unexpected success、2=拒否・中断・
不完全な実行です。summaryの`qualification`は常に`NOT_EVALUATED`です。
失敗outputを削除して同じdirectoryで再試行せず、別runで原因と証拠を扱います。

## 時間・所有子・measurement

最大1200秒のdeadlineはdiscovery import、worker起動と実行を含みます。
SIGINT/SIGTERMまたはtimeout時は所有子groupへTERM/KILLを送り、wait/reapします。
Linux subreaperはこのorchestrator processだけに設定し、detachして再親化された所有子も
確認します。cleanup不完全、未知ownership、source/環境driftをPASSにしません。

RSSはsource/environment事前確認後からcollector/worker cleanupまでに観測した
orchestratorと所有process treeの合計のsampled peakです。起動import・事前確認・
結果集計・summary保存を含む全invocation peakではありません。summaryにもこのphaseを
明記します。この値を全invocationのqualificationへ流用しません。
20msはscan後の
待機目標で、実周期やhard boundではありません。短命の未観測子を逃す限界があります。
親/起動したcollector・workerの観測欠落は非0であり、欠測を0の成功値に置換しません。
CPUは親自身とOSが記録したreaped childを分け、worker側のCPUも別に残します。
worker CPUを親のreaped-child値へ重ねて加算しません。未確定runの値は完全測定ではありません。
環境はPython identity、dependency name/version、元環境とworker TEMPのdigestに束縛します。
dependency実bytesを全てattestするものではなく、環境変数のplaintextも出しません。

## 採用する前の条件

短いfixtureのPASSや実processの重なりは全suiteのspeedupではありません。
新固定source/environmentで、独立レビュー・全occurrence/label preflight・静穏条件を経て
A1→B1→B2→A2を全て完走し、原#331の厳密outcome比較を通します。
median wall短縮15%以上、worst B/A≤1.10、aggregate sampled peak RSS≤2.5倍が必要です。
RSS gateには全invocationの集計・保存・終了までを含む別の固定observer/harnessが必要で、
このrunnerの部分phase値だけでは受入を証明しません。
A1/B1で厳密不一致があれば停止し、rawを保存します。失敗/部分runを採用しません。
旧ABBAの中断結果や局所fixture改善率をこのcandidateの性能へ転用しません。
必須workflowの変更は、このqualificationと別の採用判断が成立してから扱います。
