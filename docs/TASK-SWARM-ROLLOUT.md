# Task swarm rollout の段階的読取

対象: [#332](https://github.com/Kotodama-Project/Kotodama-project/issues/332)。
`runtime/task_swarm/codex.py` の runtime receipt 解決は、JSONL 全体を文字列と行一覧へ
複製せず、改行までの bytes を順に読みます。Task owner、receipt、完了判定、
明示された thread/turn と作業ディレクトリの照合は既存の経路を使います。
新しい履歴 cache や第二の正本は作りません。

## 読取契約

| 対象 | 上限・動作 |
|---|---|
| 子プロセス stdout | 既存 `MAX_STDOUT_BYTES`、16 MiB |
| 子プロセス stderr | 既存 `MAX_STDERR_BYTES`、1 MiB |
| 一つの rollout | 独立した `MAX_RUNTIME_ROLLOUT_BYTES`、16 MiB |
| 上限超過 | `runtime_rollout_limit`。切り捨てた成功を返さない |
| 読取中の追記・置換・消失・更新 | descriptor と名前の metadata を再確認し `runtime_rollout_changed` |
| 読取前の消失 | 従来どおりその候補を読めなかったものとして扱う |
| exact-record 再検証 | 呼出し元が保持する bytes を読み、path を開き直さない |

Windows では descriptor と path の stat が同じファイルにも異なる ctime を
返す場合があるため、時刻は各 API の読取前後の snapshot 同士を比較します。
descriptor と path のファイル identity は読取前後とも一致を要求します。読取 handle は
置換・削除を共有可能として開き、変更を黙認せず `runtime_rollout_changed` にします。
取消・上限超過などで読取が失敗した場合は、その元のエラーを保持します。
途中で generator を閉じる場合も、成功側と同様に変更を確認します。

16 MiB は既存 Task runner の rollout 再検証上限と合わせています。
これまで初回解決だけが巨大な履歴を読み終え、後段で拒否され得た状態を、
初回解決でも明示的に拒否します。stdout 上限の変更ではありません。

不正 UTF-8 は従来どおり置換して JSON を解釈します。LF、CRLF、CR と
`str.splitlines()` が扱う Unicode 区切りを維持します。末尾に改行のない完成した
JSON は読み、不完全な末尾 JSON は従来どおり無視します。後者を完成した turn と
見なすことはありません。複数 turn の曖昧さ、失敗記録、最後の context、
明示 turn の選択も同じです。

owner の取消 callback は各読取・各論理行で確認します。
探索では各ディレクトリ・各 entry・候補返却前にも確認します。既に渡された exact bytes
の外側の digest 再照合は Task runner が引き続き担当します。

## 合成測定

2026-10-10、Linux/Python 3.12.10。baseline は公開 commit
`b71ecf102e864ae5ac54db37891fb882d024b4ca` の `_runtime_receipt`。
同じ metadata と最終 completion の間に約 512 bytes の無関係な JSON 行を置き、
1/10/100 MiB のファイルを作りました。両実装の前準備を揃え、各標本を新しい
プロセスで測定しています。共有ホスト上の観測値であり SLO ではありません。

各欄は baseline → 今回。1/10 MiB は 5 回、100 MiB baseline は 1 回のみです。
5 回の p95 は最大値であり、安定した本番 percentile を推定できません。

| 入力・経路 | p50 / p95 (ms) | 最大 process RSS (MiB) | 読んだ rollout bytes |
|---|---|---|---|
| 1 MiB、path | 11.34 / 29.14 → 17.77 / 41.45 | 21.38 → 21.38 | 両方 1,048,576 |
| 10 MiB、path | 99.62 / 223.81 → 124.88 / 139.30 | 39.64 → 21.38 | 両方 10,485,760 |
| 10 MiB、exact bytes | 96.53 / 170.44 → 155.96 / 203.51 | 49.57 → 28.82 | 両方 0（入力 bytes は事前保有） |
| 100 MiB、path | 2,201.31（1 回）→ 0.58 / 0.78 | 230.01 → 21.38 | 104,857,600 → 0 |

100 MiB の今回結果は成功ではなく `runtime_rollout_limit` です。読取量は別の
instrumented pass で数え、時間の測定にはその計測処理を入れていません。
RSS は import・前準備も含む process の high-water mark です。
10 MiB path の測定区間の RSS 増分は baseline 最大 18.29 MiB、今回 0 MiB でした。
小さい入力では前準備の high-water mark に隠れるため、0 を割当てゼロと解釈しません。

この測定で確認した改善は全履歴の重複保持の削減です。行ごとの処理が増え、
p50 が遅い条件もあるため、一般的な高速化を達成したとは主張しません。

無関係な session file を 1,000 / 5,000 件加えた条件でも、本文を開いた候補は
1 件、読取量は 1 MiB でした。path 解決全体の今回 p50/p95 はそれぞれ
27.50/37.39 ms と 28.43/44.40 ms。従来は 11.80/12.69 ms と 19.83/37.40 ms。
この旧測定は recursive glob 時点の記録です。以下の探索変更の測定とは合算しません。

10 MiB 入力で 20 回目の取消確認時に停止する合成試験は、5 回の p50 0.17 ms、
p95 0.61 ms でした。これはローカルファイル・解析中の確認であり、遅い filesystem、
探索中、ブロックしている OS read に対する取消期限ではありません。

## 探索のメモリと取消

履歴探索はディレクトリを一つずつ `scandir` で開き、無関係な file entry を
一覧に保持せずに進めます。開いている iterator は常に一つで、取消・列挙失敗でも
閉じます。開始前に消えた、またはディレクトリでなくなった path は従来どおり
読み飛ばします。それ以外の open/entry 分類失敗や途中の列挙失敗は
`runtime_discovery_failed` として明示的に拒否します。可読な別候補だけで成功を
返しません。このエラー時の拒否は、従来の best-effort な読み飛ばしより厳格です。
ディレクトリ symlink は再帰せず、file symlink は従来どおり root 内に解決するもの
だけを使います。解決済み path の `normcase` による重複除外と `sorted(Path)` 順は
維持し、複数候補の最後の context/completion と最初の有効 receipt path を変えません。
exact-record は探索を省略します。新しい cache や任意の件数上限は追加しません。

合成の無関係な空 JSONL 10,000 / 40,000 件と、一致する 439-byte の完了記録 1 件を
同じディレクトリに作成しました。Linux/Python 3.12.10、比較元は
`64771158b3e2e587130c62b01e939a73023cb854`。各標本は別 process、両経路の
関数準備を揃え、各 1 回 warm-up 後に交互順で 5 回計測しました。
p95 は 5 標本中の最大値で、本番 percentile や SLO ではありません。
各欄は recursive glob → 今回です。

| 無関係な file 数 | 解決 p50 / p95 (ms) | process 最大 RSS (MiB) | 既に要求済みの取消 p50 / p95 (ms) |
|---|---|---|---|
| 10,000 | 10.18 / 13.07 → 6.01 / 7.89 | 19.30 → 19.30 | 8.76 / 12.54 → 0.20 / 0.26 |
| 40,000 | 33.46 / 39.05 → 21.40 / 37.59 | 26.38 → 19.30 | 33.96 / 51.63 → 0.22 / 0.30 |

全成功結果は同一です。別の instrumented pass では、40,000 件のときに
列挙した entry が 80,002 → 40,001、directory scan が 2 → 1、読んだ本文は
双方 439 bytes でした。この条件では解決時間・RSS・取消応答が改善しました。
対象は一つのディレクトリの小さな完了記録であり、すべての履歴や本番での
高速化を保証しません。最大 RSS は import/準備も含み、小さい入力ではその床に隠れます。

取消は cooperative です。OS の `scandir`/`stat`/path 解決自体の block、最後の
候補 sort、一つの callback 自体に時間上限はありません。directory frontier と
一致候補、解析で保持する turn/context の総量にもまだ上限はありません。
したがって一定メモリや総履歴 budget、全段階の取消期限は未達です。
探索の確認粒度は各 entry、解析は独立した 16 MiB/file の上限です。
既存の解析上限超過は引き続き明示的に拒否し、途中成功を返しません。

## 確認と残る境界

必要な依存は既存の `requirements-task-swarm-ci.txt` に従います。

```sh
python -B -m pytest -q -p no:cacheprovider \
  tests/test_task_swarm_rollout_streaming.py \
  tests/test_task_swarm_rollout_discovery.py \
  tests/test_task_swarm_codex.py \
  tests/test_task_swarm_runtime_evidence.py
```

回帰試験は UTF-8、全改行種別、巨大な一行、不完全な末尾、複数 session/turn、
取消、read 中の変更、exact bytes、100 MiB の本文未読拒否を検査します。

- メモリは最大の LF 区切り行と保持する turn/context 数にも依存します。
  巨大な一行は 16 MiB 内なら読みます。すべての入力で一定メモリにはなりません。
- 複数の一致候補を探索・集約する総量は今回の上限の対象外です。
  差分探索、総候補数・総読取量の上限、総履歴 budget は #332 に残ります。
- 本番 rollout の採用・復元・自動削除は実施していません。ローカル合成 PASS は
  live acceptance、Promotion、Current Truth を意味しません。
