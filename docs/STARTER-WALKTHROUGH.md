# Company Starter Walkthrough

この手順は、公開starterを自分の会社・チーム用の**候補pack**として試すためのものです。約3分、Python標準ライブラリだけで構造検証できます。

## 1. starterをcopyする

repository rootから実行します。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
Copy-Item examples\company-starter work\my-company -Recurse
```

```bash
mkdir -p work
cp -R examples/company-starter work/my-company
```

元のexampleを直接書き換えず、作業copyを使うと差分とrollbackが明確になります。

## 2. manifestで正本の場所を決める

`work/my-company/manifest.json`で最初に変更するのは次の3点です。

| Field | 書くもの | 書かないもの |
|---|---|---|
| `id` | 小文字・数字・hyphenのpack ID | 会社の秘密名や個人情報 |
| `human_intent_ref` | governed Human Intent recordの参照名 | Human Intent本文やtoken |
| `canonical_owners` | fact familyごとの正本owner/保存先 | 同じfactの競合する正本 |

`human_intent_ref`はlocatorのplaceholderです。このvalidatorは参照先の存在、真正性、承認を確認しません。

`id`を変更したら、`mocs/company-operations.json`の先頭refも同じIDへ変更します。MOCの参照先が存在しなければvalidatorはfail closedします。

## 3. flow contractとMOC順にBlockを読む

`manifest.json`の`flow`は、外部から入る`entry_inputs`、Block IDの`sequence`、読み順を示す`moc_ref`を宣言します。[`company-operations.json`](../examples/company-starter/mocs/company-operations.json)は、同じ順序を示すnavigation projectionです。

```mermaid
flowchart LR
  S["Source Intake"] --> I["Intent Candidate"]
  I --> D["Human Decision record"]
  D --> W["Work Order candidate"]
  W --> G["Capability Grant candidate"]
  G --> X["Change Candidate"]
  X --> V["Verification Receipt"]
  V --> P["Promotion Candidate"]
  P --> H["Human Promotion Decision"]
  H -. "separate governed Promotion" .-> C["Current Truth"]
```

MOCはDecision、Promotion、Current Truthを変更しません。

validatorは、sequenceがmanifest内の全Blockをちょうど1回含むこと、各Blockの入力がentry inputまたは前段Blockの出力に存在すること、指定MOCが同じ順序を持つことを確認します。

## 4. Block出力とRecord契約を合わせる

`manifest.json`の`records`は、各Blockの`outputs`を受け取るGoverned Recordテンプレートを列挙します。Recordの`artifact`は全Block出力を重複なく一度ずつ覆う必要があります。

- `required_fields`: 実Recordを作るときに必ず保持する項目
- `canonical_owner`: そのfact familyの正本を持つ場所または役割
- `authority`: 作成役、検証役、Current Truthに必要な別Promotion
- `retention.policy_ref`: 値そのものではなく組織の保持方針への参照
- `denied_claims`: 自己承認、自己Promotion、PromotionなしのCurrent Truth化を禁止

このstarterのRecordはデータ入力フォームではなく契約例です。実データ、secret、個人情報を公開packへ直接書かないでください。

## 5. Blockを自分の運用へ合わせる

各Blockで必ず確認します。

- `inputs` / `outputs`: 前後のrecord名がつながっているか
- `authority`: owner、許可action、拒否action、期限が具体的か
- `verification`: successだけでなくnegative testがあるか
- `rollback`: 失敗時に何を戻し、何が変わっていないと確認するか
- `stop_conditions`: 不明点やdriftで安全に止まるか

例の`2099-01-01`は書式を示すplaceholderです。実運用では短い作業windowに置き換えます。

## 6. validatorを実行する

```powershell
python tools\validate_template_pack.py work\my-company
```

```bash
python3 tools/validate_template_pack.py work/my-company
```

成功例:

```json
{"errors": [], "pack_id": "my-company", "status": "PASS", "validated_files": 20}
```

## 7. PASSの意味を狭く保つ

PASSが示すのは、pack構造、参照、限定authority、secretらしい値、必須denialなどの検査結果です。次は証明しません。

- Humanが意図・Decision・Promotionを承認したこと
- 外部providerやruntimeが安全に動くこと
- rollbackや削除が実環境で成功すること
- Current Truthが変更されたこと
- Public Beta GO

実行やPromotionへ進む場合は、対象revisionを固定したWork Order、実結果のVerification Receipt、必要な独立承認を別途用意します。

## よくある失敗

| Error | 確認すること |
|---|---|
| `unsafe relative path` | pack外参照、空白、絶対pathを使っていないか |
| `references unknown id` | MOCのIDと各JSONの`id`が一致しているか |
| `has unavailable input` | `flow.sequence`の前段出力または`entry_inputs`が不足していないか |
| `must contain every manifest block` | sequenceからBlockが欠落・重複していないか |
| `refs must equal manifest id followed by flow sequence` | MOCとflowの順序が一致しているか |
| `forbidden allowed action` | Blockが公開safe allowlistを越えていないか |
| `secret-bearing key is forbidden` | secret値ではなく安全な参照名へ置換したか |
| `public_beta must remain NO_GO_UNPUBLISHED` | template自身にGOを宣言させていないか |

validatorの完全な境界は[Template Pack Validation](VALIDATION.md)を参照してください。
