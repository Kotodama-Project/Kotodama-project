---
type: Key Factor
title: 比較と観測の根拠
description: KGI-INTENTを支える要因候補。作業実行・数値目標・効果の実証を宣言しない。
tags: [key-factor, strategy, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:key-factor-definition, at: 2026-10-06T23:22:27Z }
sources:
  - id: current-contract
    resource: ../../knowledge/operations/retrieval-quality.md
    title: Current canonical contract
    author: team:kotodama-project
  - id: public-predecessor
    resource: https://github.com/Kotodama-Project/Kotodama-project/blob/a20ebd336071d32d896a6391c7e01cb76ccadda9/governance/okf.json
    title: Public predecessor factor vocabulary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: factors/evaluation-evidence
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 65
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  factor_refs: [KF-06]
  initiative_refs: [INIT-METHOD-RENEWAL, INIT-CONTEXT-END-TO-END]
  strategy:
    id: KF-06
    adoption_status: candidate
    relationships:
      - { type: observed_by, target: KPI-GROUNDED-RETRIEVAL }
      - { type: observed_by, target: KPI-FORBIDDEN-LEAKAGE }
      - { type: advanced_by, target: INIT-METHOD-RENEWAL }
      - { type: advanced_by, target: INIT-CONTEXT-END-TO-END }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# KGIへの寄与の仮説

「同じ入力・課題で品質と境界遵守を比較し、指標だけの改善を区別する」ことが、[KGI-INTENT](../project/success-model.md)の依頼成果に寄与するという候補です。旧候補のIDを維持し、現行の正本と権限の境界へ接続しています。旧targetやphaseの予定・到達状態は移しません。[^current-contract][^public-predecessor]

# 観測と介入

observed_byは効果を観測する補助指標、advanced_byは反証条件を持つ介入候補です。

* [KPI-GROUNDED-RETRIEVAL](../metrics/grounded-retrieval.md)
* [KPI-FORBIDDEN-LEAKAGE](../metrics/forbidden-leakage.md)
* [INIT-METHOD-RENEWAL](../initiatives/method-renewal.md)
* [INIT-CONTEXT-END-TO-END](../initiatives/context-end-to-end.md)

指標だけが改善しても、成果ownerが受け入れた依頼結果が改善しなければ見直します。仮説の採否、実行、measurement window、targetは既存ownerが判断します。本文やgraphからgrant、Task実行、Current Truthを作りません。

[^current-contract]: 現在の出典と適用範囲。
[^public-predecessor]: 由来の記録。古い候補の数値や稼働状態を承認した証拠ではありません。
