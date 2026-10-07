---
type: Risk
title: 代理指標だけを最適化する危険
description: Riskの定義または既存判断のprojection。実行・実証・adoption・権限を追加しない。
tags: [strategy-definition, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-guard-definition, at: 2026-10-06T23:33:26Z }
sources:
  - id: existing-authority
    resource: ../../docs/INTENT-OUTCOME-METRIC.md
    title: Existing source and authority boundary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: strategy/proxy-optimization
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
    id: RISK-PROXY-OPTIMIZATION
    adoption_status: candidate
    relationships:
      - { type: threatens, target: KGI-INTENT }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 定義と位置づけ

文書数、PR数、Task数、receipt数、agent数や、一部のKPIの改善を、依頼成果が改善したことへ置き換える危険の候補定義です。事故が実際に起きたとの記録ではありません。[^existing-authority]

# 関係と境界

* [KGI-INTENT](../project/success-model.md)

元の依頼scope、独立検証、成果ownerの受入、除外の根拠、hard guardrailsを別に照合します。KGI-INTENTの高い割合だけでも実証・adoption・GOを作りません。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)へ戻り、同じ依頼と証拠のownerを確認してください。この文書やtyped edgeを、Task・Decision・Current Truthの正本にしません。

[^existing-authority]: 出典にある判断・要求の参照。新しい実行許可や受入を発行したものではありません。
