# Governed Record Catalog

Governed Record は、Block が出力した候補を「誰が作り、誰が検証し、どこが正本を持ち、どの保持方針に従うか」と一緒に残すための記録契約です。Record 自体が承認、Promotion、Current Truth の変更を行うことはありません。

## 理想の使い方

```text
Source Record
  -> Intent Candidate
  -> Decision Record
  -> Work Order Candidate
  -> Capability Grant Candidate
  -> Change Candidate
  -> Verification Receipt
  -> Promotion Candidate
  -> Promotion Decision Record
  -> separate governed Promotion
  -> Current Truth
```

各Recordは、前段の参照、対象revision、時刻、検証結果などを実データとして持ち、canonical ownerとretention policyを組織の正規参照へ束縛します。作成者と検証者を分離し、Promotionは別の権限と手続きで実行します。

## この公開starterで今できること

`examples/company-starter/records/` に次の9契約があります。

| Artifact | 主な役割 | Canonical owner example |
|---|---|---|
| `source_record` | 出典・同意/アクセス・digest・保持方針を記録 | Evidence Store |
| `intent_candidate` | Sourceから読み取った意図候補を未承認のまま記録 | Human Intent owner |
| `decision_record` | 人間の判断と根拠を記録 | Governed Git |
| `work_order_candidate` | target、action、revision、effects、rollback、期限を束縛 | Governed Git |
| `capability_grant_candidate` | subjectと最小actionをexact Work Orderへ期限付きで束縛 | Governed Git |
| `change_candidate` | Work Orderの下で生成した差分・成果物を記録 | Evidence Store |
| `verification_receipt` | exact candidateへのcheck、negative test、effectを記録 | Governed Git |
| `promotion_candidate` | Promotion審査に必要なreceiptを集約 | Governed Git |
| `promotion_decision_record` | 人間のPromotion判断を記録するがPromotionは実行しない | Governed Git |

公開validatorは、Recordの必須field、snake_case、作成roleと検証roleの分離、retention参照、自己承認/自己Promotion禁止、および全Block出力との一対一対応を検査します。サンプルは値の入った本番Recordではなく、`required_fields`を示すテンプレートです。

## 公開starterの9 Governed Recordsを目的で選ぶ

公開starterのRecord契約は、同じcanonical flowの各段階で「何を残すか」を
選ぶための一覧です。以下の9件はすべて`examples/company-starter/records/`に
同梱されたshipped JSONで、順序はSourceからPromotion Decisionまでの標準鎖に
一致します。

| 段階 | 目的 | shipped contract |
|---|---|---|
| Source Record | 出典、同意/アクセス、digest、保持方針を束ねる | [source-record.json](../../examples/company-starter/records/source-record.json) |
| Intent Candidate | Sourceから抽出した確認待ちの意図を残す | [intent-candidate.json](../../examples/company-starter/records/intent-candidate.json) |
| Decision Record | 人間またはpolicyの判断と根拠を残す | [decision-record.json](../../examples/company-starter/records/decision-record.json) |
| Work Order Candidate | target、action、revision、effects、rollback、期限を束ねる | [work-order-candidate.json](../../examples/company-starter/records/work-order-candidate.json) |
| Capability Grant Candidate | subjectと最小actionをWork Orderへ期限付きで束ねる | [capability-grant-candidate.json](../../examples/company-starter/records/capability-grant-candidate.json) |
| Change Candidate | Work Order下で作った差分・成果物を残す | [change-candidate.json](../../examples/company-starter/records/change-candidate.json) |
| Verification Receipt | exact candidateのcheck、negative test、effectを残す | [verification-receipt.json](../../examples/company-starter/records/verification-receipt.json) |
| Promotion Candidate | Promotion審査へ渡すreceiptの集合を残す | [promotion-candidate.json](../../examples/company-starter/records/promotion-candidate.json) |
| Promotion Decision Record | 人間のPromotion判断を残す（Promotion自体は実行しない） | [promotion-decision-record.json](../../examples/company-starter/records/promotion-decision-record.json) |

この表はRecordの目的と参照先を案内するnavigationです。9件とも構造候補であり、
`candidate-only`、`read-only`、`NO_GO_UNPUBLISHED`の境界を保ちます。Voiceのraw
audio、transcript、speaker attribution、retention/delete receipt、実際のPromotionや
Current Truthは、この公開Record catalogが生成・保存・証明するものではありません。

Recordを実際のcandidate chainへ渡すときは、まずreview bundleでBlock・Record・
MOCのbytesを固定し、[Review Request](../../docs/REVIEW-REQUEST.md)、[Review Response](../../docs/REVIEW-RESPONSE.md)、
[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)で保存済み件数と参照を
再照合します。starterの`19/46/5`は公開例であり、Recordを省略・追加したPackの
件数を固定しません。

`schemas/record.schema.json`はportableな構造確認用です。JSON Schema単体ではrole間の値比較やpack全体の対応関係を表現しきれないため、公開前の安全判定には`tools/validate_template_pack.py`のPASSが必須です。

## まだ証明しないこと

- 参照先のHuman Intent、Decision、retention policyが実在し承認済みであること
- 実runtimeがRecordを生成・保存・削除できること
- 作成者と検証者が実際に別人であること
- PromotionやCurrent Truth変更が完了したこと
- Public Beta GO

構造の詳細は[`schemas/record.schema.json`](../../schemas/record.schema.json)、動く例は[`examples/company-starter/records/`](../../examples/company-starter/records/)、検証方法は[Template Pack Validation](../../docs/VALIDATION.md)を参照してください。
