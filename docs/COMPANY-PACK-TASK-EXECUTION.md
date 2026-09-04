# Task に結び付いたローカル Company Pack 作成

`tools/run_company_pack_task.py` は、既存の `create_company_pack.py` を使って
実際の Company Pack を作り、別 Python プロセスの validator とファイルの
SHA-256 読取結果をローカル operation receipt に結びます。
README の「仕事を進め、成果物と検証証拠を残す」経路の小さな実装です。

対象操作は `CREATE_COMPANY_PACK` 一つだけです。Task の作成・状態変更・完了判定、
任意コマンド、agent dispatch、外部送信、provider、配備、Promotion は扱いません。
既存 Task の owner が receipt を読んで次の判断を行います。ここに新しい Task
台帳は作らず、completed の fixture Task も書き換えません。

## 手元で使う

Python 3.12 と Git を使います。追加依存のインストールは不要です。
以下は、operator が選んだ**既存の三つの record ファイル**を読み、入力 snapshot と
request を作る例です。`work/company-pack-inputs/` の Task / Work Order / capability は
事前に owner が用意した、この後の local adapter 条件に合う候補とします。
この準備コードも executor も、その record を作成・変更・承認しません。

```python
import json
import hashlib
import subprocess
import sys
from pathlib import Path

record_root = Path("work/company-pack-inputs").resolve()
records = {}
entries = {}
for name in ("task", "work_order", "capability"):
    path = record_root / (name + ".json")
    raw = path.read_bytes()
    records[name] = json.loads(raw)
    entries[name] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
task, work_order, capability = (records[name] for name in ("task", "work_order", "capability"))
target = work_order["target"]
output_root = Path(target["output_root"])
assert output_root.is_absolute() and output_root.is_dir()
source = json.loads(subprocess.check_output([
    sys.executable, "-B", "tools/run_company_pack_task.py", "--source-binding"
]))
assert work_order["candidate_revision"] == source
binding = {
    "kind": "company_pack_existing_record_binding", "version": "1.0",
    "owner_ref": task["owner_ref"], "task_updated_at": task["updated_at"], "records": entries,
}
Path("work/company-pack-binding.json").write_text(
    json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
request = {
    "kind": "company_pack_task_request",
    "operation": "CREATE_COMPANY_PACK",
    "operation_key": target["operation_key"],
    "task_ref": "task:" + task["task_id"],
    "work_order_ref": "work-order:" + work_order["work_order_id"],
    "capability_ref": "capability:" + capability["grant_id"],
    "authorized_output_root": str(output_root),
    "source": source,
    "pack_id": target["pack_id"],
    "human_intent_ref": target["human_intent_ref"],
    "authority_expires_at": work_order["expires_at"],
    "retention_policy_ref": target["retention_policy_ref"],
}
Path("work/company-pack-request.json").write_text(
    json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(output_root)
```

表示された絶対パスを `OUTPUT_ROOT` に入れ、このローカル出力への書込を明示します。

```text
python -B tools/run_company_pack_task.py work/company-pack-request.json --record-binding work/company-pack-binding.json --authorize-local-output-root "OUTPUT_ROOT"
```

成功時の生成先は
`OUTPUT_ROOT/OPERATION_KEY/pack/`、検証記録は同じ operation directory の
`receipt.json` です。`manifest.json`、9 Blocks、9 Records、3 MOCs と説明文を実際に
生成します。生成物は draft、参照は静的な入力です。

`--authorize-local-output-root` は**呼出者による今回のローカル書込指示**です。
request 内の root と一致する既存のローカル絶対パスが必須です。
Work Order / capability / Human Intent / retention の文字列を、認証済み承認や
検証済みポリシーとして扱いません。外部の権限を暗黙に引き継ぎません。

## 既存 record への小さな local adapter

`--record-binding` は operator が request と別に選ぶ読取入力です。三つの実ファイルの
絶対パス、SHA-256、期待する Task の `updated_at`、owner を持ちます。生成の前後で
読取り、IDs・相互参照・現在 bytes を照合します。保存済み owner / receipt にも binding
digest を固定し、再開時の record 差替えを拒否します。各入力は64 KiB以内です。
存在しないファイルや `task:does-not-exist` のような ID は、Pack 作成前に失敗します。

Task は既存の `kotodama.task-record` v1 / `KTP-TASK-NNNN` の候補形式を使います。
`active` または `validating`、`blocker.kind=none`、owner と `updated_at` の一致が必須です。
`waiting_human`、`completed`、`closed` を再実行可能とは扱いません。この adapter が認識する
`scope.in_scope` は `['CREATE_COMPANY_PACK', 'output-root:ABSOLUTE_ROOT']` の二つだけです。
`out_of_scope` は `['external_write', 'task_state_change', 'promotion']` に限定します。
public adoption などの自由文からローカル生成の権限を推測せず、矛盾や未知の scope 文を
受け入れません。既存 record の意味を自動翻訳する機能ではありません。

Work Order と capability は Company starter の `work-order-candidate.json` /
`capability-grant-candidate.json` が要求する全フィールドを使う**ローカル instance profile**です。
加えるフィールドは `kind`（template の artifact 値）、`record_status=CANDIDATE_ONLY`、
`status=active` です。これは既存 canonical instance schema の採用や authority 発行ではなく、
この CLI が読む候補の限定形式です。`decision_ref` / `authority_evidence_ref` は未認証の
関連参照として一致だけを検査し、Human approval の検証とは主張しません。

両 record の `target` は次の閉じた object が同一である必要があります。

```text
task_ref, task_revision (= Task file SHA-256), owner_ref, operation_key,
output_root (= absolute root), pack_id, human_intent_ref, retention_policy_ref
```

Work Order の action は `CREATE_COMPANY_PACK`、candidate_revision は request の source、
effects は `['create_local_draft_pack_and_operation_receipt']` に限定します。
capability の work_order_ref と subject_ref は Work Order と Task owner に一致し、
allowed_actions は `['CREATE_COMPANY_PACK']`、denied_actions は
`['external_write', 'task_state_change', 'promotion']` だけを受けます。issued_at は未来ではなく、
双方の expires_at は request と一致する未来時刻です。非空の rollback / stop_conditions も必須です。

実際の候補ファイルを使う local example は次で再現できます。

```text
python -B -m unittest discover -s tests -p test_run_company_pack_task.py -k real_cli -v
```

この例は隔離した一時 directory に **synthetic KTP-TASK-9001**、Work Order、capability の
候補ファイルを用意し、CLI にその実パスと digest を渡し、Pack と receipt の実生成と
三 record の不変性を検証します。同じ test file の replay / crash test も実ファイルを使います。
実在する公開統合待ち Task や完了 Task を流用した成功例ではありません。

## 入力と再開

- 入力は閉じた JSON object です。余分なキー、重複キー、不正な識別子、
  secret-like な入力を拒否します。request の上限は 64 KiB です。
- source は Git HEAD と、starter 全ファイルおよび generator / customization checker /
  validator / executor の**現在 bytes**から得た SHA-256 に一致する必要があります。
  dirty な source を clean commit と偽装する値ではありません。revision と digest を
  一組で使い、commit や source の変更後は新しい request / operation key を使います。
- intent、Block の authority expiry、Record の retention policy だけを許可された
  customization とします。expiry は現在より先、30日以内です。検証終了時にも再確認します。
- root の下に operation key の専用 directory を新規作成し、`owner.json` に request
  とその digest を固定します。操作用 OS lock は同時実行を拒否し、process crash で解放されます。
  operation key の一意性はこの root 内です。複数 root にまたがる Task の重複実行防止は
  既存 Task owner が担当します。
- 同じ key と異なる入力、別 owner、既存の無関係な target、path escape、symlink、
  junction / reparse point、hardlink、network root、期限切れは拒否します。
- Pack は最大64ファイル・合計1 MiB、directory を含め最大128 entries です。
  validator は固定コマンド、30秒の上限付きで起動し、stdout / stderr の内容を
  エラーへ反射しません。生成前後で source を再照合します。
- 生成後は validator と前後の byte readback に加えて、元 starter に許された
  customization だけが入ったことを確認します。未確認の追加ファイルを受け入れません。

生成後、receipt 作成前に process が終了した場合は、**同じ request と同じコマンド**を
再実行します。所有 binding が一致した Pack を観測・検証して receipt を作ります。
generator を再実行しません。receipt が既にあれば現在 bytes と一致することを
再確認し、保存済み receipt を変更せず返します。`observed_at` は保存時刻のままです。

Pack が不足・破損している、owner / receipt の書込が途中で切れている、または
検証に失敗した場合は `INCOMPLETE_OR_REFUSED` と固定 error code を返し、途中の
ファイルを残します。自動削除、上書き、blind retry はしません。必要なら内容を確認して
別の operation key で新規作成し、旧 directory の扱いは owner が判断します。
CLI の終了コードは成功 `0`、拒否・未完 `1`、引数形式エラー `2` です。

## 証明の範囲

receipt の `LOCAL_PASS` は、この入力に対応するローカル draft の実生成、独立した
validator process、選択された三 record の存在・scope・revision 照合、byte digest の証拠です。receipt 自体は署名や
protected attestation ではありません。Task 状態、Human approval、retention の採用、
Promotion、Current Truth、Public Beta を証明しません。`claims` はすべて false、
`task_state_changed` は false、`NO_GO_UNPUBLISHED` を維持します。

同じ OS user が信頼されたローカル directory を管理する single-writer 用です。
record の信頼元は operator が明示選択したローカルファイルです。第三者が偽造した record と
manifest の組を暗号的に排除する機能ではなく、global Task registry や Human identity を照会しません。
所有 marker と cooperative OS lock は、悪意ある別プロセスによる directory 差替えや
marker 偽造を隔離する sandbox ではありません。process crash の再開は検証しますが、
電源断時の filesystem durability、multi-host、削除・retention worker は未対応です。
ローカル request / owner / receipt は内部参照や絶対パスを含むため、そのまま公開しません。

## 検証

```text
python -B -m unittest discover -s tests -p test_run_company_pack_task.py -v
python -B -m unittest discover -s tests -p test_create_company_pack.py -v
```

実 subprocess の生成直後 `os._exit`、再開時の生成抑止、byte drift、部分結果の保持、
既存 Task の非変更、引数による明示権限、期限切れ、source drift、別 owner、lock 競合、
link と未所有ファイルの拒否を検証します。symlink 作成権限がない環境ではその実試験は
skip として明記します。従来 generator CLI の失敗時 cleanup の既定動作は変えず、
executor だけが keyword-only の `preserve_incomplete=True` を渡します。
