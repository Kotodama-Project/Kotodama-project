---
id: MOC-INCIDENT-RECOVERY-EXAMPLE
kind: map_of_content
version: 0.1.0
status: example
authority: navigation_only
---

# Incident / Recovery MOC

このMOCは、停止・復旧作業で既存のWork Order、Capability Grant、Change Candidate、Verification Receiptへ案内する入口例です。incident management system、runtime monitor、復旧実行権限の実装ではありません。

## Ideal use

1. 影響範囲、観測時刻、停止条件をincident recordへ固定する。
2. 対象とrollbackを束縛したWork Orderを作る。
3. 最小Capability Grantの範囲だけでrecovery candidateを実行する。
4. readback、negative checks、未作用をVerification Receiptへ残す。
5. 復旧後のPromotionとCurrent Truth更新は別gateで判断する。

## Current public starter

機械可読例は[`incident-recovery.json`](../../examples/company-starter/mocs/incident-recovery.json)です。現在は既存Company Blockへ辿るnavigation projectionだけで、専用Incident Record、monitor、production recovery E2Eは未実装です。

## Current evidence path

停止・復旧候補のbytesは[Review Workflow](../../docs/REVIEW-WORKFLOW.md)と
[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)でread-onlyに再照合
できます。これはincident runtime、削除、復旧済みCurrent Truth、または
Public Beta GOのreceiptではありません。

## Add your organization links

- Incident record: `<INCIDENT_REF>`
- Runtime observation: `<RUNTIME_OBSERVATION_REF>`
- Recovery Work Order: `<RECOVERY_WORK_ORDER_REF>`
- Capability Grant: `<CAPABILITY_GRANT_REF>`
- Recovery Verification Receipt: `<RECOVERY_RECEIPT_REF>`
- Rollback or stop record: `<ROLLBACK_OR_STOP_REF>`

各参照にはsource revision、observed time、statusを表示し、復旧候補と復旧済みCurrent Truthを混同しません。
