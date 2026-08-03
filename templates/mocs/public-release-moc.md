---
id: MOC-PUBLIC-RELEASE-EXAMPLE
kind: map_of_content
version: 0.1.0
status: example
authority: navigation_only
---

# Public Release Review MOC

このMOCは、公開候補をレビューするときに同じCompany governance chainの必要箇所へ案内する入口例です。公開承認、Capability Grant、Promotion、Current Truthそのものではありません。

## Ideal use

1. 対象revisionとHuman Decisionの証拠を固定する。
2. exact Work Orderと最小Capability Grantを照合する。
3. Change CandidateとVerification Receiptを同じrevisionへ束縛する。
4. Promotion Gateを通し、別の人間判断をPromotion Decision Recordへ残す。
5. 実際の公開やPromotionは、別のgoverned processで行う。

## Current public starter

機械可読例は[`public-release.json`](../../examples/company-starter/mocs/public-release.json)です。既存Blockの順序を保った部分列だけを参照し、独立したrelease SSOTを作りません。validatorのPASSも、実公開やFinal Human GOを意味しません。

## Current read-only review path

公開starterの例では、review bundleから[Review Request](../../docs/REVIEW-REQUEST.md)、
[Review Response](../../docs/REVIEW-RESPONSE.md)、[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)
へ進みます。`46/5`などの件数はstarter例で、別Packはsaved reportの実数を使います。
このMOCは公開を実行せず、Decision、authority、Promotion、Current Truth、Public
Beta GOを生成しません。

## Add your organization links

- Candidate revision: `<CANDIDATE_REVISION_REF>`
- Human Decision evidence: `<HUMAN_DECISION_REF>`
- Work Order: `<WORK_ORDER_REF>`
- Capability Grant: `<CAPABILITY_GRANT_REF>`
- Verification Receipt: `<VERIFICATION_RECEIPT_REF>`
- Promotion Decision: `<PROMOTION_DECISION_REF>`

各参照にはsource revision、observed time、statusを表示し、古いProjectionをCurrent Truthとして扱いません。
