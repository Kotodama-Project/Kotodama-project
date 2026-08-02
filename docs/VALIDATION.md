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

新しい作業copyを作る場合は、先にinitializerを使えます。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
```

initializerはshipped starterをpreflightし、既存targetを拒否し、manifest IDと全該当MOCを再束縛し、生成後にこのvalidatorを実行します。任意の既存packを更新・migrationするツールではありません。

## What it validates

- `manifest.json`と必須governance fields
- ID形式、manifest collectionの重複、参照path形式のJSON Schema整合
- 参照されたBlockとMOCの存在とJSON形式
- pack外へ出る絶対pathまたは`..`参照の拒否
- 解決後pathのpack-root containment（symlink escapeを含む）
- manifest、参照JSON、未参照JSONを含むpack内全JSONのsecretらしいkey表記揺れと代表的token/private-key値の拒否
- templateによる`promoted`やPublic GOの自己申告拒否
- Human IntentからCurrent Truthまでのcanonical ownerとmandatory denied actions
- 対応profile（`compose_minimum` / `proxmox_segmented`）の非空allowlist
- Blockのnested authority、限定allowed actions、有効期限、verification、receipt、rollback、stop contract
- MOCの必須field、string refs、`navigation_only` authority
- ID型・重複と、MOCから未知IDへの参照拒否
- `flow`宣言時のentry inputs、全Blockの一度ずつのcoverage、前段出力、primary MOC完全一致
- `projection: flow_subsequence`を明示したsecondary MOCがmanifest IDから始まり、canonical flowと同順序の非空部分列であること
- Block出力名を外部entry inputとして再注入するdependency shadowingの拒否
- Governed Recordのschema相当契約、authority、retention参照、mandatory denied claims
- Governed Recordのcreator roleとverifier roleの分離
- 全Block出力とmanifest内Record artifactの一対一coverage
- templateからのactual Capability Grant、Promotion/`promoted`、Current Truth、Public GO/Final Human GO artifact出力の拒否

JSON Schemaは`schemas/`にあります。stdlib validatorは、portable schemaだけでは表現しにくいcross-file参照と公開安全境界も検査します。

JSON Schema単体のPASSはpackの検証完了を意味しません。作成roleと検証roleの分離、Block出力とRecordの一対一対応、pack全体のsecret scanなどのcross-field/cross-file境界を含め、公開前は必ずこのCLI validatorを実行してください。

validatorは汎用packの構造と安全境界を検査するため、`flow`や`records`を持たない既存packへ同じBlock構成や順序を強制しません。`flow`を宣言したpackでは、そのpack自身が列挙したentry inputs、sequence、MOC bindingを検査します。`records`を宣言したpackでは、全Block出力との一対一対応を検査します。公開Company starter固有の9 Block ID、9 Record artifact、Capability-before-Change、Human-evidence-before-Promotion-Decisionの順序はrepository testでも固定しています。

### Secondary MOC migration note

`flow`を宣言するpackでは、`projection: flow_subsequence`を明示したMOCだけをsecondary flow projectionとして扱います。各secondary flow projectionはmanifest IDから始まり、`flow.sequence`と同じ順序のBlockを1つ以上参照する必要があります。projectionを明示しない既存0.1 MOCにはこの追加制約を遡及適用しません。

- 実行・判断の目的別入口は、`projection: flow_subsequence`を付けて同順序のBlock部分列へ移行する。
- Recordや一般文書の横断リンクはMarkdownのnavigation documentへ分ける。
- そもそもcanonical execution orderを宣言しない汎用packでは、`flow`を省略する。

これは既存データを自動変換する処理ではありません。一般navigation MOCをflow projectionへ移行する場合だけ、作業copyで差分を確認し、validatorのPASS後に採用してください。

## Tests

```powershell
python -m unittest discover -s tests -v
```

正常packに加え、path traversal、未参照JSONを含むsecret key表記揺れ、自己昇格、Public GO、未知profile、Block action越権、無効な期限、MOC authority/shape、参照切れ、flow順序・coverage・primary MOC drift、secondary MOCのreorder、Record role分離、nested rollback/receipt欠落、governance owner欠落、重複ID、型不一致をnegative caseで検査します。Windowsでsymlink作成権限がない場合、symlink E2Eだけはskipされますが、resolved-path containment自体はvalidatorで常時有効です。

## Boundary

PASSはtemplate packの構造と限定された公開安全条件だけを示します。`human_intent_ref`は非空文字列であることだけを検査し、locator形式、参照先の存在・真正性・承認状態は証明しません。実際のgoverned recordとは別途reconciliationが必要です。runtime deployment、provider E2E、実データ安全性、Human approval、Promotion、Current Truth、Public Beta GOの証明でもありません。

initializerのPASSも同じ境界です。copy、ID再束縛、構造検証を示すだけで、組織固有のHuman Intent、owner、保持方針、実行権限を確定しません。
