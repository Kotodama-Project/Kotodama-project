---
type: Decision
title: 既存の正本・ID採用判断を参照する
description: Decisionの定義または既存判断のprojection。実行・実証・adoption・権限を追加しない。
tags: [strategy-definition, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-guard-definition, at: 2026-10-06T23:33:26Z }
sources:
  - id: existing-authority
    resource: https://github.com/Kotodama-Project/Kotodama-project/issues/128#issuecomment-5852468861
    title: Existing source and authority boundary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: strategy/canonical-definitions
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
    id: DECISION-CANONICAL-DEFINITIONS
    adoption_status: candidate
    decision_scope: canonical_definition_only
    relationships:
      - { type: adopts, target: KGI-INTENT }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 定義と位置づけ

#128に記録された、#48系のIDとConceptを正とし、旧KGI/KF/段階をそこへ対応付ける判断のprojectionです。新しいHuman Decisionを発行するものではありません。[^existing-authority]

# 関係と境界

* [KGI-INTENT](../project/success-model.md)

adoptsの範囲はcanonical_definition_onlyです。KGI-INTENTというIDと定義の置き場を採る意味で、式・数値target・measurement window・除外policy・runtime・Public Betaを採用した意味にはしません。元の判断と訂正は出典のownerへ戻します。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)へ戻り、同じ依頼と証拠のownerを確認してください。この文書やtyped edgeを、Task・Decision・Current Truthの正本にしません。

[^existing-authority]: 出典にある判断・要求の参照。新しい実行許可や受入を発行したものではありません。
