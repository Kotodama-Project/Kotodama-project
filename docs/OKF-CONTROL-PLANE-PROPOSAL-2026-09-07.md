# Kotodama OKF Control Plane 提案

Status: **Architecture proposal / implementation and adoption not implied**  
Date: **2026-09-07**  
Applies to: `codex/knowledge-base-control-plane-20260907` and its base integration train  
Authority: This document proposes a next architecture. It does not replace Human Intent, Task state, Decision, Current Truth, Access Policy, Work Order, Promotion, or Final Human GO.

## 1. Executive summary

Kotodama の現行 OKF 実装は、公開可能な Markdown knowledge bundle、出典、生成・検証主体、鮮度、ライフサイクル、役割分離、deterministic catalog/graph、監査・検索・限定 context を備えた良い基礎である。

次に必要なのは、単なる文書群から次の **Knowledge Control Plane** へ進化させることである。

```text
Human Intent / Source / Decision / Task / Evidence の既存正本
  -> revision・digest・authority・access を束縛した Source Binding
  -> OKF Concept Candidate
  -> independent verification / conflict resolution
  -> reviewed OKF revision
  -> catalog / typed graph / lexical・semantic indexes
  -> actor・purpose・Task・grant に束縛した Context Pack
  -> bounded work / independent outcome verification
  -> correction・revocation・learning event
  -> affected concepts and contexts only invalidated and rebuilt
```

最重要の設計判断は以下である。

1. **OKF標準準拠、Kotodama producer profile準拠、decision-ready判定を分離する。**
2. **Goal、Outcome、KGI、Key Factor、KPI、Initiative、Experimentをfirst-class Conceptにする。**
3. **KGI/KPIの計算を OKF v0.2 `Attested Computation` と実行receiptで再現可能にする。**
4. **SourceをURLやpathだけでなく、revision・content digest・観測時刻・authority・access/invalidation refへ束縛する。**
5. **知識状態を一つのenumへ押し込まず、文書、認識、時間、access、publication、authorityを直交させる。**
6. **検索を「類似文書探し」から、必須制約を落とさない task-scoped context assemblyへ変える。**
7. **更新・訂正・取消では、再生成より先に影響投影を隔離し、CASでcurrent revisionを切り替える。**
8. **agentの数ではなく、元の成果、知識品質、境界遵守、費用、遅延、rollback可能性で最適化する。**

## 2. 現在の実装で維持すべき強み

現行PRで確立した以下は維持する。

- OKFを transactional SSOT、ACL engine、raw archive、runtime authority にしない。
- 公開repositoryのknowledge bundleを `public_candidate` に限定する。
- `generated` と `verified` を分離し、生成主体の自己検証を認めない。
- stale、conflict、unknown、deprecated、revokedを無視せず表示する。
- catalog、graph、search result、contextを再構築可能なprojectionとして扱う。
- Markdownを人とagentが共通に読める正規のcurated representationとして使う。
- one writer per mutable surface、executorとauditorの分離、bounded grantを維持する。
- embeddingやvector DBをsource archiveやauthorityとして扱わない。
- 構造テストやdocument作成を、runtime配備・Public Beta・Human GOの証拠にしない。

## 3. 重要な監査所見

| ID | Severity | 所見 | 問題 | 提案 |
|---|---|---|---|---|
| OKF-01 | Critical | OKF standard conformanceとKotodama strict profileが同じvalidator結果に見える | OKF v0.2は`type`のみ常時必須で、optional fieldやbroken cross-linkだけでは非準拠にならない。現行profileは追加項目やlink/sourceの存在を必須化している | `standard`、`profile`、`decision-ready`の3判定へ分離する |
| OKF-02 | Resolved in current foundation | `stale_after`、`sources[].last_modified`、`usage_window`はoffset付きISO 8601 datetimeである | OKF v0.2 §5は全timestamp-valued keyを明示UTC offset付きdatetimeとし、`stale_after`をrelative TTLではなくabsolute instantと定義する | 現行date-time schemaを維持し、offsetなし値を拒否する |
| OKF-03 | Critical | `KGI-INTENT`は名前・metric・evidence sourceだけで、計算契約がない | numerator、denominator、window、exclusion、owner、baseline、target、guardrail、calculation revisionがないため測れない | Metric ConceptとAttested Computation Conceptへ分離する |
| OKF-04 | Critical | `retrieval readiness`が未検証candidateもreadyとして数える | source/freshnessが100%でもindependent verificationが0%であり、意思決定可能性と構造的取得可能性を混同する | `structural_retrieval_eligibility`と`decision_ready_ratio`を別指標にする |
| OKF-05 | Critical | Sourceがpath/URL中心でrevision-boundではない | 同じpathの内容変更、force replacement、external driftを検出できず、どのbytesから生成したか再現できない | Source Bindingにrevision、digest、observed_at、authority scope、access/invalidation refを追加する |
| OKF-06 | High | Concept間relationが標準Markdown linkのuntyped edgeだけである | depends-on、supersedes、conflicts-with、governed-by等を機械的に区別できない | Markdown linkを残したまま、Kotodama typed relation projectionを追加する |
| OKF-07 | Critical | Context assemblyがGoal/KGI/tagとConcept件数中心である | recipient、purpose、Task revision、grant、policy revision、token/byte budget、最終入力hashが束縛されない | signed/hashed Context Pack contractを追加する |
| OKF-08 | High | 検索品質を判断するevaluation corpusがない | lexical、graph、embedding、rerankerの比較を再現できない | required/forbidden concept、source、constraint、budgetを持つfixtureを作る |
| OKF-09 | Critical | refresh/invalidationが文書上のflowで、実event/CASがない | source correctionやrevocation後に古いprojectionがraceでcurrentへ戻り得る | append-only change event、impact set、quarantine、CAS promotionを実装する |
| OKF-10 | High | logical roleはあるがruntime identity・invocation・grantへ未接続 | role名だけで責任主体、独立性、budget、lease、実行証拠を確認できない | Agent DefinitionとAgent Invocationを分離し、毎runをreceiptへ結ぶ |
| OKF-11 | Medium | 公開bundleだけが存在する | 公開境界としては正しいが、将来のinternal/restricted knowledgeを安全に連携できない | bundle federationとContext Gatewayを採用し、公開bundleへprivate bodyを複製しない |
| OKF-12 | Critical | PR #48のbase自体がpublished `main`から大きく先行している | #48がclean/greenでも、base integration trainが`main`へ採用可能とは限らない | baseの統合経路、最新review、required checks、license/provenance gateを先に明示する |

## 4. Target architecture

### 4.1 Layer A: Authoritative records

既存の正本を保持する。

- Human Intent and corrections
- Source Evidence and source revision
- Decision and Promotion
- Task / Session / Work Order / Grant / Lease
- Verification Receipt and operational evidence
- Access Policy / consent / retention / legal hold

OKFはこれらを書き換えず、stable referenceとrevisionを通じて参照する。

### 4.2 Layer B: Append-only causal ledger

変更を上書きではなくeventとして保持する。

推奨event family:

- `SourceObserved`
- `SourceRevised`
- `SourceAccessRevoked`
- `ConceptProposed`
- `ConceptVerified`
- `ConceptConflictDetected`
- `ConceptPromoted`
- `ConceptInvalidated`
- `ContextAssembled`
- `ContextDelivered`
- `WorkExecuted`
- `OutcomeVerified`
- `MetricComputed`
- `MethodExperimented`
- `MethodAdopted`
- `RollbackCompleted`

各eventはsubject、subject revision、actor、authority/grant、occurred_at、observed_at、idempotency key、previous digest、content digest、evidence refsを持つ。

### 4.3 Layer C: OKF curated projection

人・agentが読むConceptを管理する。

推奨Concept families:

```text
knowledge/
  goals/
  outcomes/
  factors/
  metrics/
  computations/
  initiatives/
  experiments/
  decisions/
  risks/
  capabilities/
  agents/
  operations/
  references/
  evaluations/
  _generated/
```

既存の`project/`と`governance/`は段階移行し、破壊的renameは行わない。

### 4.4 Layer D: Rebuildable projections

- frontmatter catalog
- typed relation graph
- source-to-concept reverse index
- invalidation impact index
- lexical index
- optional embedding index
- evaluation result projection
- human navigation index

これらは削除しても一次情報とreviewed Conceptから再構築できることを条件にする。

### 4.5 Layer E: Context Gateway

Context Gatewayは検索APIではなく、以下を同時に解決するpolicy-aware assemblerとする。

- actor / runtime identity
- recipient role
- purpose
- Task / Session / Requirement / Plan revision
- applicable Human Intent and corrections
- policy and access decision
- current Goal/KGI/Initiative position
- required and forbidden Concept sets
- token / byte / time budget
- source and Concept revisions
- unresolved conflict / stale / unknown
- final delivered bytes digest

### 4.6 Layer F: Execution, review, learning

Context Packを受けたexecutorはbounded workを実行し、別actorのauditorがsource・input・output・whole-context・approachを確認する。結果は採用、修正、実験、方式変更、停止のいずれかへ明示的に処理される。

## 5. OKF standardとKotodama profileを分離する

### 5.1 Three verdicts

#### A. `OKF_CONFORMANT`

公式OKF v0.2の最低要件だけを判定する。

- non-reserved Markdownにparseable frontmatterがある
- non-empty `type`がある
-存在するreserved fileが規約に従う
- unknown type、unknown key、missing optional field、broken cross-linkだけではfailしない

#### B. `KOTODAMA_PROFILE_PASS`

用途別producer profileを判定する。

例:

- `kotodama-public-candidate-v0.2`
- `kotodama-internal-v0.2`
- `kotodama-decision-ready-v0.2`
- `kotodama-runtime-context-v0.2`

Public profileではsource、classification、owner/reviewer分離、path escape、public hygiene、freshnessなどを追加で必須化できる。

#### C. `DECISION_READY`

特定のactor、purpose、time、Taskに対して使用可能か判定する。

```text
standard conformant
AND profile pass
AND current access allowed
AND required source revisions resolvable
AND not stale for the requested use
AND no unresolved material conflict
AND required trust tier satisfied
AND required attestation passed
AND mandatory ancestor constraints included
```

これにより、構造的に良いcandidateを「確定済み知識」と誤表示しない。

### 5.2 CLI proposal

```bash
python tools/knowledge_base.py validate --standard okf-0.2
python tools/knowledge_base.py validate --profile kotodama-public-candidate-0.2
python tools/knowledge_base.py audit --readiness structural
python tools/knowledge_base.py audit --readiness decision --actor ... --purpose ...
```

## 6. Knowledge stateを直交軸に分ける

現在の`knowledge_state`は便利だが、認識状態、文書状態、取消、時間状態が混在している。profile v0.2では以下を分離する。

| Axis | Candidate values | Meaning |
|---|---|---|
| Document lifecycle | `draft / stable / deprecated` | OKF標準の文書状態 |
| Epistemic status | `hypothesis / reported / corroborated / verified / disputed / unknown` | 主張をどの程度確認したか |
| Temporal status | `current / stale / future / expired` | 使用時点で有効か |
| Access status | `allowed / denied / revoked / expired / unresolved` | actor・purposeごとの取得可否 |
| Publication status | `internal / public_candidate / published / withdrawn` | 公開判断 |
| Authority class | `source_record / canonical_interpretation / projection` | 何を決定できるか |
| Attestation status | `not_required / missing / pass / fail / expired` | 計算結果の実行確認 |

同じConceptは、`document=stable`でも`epistemic=disputed`、`temporal=stale`、`access=denied`になり得る。単一の総合enumや総合scoreでこの差を潰さない。

## 7. Revision-bound Source Binding

### 7.1 Minimum contract

Kotodama extensionまたはbundle外のbinding recordに以下を持たせる。

```yaml
source_binding:
  source_id: SRC-...
  resource: ...
  revision_kind: git_commit | etag | version | event_sequence | content_digest
  revision: ...
  content_sha256: ...
  observed_at: ...
  authority_scope: ...
  access_policy_ref: ...
  retention_policy_ref: ...
  invalidation_key: ...
  locator_visibility: public | opaque
```

Public bundleではprivate locatorを公開せず、opaque IDとapproved digestだけを載せる。

### 7.2 Per-claim evidence

OKF標準の`source id`付きfootnoteを維持し、Kotodama側では必要に応じて以下を追加する。

- source revision
- content digest
- source span / line / JSON Pointer / event range
- extraction method revision
- transformation digest
- quoted value digest

本文の脚注proseだけを機械的なlineageと見なさない。

## 8. Concept revision and CAS

Concept pathをlogical IDとして維持し、current bytesとは別にrevisionを束縛する。

```yaml
kotodama:
  id: project/goal
  revision:
    id: KREV-...
    parent: KREV-...
    content_sha256: ...
    source_set_sha256: ...
    generated_by_invocation_ref: ...
  current_pointer_expected: KREV-...
```

Promotion時は、生成開始時のparent revisionとsource dependency revisionsが現在も同じ場合だけCASで切り替える。途中で訂正・revocation・別revisionが入った候補はcurrentにしない。

## 9. Typed relation graph

OKF標準のMarkdown linkはportable navigationとして残す。Kotodamaのmachine projectionで以下を型付けする。

```yaml
relations:
  - predicate: advances_goal
    target: goals/out-intent
    target_revision: KREV-...
    required: true
    evidence_ref: ...
  - predicate: depends_on
    target: governance/authority-boundaries
    required: true
  - predicate: conflicts_with
    target: decisions/alternative-x
    resolution_state: open
```

推奨predicate:

- `derived_from`
- `governed_by`
- `advances_goal`
- `supports_kgi`
- `measures`
- `depends_on`
- `requires_context`
- `supersedes`
- `conflicts_with`
- `invalidates`
- `implemented_by`
- `owned_by`
- `reviewed_by`
- `computed_by`
- `attested_by`

Typed edgeは標準OKFの一部だと主張せず、Kotodama profileのprojectionとしてversion管理する。

## 10. Goal / KGI model

### 10.1 North-star Goal

> 権限ある会話を、意図・根拠・境界を失わず、検証可能な成果と学習へつなげる。

### 10.2 Primary product KGI

既存ID `KGI-INTENT` を維持し、採用前に次の計算契約を確定する。

**Candidate definition: Verified intent-to-outcome completion ratio**

```text
Numerator:
  admitted intent cases due in the measurement window that contain:
  1. revision-bound Source Evidence
  2. effective reviewed Intent revision
  3. bounded Work Order / grant
  4. candidate artifact or performed outcome
  5. independent verification receipt
  6. outcome-owner acceptance or explicit policy-defined acceptance
  7. linked learning/readback disposition

Denominator:
  all admitted intent cases due in the window
  minus explicitly withdrawn/cancelled cases with owner, reason, and receipt
```

必要なguard:

- 同じcaseの重複countを禁止する
- trivial artifactでcountを水増ししない
- incomplete caseをcancelへ逃がさない
- receipt数やPR数を成果の代用にしない
- rejected/failed/inconclusive resultも履歴から消さない
- result qualityとboundary violationを別guardrailで見る

Countとratioのどちらをprimaryにするかは、baseline収集後にownerが決定する。現在の`verified intent-to-artifact vertical slices`という表現は残しつつ、artifactだけでなく求めるoutcomeまで評価する。

### 10.3 Knowledge control-plane SLOs

これらはproduct KGIを置き換えず、KGIを成立させるsystem healthである。

| ID | Definition | Hard guard / candidate target |
|---|---|---|
| SLO-KB-CONTEXT | required Concept・primary source・mandatory constraintがcontext budget内に入り、forbidden knowledgeが入らないtaskの割合 | forbidden/revoked leakageは0。quality targetはbaseline後に採用 |
| SLO-KB-INVALIDATION | source correction/revocationから、影響projectionのquarantineと再構築までの時間 | revocation後にready contextへ残る件数0 |
| SLO-KB-DECISION-READY | consequential useに必要なsource、verification、freshness、access、conflict、attestationを全て満たすConcept割合 | unknownをpassへ変換しない |
| SLO-KB-RECOVERY | fresh sessionがmaterial correctionなしに目的・制約・現在位置を復元できる割合 | obsolete instructionの再実行0 |
| SLO-KB-GROUNDING | required source recall、citation precision、claim support | unsupported material claim 0をhard guardとする |
| SLO-AGENT-BOUNDARY | invocationがidentity、grant、scope、budget、lease、stop、receiptを満たす割合 | material grant/authority violation 0 |

### 10.4 Diagnostic KPIs

- source binding completeness
- verification lag
- stale backlog age
- unresolved conflict age
- orphan Concept / edge count
- impact set precision / recall
- required Concept recall@k
- source recall@k
- mandatory constraint retention
- context size and omitted-required count
- material human correction rate
- context assembly latency and cost
- agent retry / duplicate work / coordination overhead
- rollback success rate
- metric computation attestation pass rate

KPI改善だけを成功としない。必ず`KPI -> Key Factor -> KGI -> requested outcome`の因果仮説を持たせる。

## 11. Attested Computation for every adopted metric

OKF v0.2の`Attested Computation`を、KGI/KPI定義と実測の橋に使う。

推奨構造:

```text
knowledge/metrics/kgi-intent.md
  -> links to
knowledge/computations/kgi-intent.md
  -> executor
references/metrics/compute-kgi-intent.py
  -> attester
references/attesters/kgi-intent-receipt.py
```

Computation contract proposal:

```yaml
---
type: Attested Computation
title: KGI-INTENT computation
runtime: python
parameters:
  - { name: window_start, type: date, required: true }
  - { name: window_end, type: date, required: true }
executor:
  resource: ../../references/metrics/compute-kgi-intent.md
  receipt:
    - computation_revision
    - code_sha256
    - input_snapshot_digest
    - window_start
    - window_end
    - numerator_case_ids_digest
    - denominator_case_ids_digest
    - excluded_case_ids_digest
    - numerator
    - denominator
    - result
attester:
  resource: ../../references/attesters/kgi-intent-receipt.py
---
```

`verified`はmetric定義がpolicyと一致するかを確認するdocument-level signal、attestationは各runが承認済み計算を実際に行ったかを確認するper-run signalとして分離する。

## 12. Decision-ready readiness model

単一のreadiness percentageは使用しない。次の行列で示す。

| Dimension | Result | Evidence |
|---|---|---|
| OKF standard | pass/fail | parser report |
| Producer profile | pass/fail | profile validator |
| Source resolvability | complete/partial/missing | source binding report |
| Source revision integrity | pass/fail/unknown | digest receipt |
| Verification | unverified/machine/human | `verified` events |
| Freshness | current/stale/unknown | date + source revision |
| Conflict | none/open/resolved | conflict record |
| Access | allowed/denied/revoked/unresolved | policy decision receipt |
| Attestation | not-required/pass/fail/missing | runtime receipt |
| Context inclusion | included/omitted/unresolved | Context Pack manifest |
| Decision readiness | ready/not-ready | deterministic rule and purpose |

現行の100% `retrieval readiness`は、名称を`structural retrieval eligibility`へ変更し、unverified candidateをdecision-readyと解釈できないようにする。

## 13. Context Pack contract

### 13.1 Required identity and purpose binding

```yaml
context_pack:
  id: CTX-...
  revision: ...
  assembled_at: ...
  expires_at: ...
  assembler_version: ...
  actor_ref: ...
  runtime_identity_ref: ...
  recipient_role: ...
  purpose: ...
  task_ref: ...
  task_revision: ...
  session_ref: ...
  intent_ref: ...
  intent_revision: ...
  policy_revision: ...
  access_decision_ref: ...
  grant_ref: ...
  budget:
    max_tokens: ...
    max_bytes: ...
    max_concepts: ...
```

### 13.2 Content manifest

各entryに以下を持つ。

- Concept ID and revision
- source-set digest
- required / optional / supporting
- relation to Goal/KGI/Task
- trust/freshness/conflict/access verdict
- exact selected source excerpts or source refs
- omission reason
- redaction/transformation revision
- instruction treatment: evidence-only / executable-policy / prohibited

Pack全体にmanifest digest、rendered bytes digest、最終agent input digestを持たせる。人が見た最新版と、実際にagentへ渡した版を別表示できるようにする。

### 13.3 Fail-closed conditions

- mandatory ancestor context missing
- source revision unresolved
- actor/purpose access unresolved
- material conflict open
- critical Concept stale
- revoked/withdrawn information selected
- budget内にmandatory constraintsを収められない
- generated context attempts to relax parent policy or grant
- delivered bytes differ from recorded digest

## 14. Retrieval architecture

### Stage 0: exact resolution

Goal/KGI/Task/Intent/Decision/Source ID、current revision、mandatory policy、grantをdeterministically解決する。

### Stage 1: lexical baseline

日本語を含むため、単純な`\w+` substringだけでなく、以下を比較する。

- exact ID and alias
- Unicode normalized title/tag
- character n-gram
- BM25 with Japanese-aware tokenization
- source footnote and relation fields

### Stage 2: graph expansion

`requires_context`、`governed_by`、`depends_on`、`supersedes`、`conflicts_with`等のtyped edgeで必要な祖先・依存を追加する。similarityでmandatory contextを追い出さない。

### Stage 3: optional semantic retrieval

Embeddingやrerankerは、同じevaluation fixturesでlexical+graph baselineを有意に上回り、access、revocation、latency、cost、rollbackを悪化させない場合だけ採用する。

### Stage 4: source opening and claim grounding

Consequential answerではConcept summaryだけでなく、権限内の現在source revisionを開く。出典に到達できない場合は`unknown`または`needs_resolution`とする。

## 15. Retrieval and context evaluation

### 15.1 Fixture contract

```yaml
case_id: EVAL-...
actor_ref: ...
purpose: ...
task_ref: ...
query_or_request: ...
required_concepts: [...]
required_sources: [...]
required_constraints: [...]
forbidden_concepts: [...]
forbidden_sources: [...]
expected_unknowns: [...]
expected_next_action: ...
max_tokens: ...
max_bytes: ...
```

### 15.2 Required suites

1. Goal/KGI/Taskのexact lookup
2. 日本語の同義・表記揺れ
3. 類似するが別案件のfalse neighbor
4. stale sourceと新revision
5. superseded instruction
6. source correction during assembly
7. access revoked before delivery
8. conflicting corrections
9. mandatory contextがbudgetを超えるケース
10. generated document内の命令をevidenceとして扱うケース
11. fresh-session recovery
12. KPIが改善するがoutcomeが改善しないケース
13. agent/team変更の前後比較
14. rollback後にrevoked knowledgeを復活させないケース

### 15.3 Metrics

- required concept recall@k
- required source recall@k
- citation precision and claim support
- mandatory constraint retention
- forbidden/revoked leakage
- material correction rate
- task/outcome success
- context size, latency, cost
- impact set precision/recall
- stale-to-quarantine and stale-to-rebuild latency

## 16. Refresh, invalidation, and promotion loop

```text
1. Observe exact source change / correction / access event
2. Verify actor, authority, source revision, and event idempotency
3. Calculate affected Concept, index, context, metric, decision views
4. Quarantine affected current projections before rebuilding
5. Produce candidate revisions only for affected nodes
6. Independently review source fidelity, constraints, conflict, classification
7. CAS-promote only when parent and all dependency revisions still match
8. Rebuild catalog/graph/search/context projections
9. Run targeted positive and negative readback fixtures
10. Record disposition, metrics, residual unknowns, and rollback pointer
11. Notify only material changes through the topmost supervising path
```

### Anti-race requirements

- candidate generated from old source cannot overwrite a newer current revision
- rollback cannot restore revoked access or withdrawn consent
- unchanged dependency digest suppresses unnecessary regeneration
- repeated identical blocker is deduplicated and escalated after a bounded threshold
- one mutable Concept revision has one writer

## 17. Agent architecture

Permanent agent names are not the unit of control. `Agent Definition`と`Agent Invocation`を分離する。

| Responsibility | Input | Output | Hard boundary |
|---|---|---|---|
| Source Observer | source ref, grant, expected revision | observed revision/digest event | no interpretation/promotion |
| Knowledge Extractor | authorized source bytes, extraction contract | candidate claims and citations | no self-verification |
| Resolver / Librarian | candidates, current graph, conflicts | bounded Concept revision and impact set | no policy/authority expansion |
| Conflict Detector | competing claims/revisions | conflict record and affected uses | no silent winner selection |
| Independent Auditor | source, candidate, context, outcome | findings and disposition | distinct runtime actor; no execution |
| Retrieval Evaluator | fixtures, retriever revision | signed evaluation report | no changing fixtures to improve score |
| Context Assembler | Task/Intent/Policy/Grant + evaluated indexes | Context Pack and digest | no execution; fail closed |
| Builder / Executor | bounded Work Order + Context Pack | artifact/effect receipt | no promotion/self-approval |
| Method Optimizer | failure evidence + candidate method | bounded experiment proposal/results | no unconditional self-modification |

Invocation必須項目:

- exact model/runtime identity and version
- Agent Definition revision
- Task/Work Order/Grant/Lease refs
- source and knowledge scope
- tool/MCP/action grants
- budget, deadline, max depth, stop/kill, retry/idempotency
- input Context Pack digest
- output/evidence sink
- parent invocation and accountability owner
- independent reviewer invocation ref

## 18. Audit model

毎session/work cycleでcontext audit自体は行い、深さをriskで変える。

### Tier 0 — deterministic, every change

- schema/profile/conformance
- digest/revision/link/edge integrity
- access/revocation decision presence
- generated output drift
- one-writer and self-verification checks
- hard guardrails

### Tier 1 — low-risk agent review

- source-to-claim fidelity
- missing constraints/unknowns
- duplicate/obsolete knowledge
- retrieval/context fixture regression

### Tier 2 — consequential independent review

- originating intent and KGI contribution
- alternative architecture
- side effects and failure cases
- decision-ready use
- adoption/rollback recommendation

### Tier 3 — explicit human gate

- Human Intent change
- irreversible/external/high-impact effect
- public release
- access/classification/retention authority change
- production deployment or promotion

Audit outputには必ず`continue / revise / experiment / change_approach / stop`とowner、期限、evidence refを付ける。review record数は成果指標にしない。

## 19. Continuous optimization loop

```text
observe outcome and control metrics
  -> identify one material failure or opportunity
  -> write causal hypothesis and falsifier
  -> freeze evaluation set and guardrails
  -> bounded disposable experiment
  -> independent comparison
  -> canary one scoped path
  -> adopt, revise, or reject
  -> monitor outcome, cost, latency, safety
  -> auto-revert regression within standing reversible authority
  -> retain negative and inconclusive learning
```

比較対象:

- current method
- simplest deterministic alternative
- proposed lexical/graph/semantic method
- no-change baseline

採用条件は検索scoreだけでなく、元のoutcome、intent retention、access/revocation、安全、費用、遅延、運用複雑性、rollbackを含む。

## 20. Bundle federation and privacy zones

Public repositoryは引き続きpublic-safe bundleだけを保持する。将来は次のzoneをContext Gateway越しにfederateする。

| Zone | Contents | Distribution |
|---|---|---|
| Public | public_candidate / published concepts, public references | git/static distribution |
| Internal | organizational knowledge without restricted body | authenticated internal bundle |
| Restricted | personal, customer, security, operational details | purpose-bound retrieval only |
| Secret | credentials/keys and equivalent | never copied into OKF body; handle/reference only |

Cross-zone relationはopaque stable reference、classification、required access policy、digestだけを公開可能な範囲で持つ。public bundleへprivate summaryを自動コピーしない。

## 21. Phased implementation plan

### Phase 0 — Correctness and integration footing

**Purpose:** 現行foundationを誤解なく安全に採用できる状態にする。

Work:

- OKF標準validatorとKotodama profile validatorを分離
- date/date-time discrepancyを修正
- `retrieval readiness`をstructural/decision readinessへ分割
- PR #48のbase integration pathを明示
- 初期9Conceptを別actorがsourceと照合
- official spec locatorを現在のcanonical repositoryへ更新

Exit:

- standard conformanceとprofile resultが別表示
- 0 standard errors
- 0 profile errors
- initial Conceptsのverification statusが事実通り
- exact integration base/head/check/review stateがread back可能

### Phase 1 — First-class Goal, KGI, Factor, Metric, Computation

Work:

- Goal/Outcome/Key Factor/KGI/KPI/Initiative Concept templates
- referential validator
- `KGI-INTENT` Metric Concept
- first Attested Computation and deterministic attester
- baseline measurement plan and anti-gaming rules

Exit:

- KGIにowner、formula、window、evidence、calculation revision、receiptがある
- undefined Goal/KGI refsはfailする
-同じinput snapshotから同じresultが再現される

### Phase 2 — Revision-bound provenance and typed graph

Work:

- Source Binding schema
- Concept Revision schema
- typed Relation schema
- source-to-concept reverse index
- impact graph
- public opaque reference policy

Exit:

- 全critical Conceptがexact source revision/digestへ辿れる
- source変更のaffected setをdeterministically列挙できる
- stale path replacementをdigest mismatchで検出できる

### Phase 3 — Evaluation corpus and retrieval baseline

Work:

- fixture schema
- representative authorized cases and adversarial synthetic cases
- exact/lexical/Japanese n-gram/BM25/graph baseline
- reproducible evaluation receipt

Exit:

- retriever変更を同じfixtureで比較可能
- required/forbidden contextとmaterial correctionを測定可能
- embedding導入の可否をevidenceで判断可能

### Phase 4 — Deterministic Context Pack

Work:

- Context Pack schema
- actor/purpose/Task/Intent/Policy/Grant binding
- byte/token/concept budgets
- mandatory ancestor resolution
- final delivered input digest and human-visible readback

Exit:

- fresh sessionが同じrevisionへ復元可能
- displayed contextとactual inputの差分を検出可能
- stale/revoked/conflicted/denied/missing mandatory contextはfail closed

### Phase 5 — Incremental refresh, invalidation, and CAS

Work:

- source/change events
- quarantine-before-rebuild
- dependency digest comparison
- CAS current pointer
- targeted regeneration and readback
- rollback without access resurrection

Exit:

- correction、race、revocation、rollback negative testsがpass
- unchanged inputsでno-op
- affected-only rebuildをreceiptで確認

### Phase 6 — Federated Context Gateway

Work:

- public/internal/restricted bundle registry
- current access decision adapter
- private locator opacity
- purpose-bound retrieval
- cache/log/redaction policy

Exit:

- unauthorized cross-zone retrieval 0
- revoke/expiry after cache invalidation verified
- public bundleにprivate bytes or locators 0

### Phase 7 — Runtime agent binding and improvement loop

Work:

- Agent Definition / Invocation / Work Order / Grant / Lease integration
- runtime identity and model provenance
- independent reviewer binding
- bounded experiment/canary/rollback
- topmost material-update notification

Exit:

- one real authorized goal completes across a condition change and fresh session
- actual outcome, context, source, execution, review, learning all share traceable revisions
- regression automatically stops/reverts within granted boundary

## 22. Prioritized backlog

### P0

1. Separate standard/profile/readiness verdicts.
2. Correct OKF v0.2 date fields.
3. Rename/split misleading retrieval-readiness metric.
4. Establish base-to-main integration train and latest-push independent review.
5. Independently verify the initial nine Concepts.
6. Create Goal/KGI/Metric/Attested Computation templates.
7. Make unresolved Goal/KGI/Initiative references fail profile validation.
8. Add source revision/content digest binding for critical Concepts.

### P1

9. Add Concept revision and source-set digest.
10. Add typed relation projection and reverse impact index.
11. Add evaluation fixture schema and initial corpus.
12. Add Japanese lexical baseline and graph expansion.
13. Add deterministic Context Pack schema and assembler.
14. Bind human-visible context and actual invocation input digest.
15. Add stale/correction/revocation/race negative tests.

### P2

16. Add incremental invalidation and CAS promotion.
17. Add federated bundle registry and access adapter.
18. Add optional embedding/reranker experiment only after baseline.
19. Bind agent runtime identities, grants, leases and reviewer invocations.
20. Enable bounded unattended optimization with monitored rollback.

## 23. First three implementation PRs

### PR A — OKF v0.2 conformance correction

Scope only:

- date fields
- standard/profile validator separation
- metric name split
- tests and documentation

No source registry, runtime, or new storage.

### PR B — Goal/KGI and attested metrics

Scope only:

- first-class Goal/Outcome/Metric/Factor concepts
- referential validation
- KGI computation and deterministic attester
- synthetic receipt fixtures

No claim of real KGI baseline until authorized input ledger exists.

### PR C — Source binding and evaluation contract

Scope only:

- source revision/digest extension
- typed relation sidecar/projection
- retrieval/context fixture schema
- exact/lexical/graph baseline evaluation

Embedding remains a separately measured experiment.

## 24. Decisions requiring accountable adoption

The following must not be silently chosen by an implementation agent.

- `KGI-INTENT`をcountかratioのどちらでprimary表示するか
- measurement windowとcancel/exclusion policy
- product KGI target and deadline
- trust tier required per purpose
- source classごとのfreshness/review SLA
- which curated interpretation can become owner-reviewed canonical knowledge
- profile v0.2 extension keys and versioning/migration policy
- public/internal/restricted bundle boundaries
- Context Gateway production owner and runtime
- storage/event-log implementation after bounded SQLite pilot
- human gate thresholds for publication, irreversible and high-impact actions

## 25. Anti-patterns to reject

- OKFを会社全体の唯一のtransactional databaseにする
- Markdown page数、agent数、review数、PR数をKGIにする
- source pathだけをrevision証拠にする
- structural validationをsemantic correctnessと呼ぶ
- unverified candidateをdecision-readyとして数える
- embedding similarityでGoal、authority、mandatory constraintsを置換する
- generated contextからpolicy、grant、Human Intentへ逆流させる
- auditorが同じruntime invocationでexecutorを兼ねる
-全sourceを毎回再生成する
- rollbackでrevoked dataやconsentを復活させる
- private knowledge bodyをpublic bundleへ要約コピーする
- benchmark改善だけで実際のtask outcome改善を主張する
- green CIやmergeable stateをrelease/readiness証拠に拡張する

## 26. Definition of done for the OKF control plane

次が一つのauthorized real requestで実証されるまで、Knowledge Control Plane completeとはしない。

1. exact Source EvidenceとHuman Intent revisionがある。
2. Goal、KGI、Key Factor、Initiative、Taskの関係が解決される。
3. actor/purpose/access/grantに応じたContext Packが作られる。
4. mandatory constraintsがbudget内に保持される。
5. bounded executorがそのexact inputで作業する。
6. distinct auditorがsource、input、output、whole context、approachを確認する。
7. outcome ownerまたは定義済みpolicyが実成果を判定する。
8. KGI/KPIがAttested Computationとreceiptで再計算される。
9. 途中で一つのsource correctionまたはrevocationを入れ、影響projectionが先に隔離される。
10. fresh sessionがcurrent revisionだけを使って再開する。
11. 古い候補、取消資料、forbidden knowledgeが再注入されない。
12. failure時にrollbackし、source historyとlearningを保持する。
13. Human-visible context、actual agent input、artifact、receipt、metric runが同じrevision chainへ辿れる。

## 27. Immediate recommendation

現時点で最も価値が高い順序は次である。

```text
A. spec/profile/readinessの意味を正す
B. Goal/KGIをfirst-classにして計算をattestする
C. source revision/digestとtyped relationを付ける
D. evaluation fixtureを先に作る
E. deterministic Context Packを一件で証明する
F. invalidation/CASを条件変更とrevocationで証明する
G. その後にembedding、federation、runtime agent最適化を進める
```

この順序なら、先に巨大なDB、RAG、常駐agent群を作らず、元の意図に直接効く最小のvertical sliceから正しさを積み上げられる。

## 28. Non-authorization

This proposal does not authorize merge, publication, production deployment, provider access, private-source ingestion, billing, credential use, access-policy mutation, repository protection changes, Promotion, Current Truth, Public Beta, or Final Human GO. Each requires its existing accountable path and exact evidence.
