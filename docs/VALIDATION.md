# Template Pack Validation

`tools/validate_template_pack.py`はPython標準ライブラリだけで動く、fail-closedな最小validatorです。

## Run

```powershell
python tools/validate_template_pack.py examples/company-starter
```

```bash
python3 tools/validate_template_pack.py examples/company-starter
```

成功時は終了code `0`、失敗時は`1`、使い方の誤りは`2`を返します。標準出力は機械可読JSONです。

## What it validates

- `manifest.json`と必須governance fields
- ID形式、manifest collectionの重複、参照path形式のJSON Schema整合
- 参照されたBlockとMOCの存在とJSON形式
- pack外へ出る絶対pathまたは`..`参照の拒否
- 解決後pathのpack-root containment（symlink escapeを含む）
- secret値を持つ可能性が高いkey表記揺れと代表的token/private-key値の拒否
- templateによる`promoted`やPublic GOの自己申告拒否
- Human IntentからCurrent Truthまでのcanonical ownerとmandatory denied actions
- 対応profile（`compose_minimum` / `proxmox_segmented`）の非空allowlist
- Blockのnested authority、限定allowed actions、有効期限、verification、receipt、rollback、stop contract
- MOCの必須field、string refs、`navigation_only` authority
- ID型・重複と、MOCから未知IDへの参照拒否
- `flow`宣言時のentry inputs、全Blockの一度ずつのcoverage、前段出力、MOC完全一致

JSON Schemaは`schemas/`にあります。stdlib validatorは、portable schemaだけでは表現しにくいcross-file参照と公開安全境界も検査します。

validatorは汎用packの構造と安全境界を検査するため、`flow`を持たないpackへ同じBlock構成や順序を強制しません。`flow`を宣言したpackでは、そのpack自身が列挙したentry inputs、sequence、MOC bindingを検査します。公開Company starter固有の6 Block IDと順序は、repository testでも固定しています。

## Tests

```powershell
python -m unittest discover -s tests -v
```

正常packに加え、path traversal、secret key表記揺れ、自己昇格、Public GO、未知profile、Block action越権、無効な期限、MOC authority/shape、参照切れ、flow順序・coverage・MOC drift、nested rollback/receipt欠落、governance owner欠落、重複ID、型不一致をnegative caseで検査します。Windowsでsymlink作成権限がない場合、symlink E2Eだけはskipされますが、resolved-path containment自体はvalidatorで常時有効です。

## Boundary

PASSはtemplate packの構造と限定された公開安全条件だけを示します。`human_intent_ref`は非空文字列であることだけを検査し、locator形式、参照先の存在・真正性・承認状態は証明しません。実際のgoverned recordとは別途reconciliationが必要です。runtime deployment、provider E2E、実データ安全性、Human approval、Promotion、Current Truth、Public Beta GOの証明でもありません。
