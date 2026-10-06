---
type: Measurement Policy
title: 測定の採用に必要な境界
description: Measurement Policyの定義または既存判断のprojection。実行・実証・adoption・権限を追加しない。
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
  id: strategy/measurement-guards
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
    id: POLICY-MEASUREMENT-GUARDS
    adoption_status: candidate
    baseline: unknown
    target: not_adopted
    deadline: not_adopted
    measurement_window: not_adopted
    exclusion_policy: not_adopted
    relationships:
      - { type: mitigates, target: RISK-PROXY-OPTIMIZATION }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 定義と位置づけ

Source・対象集合・window・式・実行とattestation・ownerの受入を分ける、測定policyの候補定義です。各Conceptの数値が未採用であることを保持します。[^existing-authority]

# 関係と境界

* [RISK-PROXY-OPTIMIZATION](proxy-optimization.md)

値を報告する前に、対象集合と除外、固定した計算と入力、外部receipt、attester、coverage/真正性を既存ownerが確認します。定義のverifiedとper-run attestationを代用せず、違反を平均で消しません。baseline/target/window/deadline/exclusion policyの採用は、この候補から行いません。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)へ戻り、同じ依頼と証拠のownerを確認してください。この文書やtyped edgeを、Task・Decision・Current Truthの正本にしません。

[^existing-authority]: 出典にある判断・要求の参照。新しい実行許可や受入を発行したものではありません。
