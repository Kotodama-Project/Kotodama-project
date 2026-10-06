---
type: Initiative
title: 同じ課題で知識取得の方式を比べる
description: 固定したrequired/forbidden corpusで候補方式を比較する候補。採用済みの作業指示や効果の実証ではない。
tags: [initiative, strategy, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:strategy-definition, at: 2026-10-06T21:30:01Z }
sources:
  - id: product-direction
    resource: ../../docs/PRODUCT-DIRECTION.md
    title: Kotodama product direction
    author: team:kotodama-project
  - id: existing-initiative
    resource: ../project/success-model.md
    title: Existing initiative vocabulary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: initiatives/method-renewal
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-BUILDER
  reviewer_role: AI-AUDITOR
  context_priority: 60
  goal_refs: [OUT-INTENT]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-METHOD-RENEWAL]
  strategy:
    id: INIT-METHOD-RENEWAL
    adoption_status: candidate
    relationships: []
    hypothesis:
      intervention: 固定したrequired/forbidden corpusで候補方式を比較する
      expected_effect: 安全条件を維持したまま必要な知識の取得を改善できる
      falsifier: 見かけの指標改善だけで成果が改善しないか禁止情報の漏れが増える
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 候補の意図

固定したrequired/forbidden corpusで候補方式を比較することで、安全条件を維持したまま必要な知識の取得を改善できるという仮説です。既存の製品方向とIDの定義を公開Conceptへ移した候補で、実行や効果を記録したものではありません。[^product-direction][^existing-initiative]

# 検証と反証

見かけの指標改善だけで成果が改善しないか禁止情報の漏れが増える場合は、仮説を支持する結果とは扱いません。実測のwindow・比較条件・成果ownerの受入を先に束縛し、失敗や未確定の試行も履歴へ残します。数値の効果や目標は未採用です。

[製品Goal](../project/goal.md)、[KGI-INTENT](../project/success-model.md)、[既存の運用契約](../operations/retrieval-quality.md)へ戻って適用範囲を確認してください。このConceptは新しいTask・grant・Company truthを作りません。

[^product-direction]: 公開されている製品方向。
[^existing-initiative]: 既存IDの意味。仮説の正しさを保証する証拠ではありません。
