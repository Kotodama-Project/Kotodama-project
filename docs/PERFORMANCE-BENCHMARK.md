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
code/inputが途中で変わった比較はFAILとし、成功percentileを出さない。

## 比較と残る範囲

同じfixture/input/config、Python/SQLite、OS/CPU、同様のcache条件で比較する。
数sampleのp95はほぼ最大値になる。共有環境の外れ値をSLOや普遍的な速度とみなさない。
RSSの変化と出力bytes/VM work/入力保持を併せて判断し、品質を落として速くしたものを採用しない。
固定時間閾値をCI gateにせず、決定的な既存VM boundsと正しさを先に検査する。

knowledge/voice、常駐warm/cold、1k/10k/100k knowledge、段階別時間、p99、PSS/heap、
event-loop、長時間memory slope、cancel/drain、recorded replayはこのsliceに未実装。
このCLIのPASSを#331全体完了や全層対応へ読み替えない。
