# 出典検査のパス計算だけを軽くする再現実験

`_capture_inputs` は、毎回の全出典読取と実バイトのhashを維持します。
この候補が変えるのは `Path.relative_to` による純粋な相対パス計算だけです。
同じ種類のPathでrootの各componentが完全一致する場合は同じ相対名を直接作り、
それ以外は従来の `relative_to` に戻します。空root、別anchor、Windowsの大小文字や
drive/share差はfallbackで既存の判断を保ちます。

毎fileの `resolve`、その後のroot内検査、directoryの列挙、通常file判定、全stat、
open/read、hash、bytes/file数の上限、最終応答前の照合はそのままです。
知識の正本、Source/Decision/Promotion、admission256files/8MiBは変更しません。
mtime cache、ディレクトリcache、非同期更新、追加の索引は導入しません。

性能比較は `knowledge_source_capture_benchmark.py` で行います。公開基準commitは
`a3fe774bb44f604b1591fe3577b836c44b92229b` です。計測時の基準と
`_capture_inputs` の関数本体・foundation全体・知識CLIの全moduleが同じbytesであることを
確認済みです。このcommitから元の関数だけを取り出し、それ以外のhelper、parser、
検査処理、bundle入力は現在のcheckoutを両armで共有します。公開基準commitでは
`docs/PROJECT-MAP.md` のbytesが元の計測入力と異なるため、関数の同一性と入力の同一性は
区別します。過去の30sample測定は元の50Concepts/84sourcesの記録として保持し、
公開commit上の新しい入力で同じ値が出るとは主張しません。
計測前の独立inventoryで現在のadmitted入力を全bytes照合し、file数・bytes数・source digestを
一度だけ確定します。両armの全応答を同じfile/byte数、query3回/show4回の固定guard数と
比較し、全計測後にも元inventoryの出典を再照合します。inventoryは計測時間に含めません。
現在のfixture情報は結果JSONへ出力します。
基準の元関数と候補関数を同じPython process・同じ実bundle・同じ `session.main` の有限JSONL経路で
交互に使い、query4条件/show2条件を各engine30回ずつ測ります。
各sessionはwarmup2+測定60=62要求で既存256件上限内です。
入出力のバイトとguard回数を全応答で比較します。wall/CPUは要求取得から完成済み
応答のwriteまで、IPCと比較用hashは除外します。既存query3回、show4回の全source検査を
削減せず、OS page cacheはflushしません。shared hostの結果であり本番SLOではありません。

事前条件は全caseでwall p50/p95が10%以上改善、CPU p50が10%以上改善、全結果と
source bytes/count一致です。条件を満たさなければ候補を採用しません。
percentileはnearest-rankです。profileのnested timingと非profiled比較は区別します。
全fileの列挙・bytes再読込と、既存のsort・path解決の仕事は継続します。
O(1) freshnessを主張しません。

別途、実subprocessのIPCを含めた独立測定では、全6条件の中央値が26.2–46.1%短縮しました。
一方、日本語queryのp95改善は3.5%に留まり、実CLIの全条件で10%以上という目標は未達です。
初回応答の改善も観測していません。元の不変snapshot/index案は不採用のままで、
この相対パス計算の限定改善を#349全体の完了とは扱いません。

```text
python -B -m unittest discover -s tests -p test_knowledge_source_capture.py -v
python -B -m unittest discover -s tests -p test_knowledge_session.py -v
python -B experiments/knowledge_source_capture_benchmark.py > benchmark.json
```

POSIX/Windowsパス規則は同じPurePathモデルで照合します。native Windowsの実行速度は
このLinux実験では証明せず、採用時の既存Windows CIへ委ねます。
