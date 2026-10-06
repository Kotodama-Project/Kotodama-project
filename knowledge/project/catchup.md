---
type: Operational Playbook
title: 現在の候補と残る作業を確認する
description: 現在の候補と残る作業を出典の版に戻って確認する。未統合と未確認を完了へ置き換えず、古い文脈や出典の不一致を拒否して同じ仕事へ再開する。
tags: [catchup, knowledge, context, 現状, 候補, 再開, 引継ぎ]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:canonical-knowledge-port, at: 2026-10-06T11:18:26Z }
sources:
  - id: project-map
    resource: ../../docs/PROJECT-MAP.md
    title: 現行のプロジェクト地図
    author: team:kotodama-project
  - id: current-status
    resource: ../../STATUS.md
    title: 公開候補と未受入の範囲
    author: team:kotodama-project
  - id: knowledge-contract
    resource: ../../docs/KNOWLEDGE-BASE.md
    title: 知識の検証と限定context
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: project/catchup
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-LIBRARIAN
  reviewer_role: AI-AUDITOR
  context_priority: 12
  goal_refs: [OUT-INTENT]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-KNOWLEDGE-REFRESH, INIT-DYNAMIC-AGENT-CONTEXT]
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 再開の手順

1. [プロジェクトの目的](goal.md)と[現在地](current-state.md)を読み、対象のIssue、既存の担当と許可範囲を確認する。地図は入口であり、別のTask正本を作らない。[^project-map]
2. 現在のsource revision、候補、既存PRのhead/baseとチェックを読み戻す。過去の観測の日付やCI成功を現在の受入として使わない。未統合・未確認の範囲を保持する。[^current-status]
3. 必須の文脈を先に確保する。古いConcept、出典pinの不一致、取消、未解決の矛盾や予算超過があれば、不足を解消してから新しく読み込む。古い内容を短く切って渡さない。[^knowledge-contract]
4. 訂正を反映してquery/contextを作り直す。以前のsource digestと文脈digestを再利用せず、実行器へ渡す場合はその最終入力へ別途束縛する。候補の生成だけでTask完了・権限・本人性を認定しない。[^knowledge-contract]

このConceptは再開の手順を示す候補で、GitHubや実行環境のライブ状態を保管しない。
実行の直前には、既存の[権限境界](../governance/authority-boundaries.md)と[更新手順](../operations/refresh-loop.md)へ戻る。

[^project-map]: [プロジェクトの地図](../../docs/PROJECT-MAP.md)
[^current-status]: [公開候補の現在地](../../STATUS.md)
[^knowledge-contract]: [知識基盤の契約](../../docs/KNOWLEDGE-BASE.md)
