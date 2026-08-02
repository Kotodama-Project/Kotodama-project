# Company Pack Review Bundle

`build_company_pack_review_bundle.py`は、静的checkを通過したCompany packを、review対象の正確なbytesへ固定します。同じpack名の後続編集と、いまreviewしている候補を混同しないための機械可読bundleです。

## Run

先に構造validatorとcustomization checkerを通し、`replacement_required`を0にします。

```powershell
python tools\validate_template_pack.py work\my-company
python tools\check_company_pack_customization.py work\my-company
python tools\build_company_pack_review_bundle.py work\my-company
```

```bash
python3 tools/validate_template_pack.py work/my-company
python3 tools/check_company_pack_customization.py work/my-company
python3 tools/build_company_pack_review_bundle.py work/my-company
```

成功時は終了code `0`と`CANDIDATE_FOR_GOVERNED_REVIEW`を返します。manifest、全Block、全MOC、全Recordの順序付きbindingには、relative path、SHA-256、byte sizeが入ります。`bundle_digest`は、そのbinding配列をUTF-8・key sort・空白なしJSONにしたbytesのSHA-256です。時刻を含まないため、同じbytesからは同じ出力になります。

## Refusal

次の場合は終了code `1`、`BUNDLE_REFUSED`、binding 0件で停止します。

| Reason | 意味 |
|---|---|
| `STRUCTURAL_VALIDATION_FAILED` | pack構造がvalidatorを通らない |
| `CUSTOMIZATION_REQUIRED` | 静的placeholderが残っている |
| `SOURCE_DRIFT_DETECTED` | hash取得の前後で再checkまたはbytesが一致しない |

不正packの詳細errorやHuman Intent / retention locatorの値はbundleへ複製しません。成功時もpack ID、relative path、hash、size、check status/countだけを出し、文書本文は含めません。秘密値をpackへ書いてよいという意味ではなく、pack validatorのsecret scanも必須です。

## What the digest proves

bundleが示すのは、次の限定された事実です。

- 構造validatorが同じ読み取り区間でPASSした
- customization checkerの`replacement_required`が0だった
- 列挙されたmanifest / Block / MOC / Record bytesがhashへ固定された
- 同じbinding配列からbundle digestを再計算できる

## What it never proves

`CANDIDATE_FOR_GOVERNED_REVIEW`はapprovalではありません。bundleのclaimはすべてfalseで、次を別のgoverned evidenceへ残します。

- Human Intent参照先の真正性
- owner / roleの実在、権限、独立性
- retention policyの存在・運用
- candidate-bound Human Decision
- runtime readiness、deployment、rollback実行
- Promotion、Current Truth変更、Final Human GO、Public Beta GO

このCLIはローカルfilesystemを前後2回checkしてdriftを拒否しますが、敵対的なOS/processに対する署名付きsnapshotやatomic filesystem snapshotではありません。重要な採用ではbundle JSON自体を保存し、対象revision、reviewer、観測時刻、署名または保護されたreceiptを別Recordへ束縛してください。

機械可読schemaは[`company-pack-review-bundle.schema.json`](../schemas/company-pack-review-bundle.schema.json)です。
