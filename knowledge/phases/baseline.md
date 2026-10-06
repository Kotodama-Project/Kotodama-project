---
type: Phase
title: 分類・責任・参照の基盤
description: 旧P0の能力定義をPHASE-P0へ対応付ける候補。現在地や実行許可を表さない。
tags: [phase, capability-definition, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:phase-definition, at: 2026-10-06T23:28:38Z }
sources:
  - id: canonical-decision
    resource: https://github.com/Kotodama-Project/Kotodama-project/issues/128#issuecomment-5852468861
    title: Recorded canonical knowledge decision
    author: team:kotodama-project
  - id: current-contract
    resource: ../../docs/CONTROL-PLANE-OPERATIONS.md
    title: Current capability and evidence boundary
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: phases/baseline
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-CHIEF
  reviewer_role: AI-AUDITOR
  context_priority: 80
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: []
  strategy:
    id: PHASE-P0
    adoption_status: candidate
    relationships: []
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 段階の意味

知識、Goal/KGI、agentの責任索引が既存ownerへ結ばれ、分類と未定義参照を検査できることを確認するための定義候補です。#128で採用された「旧段階を正本Conceptへ対応付ける」判断に従い、旧P0をPHASE-P0へ対応付けます。[^canonical-decision][^current-contract]

# 現在地との分離

このConceptは現在その段階にいること、完了したこと、進捗率、開始/終了日、採用済みの数値targetを記録しません。実行は既存Task owner、進捗はその現在のreceipt、採否・Public Beta・Human GOは既存のaccountable decisionへ戻します。

[製品Goal](../project/goal.md)と[KGI-INTENT](../project/success-model.md)の改善を評価し、document数やphase表が埋まったことを成果達成に数えません。先の段階の定義が存在しても、欠けた実環境・権限・人の受入を飛ばせません。

[^canonical-decision]: 定義の置き場とID対応の判断。現在の到達や権限の判断ではありません。
[^current-contract]: 受入に必要な証拠と境界。実証のreceiptではありません。
