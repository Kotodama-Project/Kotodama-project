# Governed Record Catalog

Governed Record は、Block が出力した候補を「誰が作り、誰が検証し、どこが正本を持ち、どの保持方針に従うか」と一緒に残すための記録契約です。Record 自体が承認、Promotion、Current Truth の変更を行うことはありません。

## 理想の使い方

```text
Source Record
  -> Intent Candidate
  -> Decision Record
  -> Work Order Candidate
  -> Change Candidate
  -> Verification Receipt
  -> Promotion Candidate
  -> separate governed Promotion
  -> Current Truth
```

各Recordは、前段の参照、対象revision、時刻、検証結果などを実データとして持ち、canonical ownerとretention policyを組織の正規参照へ束縛します。作成者と検証者を分離し、Promotionは別の権限と手続きで実行します。

## この公開starterで今できること

`examples/company-starter/records/` に次の7契約があります。

| Artifact | 主な役割 | Canonical owner example |
|---|---|---|
| `source_record` | 出典・同意/アクセス・digest・保持方針を記録 | Evidence Store |
| `intent_candidate` | Sourceから読み取った意図候補を未承認のまま記録 | Human Intent owner |
| `decision_record` | 人間の判断と根拠を記録 | Governed Git |
| `work_order_candidate` | target、action、revision、effects、rollback、期限を束縛 | Governed Git |
| `change_candidate` | Work Orderの下で生成した差分・成果物を記録 | Evidence Store |
| `verification_receipt` | exact candidateへのcheck、negative test、effectを記録 | Governed Git |
| `promotion_candidate` | Promotion審査に必要なreceiptを集約 | Governed Git |

公開validatorは、Recordの必須field、snake_case、作成roleと検証roleの分離、retention参照、自己承認/自己Promotion禁止、および全Block出力との一対一対応を検査します。サンプルは値の入った本番Recordではなく、`required_fields`を示すテンプレートです。

`schemas/record.schema.json`はportableな構造確認用です。JSON Schema単体ではrole間の値比較やpack全体の対応関係を表現しきれないため、公開前の安全判定には`tools/validate_template_pack.py`のPASSが必須です。

## まだ証明しないこと

- 参照先のHuman Intent、Decision、retention policyが実在し承認済みであること
- 実runtimeがRecordを生成・保存・削除できること
- 作成者と検証者が実際に別人であること
- PromotionやCurrent Truth変更が完了したこと
- Public Beta GO

構造の詳細は[`schemas/record.schema.json`](../../schemas/record.schema.json)、動く例は[`examples/company-starter/records/`](../../examples/company-starter/records/)、検証方法は[Template Pack Validation](../../docs/VALIDATION.md)を参照してください。
