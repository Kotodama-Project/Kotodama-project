# Public Preview Self-check

`check_company_pack_public_preview.py` は、公開 Company starter または自分の
作業 copy を、外部接続なし・書き込みなしで一度に確認するための小さな
read-only CLI です。個別に validator、Catalog、customization checker を
呼び出す順序を覚えなくても、公開 preview の現在地を決定的な JSON へ
まとめられます。

## Quick start

repository root から、公開 example を確認します。

```powershell
python tools\check_company_pack_public_preview.py examples\company-starter
```

```bash
python3 tools/check_company_pack_public_preview.py examples/company-starter
```

機械処理には既定のJSON、人間が最初に読む場合は同じ結果をMarkdownで表示できます。

```powershell
python tools\check_company_pack_public_preview.py examples\company-starter --format markdown
```

```bash
python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown
```

Markdownもpack ID、path、manifest値、validation error本文を表示せず、JSONと同じ
read-only・`NO_GO_UNPUBLISHED`境界を保ちます。`--format json`を明示した場合も
既定と同じJSON契約です。

initializer で作業 copy を作った後も、同じ command の対象だけを変えます。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools\create_company_pack.py my-company work\my-company
python tools\check_company_pack_public_preview.py work\my-company
```

POSIX shellでは、既存targetを上書きしない新しい作業copyを作ってから、同じ
self-checkを実行します。

```bash
mkdir -p work
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/check_company_pack_public_preview.py work/my-company
```

JSON出力は標準出力の一行 JSON です。Markdownを選んだ場合は見出し・表形式の
固定サマリーになります。どちらもファイルへ保存する場合にpackやprivate
locatorの値を出力へ追加しません。

## 成功時の意味

`status: PASS` は、次の4面が同じ pack bytes で確認できたことを示します。

1. `pack_structure`: Company manifest、Blocks、MOCs と、存在する場合は
   Records の structural validator が PASS した
2. `catalog_projection`: read-only Catalog が生成でき、flow と Block 数、
   false claims、`NO_GO_UNPUBLISHED` が一致した
3. `customization_boundary`: placeholder replacement、governed review、
   別途必要な evidence が別 category で表現された
4. `claim_boundary`: Human approval、runtime、Promotion、Current Truth、
   Public Beta GO をすべて false のまま保持した

`manifest.records` は汎用 Pack では任意です。Records を省略した
validator-PASS Pack は、Catalog の `records: []` と `counts.records: 0` を
保ったまま、この self-check でも `PASS` になります。公開 Company starter
自身は9 Recordsを持つため、上の代表例では `records: 9` と表示されます。

状態フィールドは相互に矛盾しない形で固定されます。`PASS` では
`validated_files`、`blocks`、`mocs` がそれぞれ1以上で、4つの `checks` が
すべて `PASS`、`refusal_reason` が `null` でなければなりません。任意の
`manifest.records` を省略した場合だけは `records: 0` を許容します。
`REFUSED` ではすべての count が0、4つの `checks` がすべて `REFUSED`、
`refusal_reason` が固定された拒否理由のいずれかである必要があります。
この形状検査は、statusだけを差し替えたレポートや、一部のcheck/countだけを
書き換えたレポートを有効な証拠として扱わないためのschema-level guardです。

公開 example では通常 `replacement_required: 42` です。initializer で
ID、status、Human Intent locator、Block expiry、Record retention locator を
再束縛した作業 copy では、通常 `replacement_required: 19` になります。
どちらも `review_required` と `evidence_required` は別の governed work で
あり、値を置いただけでは閉じません。

代表的な出力形は次のとおりです（pack ID、path、error 本文は含みません）。

```json
{
  "kind": "company_pack_public_preview_check",
  "version": "1.0",
  "status": "PASS",
  "counts": {
    "validated_files": 22,
    "blocks": 9,
    "records": 9,
    "mocs": 3,
    "replacement_required": 42,
    "review_required": 46,
    "evidence_required": 5
  },
  "checks": [
    {"id": "pack_structure", "status": "PASS"},
    {"id": "catalog_projection", "status": "PASS"},
    {"id": "customization_boundary", "status": "PASS"},
    {"id": "claim_boundary", "status": "PASS"}
  ],
  "refusal_reason": null,
  "claims": {
    "human_approval_verified": false,
    "runtime_verified": false,
    "promotion_verified": false,
    "current_truth_changed": false,
    "public_beta_go": false
  },
  "public_beta": "NO_GO_UNPUBLISHED"
}
```

## Refusal and exit codes

| Result | Exit | Meaning |
|---|---:|---|
| `PASS` | 0 | 4面のread-only self-checkが成立した |
| `REFUSED` / `INPUT_NOT_DIRECTORY` | 1 | 対象directoryではない |
| `REFUSED` / `INVALID_PACK` | 1 | 既存validatorがpackを拒否した |
| `REFUSED` / `INTERNAL_CONTRACT_REFUSAL` | 1 | 期待する既存契約を安全に再確認できなかった |
| usage error | 2 | 引数が正しくない |

拒否時は固定 reason code と zero counts だけを返し、path、manifest値、
validation error本文、secretらしい値、locatorを反射しません。

## このCLIがしないこと

- pack、Catalog、manifest、Block、Record、MOCを変更しない
- Discord、Voice、n8n、Compose、Proxmox、providerへ接続しない
- Human Intent、Decision、Capability Grant、Work Order、Promotionを作らない
- runtime、deployment、restart、restore、retention/deletionを実行しない
- `PASS` をHuman approval、Current Truth、Public Beta GOへ昇格しない

JSON Schema は
[`company-pack-public-preview-check.schema.json`](../schemas/company-pack-public-preview-check.schema.json)
です。CLIのPASS、schemaのPASS、CatalogのPASSは、いずれも公開previewの
構造と境界を確認するだけで、live systemの証明ではありません。
