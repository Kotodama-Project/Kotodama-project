---
type: Key Factor
title: 証拠と権限の連鎖
description: KGI-INTENTを支える要因候補。作業実行・数値目標・効果の実証を宣言しない。
tags: [key-factor, strategy, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:key-factor-definition, at: 2026-10-06T23:22:27Z }
sources:
  - id: current-contract
    resource: ../../docs/OWNER-INTENT-COMPANY-AGI.md
    title: Current canonical contract
    author: team:kotodama-project
  - id: public-predecessor
    resource: https://github.com/Kotodama-Project/Kotodama-project/blob/a20ebd336071d32d896a6391c7e01cb76ccadda9/governance/okf.json
    title: Public predecessor factor vocabulary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: factors/evidence-authority
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 65
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  factor_refs: [KF-04]
  initiative_refs: [INIT-CONTEXT-AUDIT]
  strategy:
    id: KF-04
    adoption_status: candidate
    relationships:
      - { type: observed_by, target: KPI-AUTHORITY-INTEGRITY }
      - { type: observed_by, target: KPI-FORBIDDEN-LEAKAGE }
      - { type: advanced_by, target: INIT-CONTEXT-AUDIT }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# KGIへの寄与の仮説

「Source・Intent・Decision・Work・Verification・Promotionを短絡させない」ことが、[KGI-INTENT](../project/success-model.md)の依頼成果に寄与するという候補です。旧候補のIDを維持し、現行の正本と権限の境界へ接続しています。旧targetやphaseの予定・到達状態は移しません。[^current-contract][^public-predecessor]

# 観測と介入

observed_byは効果を観測する補助指標、advanced_byは反証条件を持つ介入候補です。

* [KPI-AUTHORITY-INTEGRITY](../metrics/authority-integrity.md)
* [KPI-FORBIDDEN-LEAKAGE](../metrics/forbidden-leakage.md)
* [INIT-CONTEXT-AUDIT](../initiatives/context-audit.md)

指標だけが改善しても、成果ownerが受け入れた依頼結果が改善しなければ見直します。仮説の採否、実行、measurement window、targetは既存ownerが判断します。本文やgraphからgrant、Task実行、Current Truthを作りません。

[^current-contract]: 現在の出典と適用範囲。
[^public-predecessor]: 由来の記録。古い候補の数値や稼働状態を承認した証拠ではありません。
