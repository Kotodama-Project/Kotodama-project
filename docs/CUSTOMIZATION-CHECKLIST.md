# Company Pack Customization Checklist

このchecklistは、Company starterを自分の組織用の候補へ変えるときに、example placeholderと要確認事項を機械可読で列挙します。placeholderを置換した事実と、Human approval・authority・Promotion・Current Truthを分離するためのものです。

## Run

initializerで作業copyを作った後に実行します。

```powershell
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
```

```bash
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/check_company_pack_customization.py work/my-company
```

initializerはpack IDを再束縛し、manifest、9 Blocks、3 MOCs、9 Recordsの合計22文書を`draft`にします。そのため新しい作業copyでは、組織固有の19項目から始められます。

- governed Human Intent locator: 1
- Blockのbounded expiry: 9
- Recordのretention policy locator: 9

元のshipped exampleを直接検査すると、上記19件にstarter ID 1件と`example` status 22件を加えた42件が表示されます。

## Three categories

| Category | 意味 | 静的に閉じられるか |
|---|---|---|
| `replacement_required` | exampleのまま残っているID、status、locator、expiry | 候補pack内の編集と再検証で閉じられる |
| `review_required` | canonical owner、runtime profile、Block owner role、Record owner/creator/verifier role | 組織のgoverned reviewが必要 |
| `evidence_required` | Human Intentの真正性、owner acceptance、role assignment・人分離、retention policy、Human Decision | このCLIだけでは閉じられない |

構造PASS後のcustomization itemは、対応する値そのものではなくJSON path、category、reasonを出します。`INVALID_PACK`の`structural_validation.errors`は不正な入力値を説明に含む場合があるため、reportを外部共有する前に確認してください。実データ、token、個人情報、Human Intent本文を公開packへ書かず、安全なlocatorを使ってください。

## Status and exit code

| Status | Exit | 意味 |
|---|---:|---|
| `INVALID_PACK` | 1 | 構造validatorが先に失敗したためcustomization判定を行わない |
| `CUSTOMIZATION_REQUIRED` | 1 | `replacement_required`が1件以上残る |
| `READY_FOR_GOVERNED_REVIEW` | 0 | 静的placeholderは0件。governed reviewへ渡せる |
| usage error | 2 | CLI引数が不正 |

`READY_FOR_GOVERNED_REVIEW`はadoption ready、runtime ready、approved、promotedを意味しません。reportの`claims`は常にfalseで、`public_beta`は`NO_GO_UNPUBLISHED`です。

## Human-readable guided view

exact itemを一件ずつ読む前に現在地と優先順を把握したい場合は、同じcheckerを内部で使うread-only plannerを実行します。

```powershell
python tools\plan_company_pack_next_steps.py work\my-company --format markdown
```

plannerは元reportの全itemをcategory別groupへlosslessに集計し、現在stage、理想の7段階、recommended next commandを表示します。default JSONのschemaは[`company-pack-next-steps.schema.json`](../schemas/company-pack-next-steps.schema.json)です。plannerのexit code `0`はplan生成成功を表すため、`CUSTOMIZATION_REQUIRED`でも`0`です。詳細は[Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)を参照してください。

## Ideal use

1. initializerで新しい`draft`作業copyを作る。
2. `replacement_required`を一件ずつ安全な参照名・bounded windowへ置き換える。
3. pack validatorとcustomization checkerを再実行する。
4. [review bundle](REVIEW-BUNDLE.md)で、review対象の22ファイルをexact SHA-256へ固定する。
5. [review workflow](REVIEW-WORKFLOW.md)に従い、別のreviewerがsaved bundleを同じPack bytesへ照合する。
6. `review_required`をauthorityを持つ人と確認し、bundle/report digestと判断証拠を別Recordへ残す。
7. `evidence_required`をcandidate-bound evidenceで閉じる。
8. 別のgoverned processだけがPromotionやCurrent Truth変更を行う。

## Current implementation boundary

現在のcheckerはJSON packの静的内容だけを読みます。provider接続、Human Intent参照先の取得、role assignment、署名、runtime、deployment、rollback実行、Promotion、Current Truth変更は行いません。

機械可読出力のschemaは[`customization-report.schema.json`](../schemas/customization-report.schema.json)です。pack構造の境界は[Template Pack Validation](VALIDATION.md)を参照してください。
