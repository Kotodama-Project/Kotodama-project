---
type: Outcome
title: 受け入れられた依頼成果の形
description: Outcomeの定義または既存判断のprojection。実行・実証・adoption・権限を追加しない。
tags: [strategy-definition, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-guard-definition, at: 2026-10-06T23:33:26Z }
sources:
  - id: existing-authority
    resource: ../../docs/OWNER-INTENT-COMPANY-AGI.md
    title: Existing source and authority boundary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: strategy/verified-request
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 75
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: []
  strategy:
    id: OUTCOME-VERIFIED-REQUEST
    adoption_status: candidate
    relationships: []
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 定義と位置づけ

依頼した結果が同じIntent版とscopeへ戻り、独立検証と成果ownerの受入・learning/readbackが結ばれた状態を目指す定義です。これは特定のcaseを完了と認定した記録ではありません。[^existing-authority]

# 関係と境界

artifact、Task、PR、review、agentが増えただけではこのOutcomeを満たしません。実際の受入recordは既存ownerに残し、このConceptへ転記しません。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)へ戻り、同じ依頼と証拠のownerを確認してください。この文書やtyped edgeを、Task・Decision・Current Truthの正本にしません。

[^existing-authority]: 出典にある判断・要求の参照。新しい実行許可や受入を発行したものではありません。
