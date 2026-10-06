---
type: Attested Computation
title: KGI-INTENTの候補計算と決定的な照合
description: 宣言された不変のsnapshotから件数と比を計算する。実際の受入・coverage・runtimeの真正性は認証しない。
tags: [computation, kgi, candidate]
status: draft
stale_after: 2026-12-07T00:00:00Z
generated: { by: process:metric-contract, at: 2026-10-06T22:35:58Z }
runtime: python
parameters:
  - { name: snapshot, type: object, required: true }
computation: ../../tools/intent_outcome_computation.py
executor:
  resource: ../../tools/intent_metric.py
  receipt: [computation_revision, artifact_sha256, input_snapshot_sha256, parameter_binding_sha256, result, result_sha256]
attester:
  resource: ../../tools/intent_metric.py
sources:
  - id: metric-definition
    resource: ../project/success-model.md
    title: Canonical KGI-INTENT candidate
    author: team:kotodama-project
  - id: computation-code
    resource: ../../tools/intent_outcome_computation.py
    sha256: 56f0606a0404085d11e4b1df108ab14766db92263a33097da6aa97452c39f8cf
    title: Pinned computation-code
    author: team:kotodama-project
  - id: executor-code
    resource: ../../tools/intent_metric.py
    sha256: f9cc7a302d8e121449eb5607951c50936fc50f09b4687b056197ed074850c9e7
    title: Pinned executor-code
    author: team:kotodama-project
  - id: snapshot-contract
    resource: ../../schemas/intent-outcome-snapshot.schema.json
    sha256: ee0676947ed0ab688e205eb2198594c1a5a2040999a8b3e3280a2498375108b3
    title: Pinned snapshot-contract
    author: team:kotodama-project
kotodama:
  profile: "0.1"
  id: computations/intent-outcome
  classification: public_candidate
  authority: projection_only
  knowledge_state: candidate
  owner_role: AI-ANALYST
  reviewer_role: AI-AUDITOR
  context_priority: 40
  goal_refs: [OUT-INTENT, OUT-LOCAL]
  kgi_refs: [KGI-INTENT]
  initiative_refs: [INIT-CONTEXT-END-TO-END]
  strategy:
    id: COMP-INTENT
    adoption_status: candidate
    relationships: []
  agent_use:
    discoverable: true
    answer_mode: source_required
    decision_authority: false
    runtime_authority: false
---

# 候補の計算

[KGI-INTENT](../project/success-model.md)の式を、[snapshot契約](../../schemas/intent-outcome-snapshot.schema.json)の入力だけで計算します。snapshotは唯一のdeclared parameterで、内部のmetric_id・window_start・window_end・exclusion_modeも閉じたschemaで検査します。入力は既存の証拠ownerが用意する宣言です。[^metric-definition][^snapshot-contract]

分母は、window_start以上/window_end未満に期限があり、cutoffまでにadmittedだったcaseです。除外方式は必須parameterで、noneまたはowner・理由・同じIntent版のreceiptを持つwithdrawn/cancelledだけです。無記録の取消は分母に残します。[^computation-code]

分子には、同じSource版・内容、reviewed Intent版・依頼scope、Work/grantと有効期間、outcome、別actorのverification、owner受入または明示policy採用receipt、learning/readbackが時系列とdigestで結ばれたcompleted caseだけを入れます。artifactを作っただけのcaseは入りません。[^computation-code]

同じcase/Intent/Intent版/outcomeの再利用は拒否します。安全境界の違反は割合から切り離したhard failureです。KPI改善だけでoutcome改善が不明ならreviewを要求します。分母0は比をnullとし、成功率100%にしません。件数と比は候補として両方を出し、どちらを採用するかは決めません。[^computation-code]

# Receiptとattester

executorは定義・計算code・executor code・schema・入力・parameter binding・結果のdigestを返します。attesterは同じ固定artifactsと入力から再計算し、結果だけでなくreceipt全体を型を区別するcanonical JSONで比較します。定義やcode、入力、除外集合、結果の変異は不一致となります。[^executor-code]

receiptは実行証拠のownerへ保存し、このbundleには埋め込みません。PASSはpinned artifactと算術の一致だけです。coverageの完全性、receiptの真正性、実行したOS/image、実際のHuman受入は認証しません。metric定義のverifiedとは別です。measurement adoption、authority、Company truth、Public Beta、Human GOのclaimsはfalseです。[^executor-code]

[^metric-definition]: 候補の成果定義。実測や目標の採用ではありません。
[^snapshot-contract]: 本文を持たない閉じた入力契約。
[^computation-code]: このConceptがpinした決定的な候補式。
[^executor-code]: 固定入力・結果を再照合するread-only実装。
