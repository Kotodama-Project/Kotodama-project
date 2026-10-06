---
type: Initiative
title: 実際に渡した入力と成果を照合する
description: 実行器へ渡した入力digestと受入に使う出典を同じtraceへ結ぶ候補。採用済みの作業指示や効果の実証ではない。
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
  id: initiatives/context-end-to-end
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-BUILDER
  reviewer_role: AI-AUDITOR
  context_priority: 60
  goal_refs: [OUT-INTENT]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-CONTEXT-END-TO-END]
  strategy:
    id: INIT-CONTEXT-END-TO-END
    adoption_status: candidate
    relationships: []
    hypothesis:
      intervention: 実行器へ渡した入力digestと受入に使う出典を同じtraceへ結ぶ
      expected_effect: 準備した文脈と実行に使った文脈の取り違えを検出できる
      falsifier: 入力bytesを変異させても照合が成功するか成果ownerの確認が抜ける
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 候補の意図

実行器へ渡した入力digestと受入に使う出典を同じtraceへ結ぶことで、準備した文脈と実行に使った文脈の取り違えを検出できるという仮説です。既存の製品方向とIDの定義を公開Conceptへ移した候補で、実行や効果を記録したものではありません。[^product-direction][^existing-initiative]

# 検証と反証

入力bytesを変異させても照合が成功するか成果ownerの確認が抜ける場合は、仮説を支持する結果とは扱いません。実測のwindow・比較条件・成果ownerの受入を先に束縛し、失敗や未確定の試行も履歴へ残します。数値の効果や目標は未採用です。

[製品Goal](../project/goal.md)、[KGI-INTENT](../project/success-model.md)、[既存の運用契約](../operations/agent-context.md)へ戻って適用範囲を確認してください。このConceptは新しいTask・grant・Company truthを作りません。

[^product-direction]: 公開されている製品方向。
[^existing-initiative]: 既存IDの意味。仮説の正しさを保証する証拠ではありません。
