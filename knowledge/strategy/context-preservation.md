---
type: Experiment
title: 同じ依頼で文脈保持を比較する候補実験
description: Experimentの定義または既存判断のprojection。実行・実証・adoption・権限を追加しない。
tags: [strategy-definition, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-guard-definition, at: 2026-10-06T23:33:26Z }
sources:
  - id: existing-authority
    resource: ../../knowledge/operations/retrieval-quality.md
    title: Existing source and authority boundary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: strategy/context-preservation
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
    id: EXP-CONTEXT-PRESERVATION
    adoption_status: candidate
    relationships:
      - { type: produces, target: OUTCOME-VERIFIED-REQUEST }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 定義と位置づけ

同じ固定したSource/Intent/Task・required/forbidden条件で既存方式と変更候補を比較する、未実行の実験定義です。介入以外の入力と評価版を固定します。[^existing-authority]

# 関係と境界

* [OUTCOME-VERIFIED-REQUEST](verified-request.md)

必須条件の欠落、禁止情報の漏れ、重大な人の訂正、実行権限違反が増えた場合は改善としません。KPIだけ改善して依頼成果が改善しなければ見直します。費用、試行window、参加者、数値の採用は既存ownerが決めます。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)へ戻り、同じ依頼と証拠のownerを確認してください。この文書やtyped edgeを、Task・Decision・Current Truthの正本にしません。

[^existing-authority]: 出典にある判断・要求の参照。新しい実行許可や受入を発行したものではありません。
