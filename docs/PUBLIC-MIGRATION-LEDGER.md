# Public Migration Ledger

公開移行台帳は、移行対象ごとの **disposition（処遇）** を、追記専用・改竄検知可能な
形で公開側に記録するための契約です。移行そのものを実行するものではなく、素材を
公開するものでもありません。記録されるのは opaque な参照、digest、gate 結果、
集計だけです。

- Schema: `schemas/public-migration-ledger.schema.json`
- Verifier: `tools/validate_public_migration_ledger.py`
- Tests: `tests/test_public_migration_ledger_contract.py`
- Fixture: `tests/fixtures/public-migration-ledger/valid.jsonl`
- Ledger location: `migration/public-migration-ledger.v1.jsonl`（現在は未作成。
  `migration/README.md` を参照）

## なぜ語彙を分けるのか

移行の議論では「最終的にどう分類したか」と「もし実行するならどう移すか」が
混ざりやすく、混ざったままでは *unclassified が 0 件である* ことを機械検証
できません。この契約では次を別フィールドとして持ちます。

| フィールド | 意味 | 値 |
|---|---|---|
| `terminal_classification` | 唯一の終端分類 | `PUBLIC_EXTRACT` / `PRIVATE_RETAIN` / `REGENERATE` / `DROP`、または blocked 中は `null` |
| `transfer_mode` | 実行するとした場合の移送機構 | `REAUTHOR` / `GENERATE` / `NO_COPY`、または `null` |
| `proposed_action` | 提案された行為への opaque 参照 | `ref/...` または `null` |
| `supersession_reason` | 後続に置き換えられた理由 | 列挙値または `null` |
| `status` | 手続き上の状態 | `BLOCKED` / `PROPOSED` / `ACCEPTED` / `REJECTED` |

`RE_AUTHORED`、`PUBLIC_REAUTHOR`、`SUPERSEDED` のような語は移送機構または
置換理由であり、終端分類ではありません。verifier は片方の語彙をもう片方の
フィールドに入れることを拒否します。

## 公開安全性

- すべての識別子は `ref/...` 形式の opaque 参照です。private path、repository
  path、URL、provider handle、host、参加者識別子は schema が拒否します。
- private な証跡は `private_receipt_ref` と `private_receipt_digest` の組でのみ
  参照します。参照を解決するには、この台帳が持たない private authority が必要です。
- 記録は素材そのものを持ちません。台帳は「何をどう処遇したか」の metadata です。

## 追記と改竄検知

各行は 1 レコードの JSONL です。

- `sequence` は 1 から始まり、欠番なく連続します。
- `prev_hash` は直前レコードの `content_hash` で、先頭レコードは 64 個の `0` です。
- `content_hash` は、`content_hash` を除いたレコードを
  `sort_keys=True` かつ区切りを `(",", ":")` にした UTF-8 の canonical JSON へ
  符号化した SHA-256 です。追記時は
  `tools/validate_public_migration_ledger.py` の `canonical_content_hash()` を
  唯一の実装として使います。
- レコードを 1 件削除・並べ替え・改変すると、そこから先の連鎖が壊れます。

## Gate の一貫性

`gates` は 5 つの独立した gate 結果（`license_provenance`、`secret_scan`、
`history_scan`、`dependency_baseline`、`independent_review`）を持ちます。

- `ACCEPTED` は全 gate が `PASS` のときだけ許されます（`GATE_BYPASS`）。
- `BLOCKED` は少なくとも 1 つ非 `PASS` の gate を必要とします。
- `FAIL` を含むレコードは `PROPOSED` や `ACCEPTED` に留まれません。
- `DROP` は `NO_COPY` を、`REGENERATE` は `GENERATE` を要求します。
- `supersession_reason` は `REJECTED` のときにだけ記録できます。

## 実行

```
python tools/validate_public_migration_ledger.py migration/public-migration-ledger.v1.jsonl
```

成功時の出力は次の形です。

```json
{
  "contract": "kotodama.public-migration-ledger/v1",
  "result": "LEDGER_CONSISTENT_UNVERIFIED",
  "reason_codes": [],
  "record_count": 5,
  "terminal_classification_counts": { "...": 0 },
  "zero_unclassified": false,
  "public_beta": "NO_GO_UNPUBLISHED"
}
```

## この検証が意味しないこと

`LEDGER_CONSISTENT_UNVERIFIED` は、記録された処遇が構造的・内部的に整合して
いることだけを示します。移行が実行されたこと、private 側の継続性、公開抽出物の
公開、依存関係の切り替え、rollback の予行、独立検証、Human Decision、Promotion、
Current Truth、Public Beta GO のいずれも意味しません。verifier の出力は claim を
すべて `false` として返し、`public_beta` は常に `NO_GO_UNPUBLISHED` です。

`zero_unclassified` が `true` になっても、それは「blocked のまま分類されていない
レコードが台帳に無い」ことだけを示します。台帳に載っていない対象があるかどうかは、
この契約の範囲外です。
