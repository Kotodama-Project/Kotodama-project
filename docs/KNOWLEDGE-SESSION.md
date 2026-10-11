# 知識 CLI の反復読取

小さな検索・本文読取を繰り返す場合は、明示的に起動する
[knowledge_session.py](../tools/knowledge_session.py) で最初の解析結果を再利用できます。
[単発 CLI](KNOWLEDGE-BASE.md) の `query` と `show` と同じ parser・実行処理を使い、
同じ引数・出典・監査時刻に対する `result` は単発 CLI の JSON と一致します。
SQLite 索引は必要ありません。通常の単発 CLI もそのまま使えます。

## 起動と形式

```bash
python tools/knowledge_session.py --root . --max-requests 2 <<'JSONL'
{"id":"find-goal","args":["query","KGI","--goal","OUT-INTENT","--limit","3"]}
{"id":"read-goal","args":["show","project/goal","--section","Required properties","--max-chars","1000"]}
JSONL
```

要求は UTF-8 JSON 1 行、応答も JSON 1 行です。stdout には応答だけを出します。
成功は `{"id":"find-goal","ok":true,"exit_code":0,"result":{...}}`、
拒否は `{"id":"find-goal","ok":false,"exit_code":2,"error":"CODE"}` です。
不正な JSON などで ID を取得できない場合、`id` は `null` になります。
拒否応答は部分的な検索結果・本文・parser の診断文を含みません。
クライアントは `ok` を確認してから `result` を利用してください。

`args` は `query` または `show` から始めます。`--json` は自動で指定されます。
`--goal`、`--kgi`、`--initiative`、`--section` などは単発 CLI と同じです。
未知の Goal は `QUERY_REFERENCE_UNKNOWN` として拒否します。
再現用の時刻は要求ごとに `--as-of` で指定できます。省略時は要求を受けた時点の
UTC を新たに取得します。過去時刻を指定する監査結果は現在時刻の結果と区別します。

開始時の `--root` は必須で、セッション中に別の root へ変更できません。
同じ root を指定する `show` の `resume_args` は次の要求の `args` にそのまま渡せます。
継続の `--expected-digest`、Unicode 文字単位の offset、出典変更時の拒否も維持します。
オプション名の省略形は受け付けません。

## 出典の変更と鮮度

解析済み bundle を使う前に、既存の reader で全入力の実バイトを再読込・照合します。
対象は knowledge の Markdown/YAML、schema、参照される repository 内の出典です。
同じサイズ・mtime の訂正、ファイルの追加・削除・移動も検出対象です。
差分があれば古い bundle を捨てて再解析し、無効な入力は拒否します。
読み取れない出典や、digest を固定した出典の変更を古い結果で埋めません。

毎要求で `stale_after` と監査時刻を再評価し、解析時の `is_stale` を使い回しません。
取消・非公開設定・Goal filter・表示可能性は、現在の bundle と既存処理で判定します。
成功 JSON を最後まで生成してから、応答を返す直前にも全出典の実バイトを再照合します。
処理中に訂正を検出した要求は `SOURCE_CHANGED_RELOAD_REQUIRED` で拒否します。
これは既存 CLI と同じ検査境界であり、検査後のファイル変更を禁止するロックではありません。

反復読取が償却するのは Python 起動と YAML/schema 解析です。全出典の読込と hash、
候補の検索は各要求で継続するため、入力数・入力バイト数に比例する仕事は残ります。
mtime だけを見て検査を省いたり、索引を新たな正本にしたりはしません。

## 有限の実行と適用境界

| 境界 | 上限・動作 |
|---|---|
| 要求サイズ | 改行を含む UTF-8 16 KiB。超過時は 1 件を拒否して終了し、残りを無制限に読み捨てない |
| 応答サイズ | 改行と envelope を含む UTF-8 256 KiB。超過時は結果を出さず拒否 |
| 要求の構造 | `id` は 1〜64 文字、`args` は 1〜64 個、各引数は最大 4096 文字。重複キーは拒否 |
| 要求数 | 既定・最大 256 件。`--max-requests` は 1〜256。到達時または EOF で終了 |
| 並行性 | 処理中 1 件、要求処理に渡す行は最大 1 件。次要求の解析・admit・queue は行わない |
| キャッシュ | 解析済み bundle は 1 世代のみ。要求・応答・過去世代の履歴を蓄積しない |
| 出典 | 既存の 256 files / 合計 8 MiB / 1 file 1 MiB などの reader 上限を維持 |

上限件数に達したプロセスへ追加送信せず、必要ならクライアントが新しく起動します。
OS と Python の有限な raw byte buffer には後続行のバイトが入る場合があります。
これは解析・admit された要求の pending queue とは区別します。
構造とバイトの上限は無制限な蓄積を防ぎますが、Python の一時 object や JSON 化を
含む固定の RSS 上限、処理時間の上限を保証するものではありません。
埋め込み用の `KnowledgeSession` は同時呼出しを受ける API ではありません。

これは read-only の明示 stdio 入口であり、背景常駐、network/provider 操作、Task の作成・
実行、Current Truth の更新、公開・承認を担いません。出力の authority は既存の
`projection_only` のままで、Public Beta や `NO_GO_UNPUBLISHED` の境界を変更しません。

採用判断では同一入力・同一時刻の単発 CLI と 30 回以上交互に実行し、結果の一致、
実読込バイト数、初回起動、warm の p50/p95 と RSS を記録します。
warm の p50 と p95 が両方とも単発の 1/2 以下であることが #348 の性能受入条件です。
出典検査を外して条件を満たす変更は受け入れません。
