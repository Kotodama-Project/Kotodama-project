---
type: KPI
title: agentの責任と検証
description: control SLOの候補となる指標。製品の成果達成や採用済みの閾値を表さない。
tags: [kpi, control-slo-candidate, measurement]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:supporting-measurement-definition, at: 2026-10-06T23:10:13Z }
sources:
  - id: existing-contract
    resource: ../../docs/AGENT-FOUNDRY-OPERATIONS.md
    title: Existing scope and evidence contract
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: metrics/agent-governance
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 70
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: []
  strategy:
    id: KPI-AGENT-GOVERNANCE
    adoption_status: candidate
    measurement_role: supporting_kpi
    baseline: unknown
    target: not_adopted
    deadline: not_adopted
    measurement_window: not_adopted
    exclusion_policy: not_adopted
    relationships:
      - { type: governed_by, target: POLICY-MEASUREMENT-GUARDS }
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 候補式と証拠

候補式は「対象active invocationのうち、owner・grant/lease・eval・停止/rollback/retirementが確認された割合」です。必要な証拠は、Agent specと実Invocationのbindings、eval、停止確認と戻しのreceiptです。既存の契約へ戻って、対象集合と権限を確認します。[^existing-contract]

# 過大評価を防ぐ条件

candidate registryの掲載を稼働証明にせず、active対象0なら未測定とする。[KGI-INTENT](../project/success-model.md)のownerが受け入れた成果とは別の指標であり、この値だけが改善しても製品成果の改善とは扱いません。

# 採用と値の報告

整備ownerはAI-ANALYST、独立reviewはAI-AUDITORです。測定window、対象集合、除外、数値のbaseline・threshold/target・deadlineはunknown/not_adoptedです。運用上の採用は既存のaccountable ownerが決めます。このConceptがその権限を与えることはありません。

**値はまだ報告しません。** 具体的なattested computation、固定入力・code・parameter binding、外部receiptとattester、およびsource/coverageの確認が揃ってから報告します。この候補定義だけでSLO達成、稼働、Human GOを作りません。

[^existing-contract]: 候補式の対象と検証境界の根拠。実測値の証拠ではありません。

[測定policy候補](../strategy/measurement-guards.md)は、値の採用や実測の前に必要な確認を示します。新しいauthorityや数値targetではありません。
