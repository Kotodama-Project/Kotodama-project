# Agent Foundry Operations

> Status: **candidate-only design**  
> Machine-readable owner: [`../governance/agent-registry.json`](../governance/agent-registry.json)

Kotodama の Agent Foundry は「Agent を大量に生成する factory」ではありません。

**必要な能力を定義し、評価し、最小権限で有効化し、観測し、改善・統合・退役まで管理する Agent lifecycle / portfolio control plane** です。

## 1. Agent lifecycle

```text
Need / KGI gap
  ↓
Agent design candidate
  ↓
Eval suite
  ↓
Implementation candidate
  ↓
Sandbox / offline evaluation
  ↓
Risk / authority review
  ↓
Capability Grant
  ↓
Bounded activation
  ↓
Telemetry / receipts
  ↓
Improve / merge / retire
```

新しい Agent を作る前に、既存 Agent の capability を改善・統合できないか確認します。

**Agent 数は KGI ではありません。**

## 2. Registry entry

active Agent は最低限、次を machine-readable に持ちます。

- `id / name`
- purpose / beneficiary
- activation state
- authority
- input knowledge / fact families
- outputs
- capabilities
- prohibited actions
- KGI / Key Factor links
- eval gate
- rollback
- implementation binding
- runtime evidence

未登録 Agent の activation は forbidden です。

## 3. Authority

初期 state は三段階で考えます。

- **read_only** — 読む・比較する・finding を出す
- **proposal_only** — Issue / Work Order / patch / eval candidate を作る
- **bounded_execute** — 別途 Capability Grant を持つ限定 execution

P0/P3 の maintenance Agent は `read_only` または `proposal_only` から始めます。

Agent は自分自身に `bounded_execute` を付与できません。

## 4. 初期 Agent portfolio

### OKF Steward

Goal / KGI / Phase と evidence を比較し、

- KGI gap
- phase gate 未達
- priority mismatch
- metric 更新候補

から bounded next work を提案します。

### Knowledge Curator

Knowledge corpus を監査し、

- stale
- duplicate
- contradiction
- missing provenance
- broken projection

を検出して candidate patch を作ります。

### Agent Auditor

Agent portfolio 全体を比較します。

- eval regression
- capability overlap
- over-permission
- unused agent
- cost / latency / quality regression
- missing rollback
- obsolete implementation

を検出し、change / merge / retire 候補を作ります。

### Context Compiler

task に必要な canonical knowledge、provenance、constraint だけを組み立てます。

### Work Orchestrator

verified intent を Work Order candidate へ分解し、Agent / Human lane を選びます。

### Evidence Auditor

claim と verification evidence の binding を確認します。

### Quality Red Team

Agent / context / workflow の adversarial case と regression case を作ります。

## 5. Agent Auditor の監査軸

### Performance

- task success
- critical eval pass rate
- correction rate
- hallucination / unsupported claim rate
- latency
- token / compute / provider cost

### Governance

- capability grant が task に対して過大でないか
- prohibited action を試していないか
- consent / retention / sensitivity を守っているか
- Promotion / Current Truth を短絡していないか
- rollback が実際に可能か

### Portfolio

- 同じ capability の Agent が重複していないか
- 小さい一つの Agent / tool に統合できないか
- routing が複雑化していないか
- inactive / unused Agent が残っていないか
- deprecated model / prompt / tool を使っていないか

### Efficiency

- 同品質で context を減らせるか
- deterministic tool で LLM call を置き換えられるか
- model tier を下げても eval を満たすか
- cache / reuse が可能か

ただし cost 改善は quality / governance より下位です。

## 6. 新 Agent を作る条件

新規 Agent candidate は少なくとも以下を答えます。

1. どの KGI / Key Factor gap を解くか
2. 既存 Agent / tool ではなぜ不足か
3. input / output contract は何か
4. authority は何が必要か
5. eval は何か
6. failure mode は何か
7. rollback / retirement はどうするか
8. cost / complexity 増加に見合うか

答えられない場合は、まず新 Agent を作らず既存 capability を改善します。

## 7. Merge / retire

### Merge candidate

- capability overlap が大きい
- routing cost が高い
- separate authority boundary が不要
- 統合後も eval と rollback が明確

### Retirement candidate

- 一定期間 unused
- replacement Agent が全 critical eval で同等以上
- cost-quality frontier で恒常的に劣る
- underlying tool / model が deprecated
- purpose 自体が Goal / KGI に不要になった

retire しても historical evidence は消しません。

## 8. Agent が Agent を改善する loop

```text
Telemetry / Eval / Failure receipt
  ↓
Agent Auditor finding
  ↓
Candidate agent change
  ↓
isolated eval
  ↓
baseline comparison
  ↓
Quality Red Team
  ↓
Candidate Promotion
  ↓
canary / bounded activation
  ↓
promote or rollback
```

Agent が自動でできる範囲:

- eval case candidate の追加
- prompt / context / routing / tool configuration の候補
- code patch candidate
- merge / retire Issue candidate
- Work Order candidate

Agent が自動でしてはいけない範囲:

- 自分への Capability Grant
- 自分に不利な eval の削除
- evidence の改ざん
- runtime activation
- Promotion / Current Truth 更新
- Final Human GO / Public Beta GO

## 9. Eval の考え方

単一の aggregate score だけを見ません。

### Knowledge Curator

- stale detection recall
- false stale rate
- contradiction recall
- canonical/candidate confusion
- provenance preservation

### Agent Auditor

- actual regression detection
- false retirement recommendation
- authority overscope detection
- duplicate capability detection

### OKF Steward

- KGI / phase link correctness
- evidence-less metric update rejection
- priority recommendation quality
- bounded work generation quality

### Evidence Auditor

- unsupported claim detection
- exact artifact / revision binding
- false promotion allowance

Critical boundary violation は平均点で相殺しません。

## 10. 最適化の順序

Kotodama の Agent optimization は次の優先度に従います。

1. Human Intent and authority
2. governance integrity
3. knowledge correctness
4. task success / quality
5. recoverability
6. human structuring load
7. latency
8. cost

たとえば「安くなったが unsupported claim が増える」は改善ではありません。

## 11. P2 → P3

### P2 Agent Foundry

- registry
- eval suites
- capability map
- activation gate
- merge / retire rules
- cost-quality comparison

を実装します。

### P3 Agentic Maintenance

その上で、

- OKF Steward
- Knowledge Curator
- Agent Auditor
- Context Compiler
- Evidence Auditor
- Quality Red Team

を proposal-only で接続します。

finding から candidate Issue / Work Order / PR までを Agent が作れるようにし、人間は重要な判断へ集中します。

目標は **「Agent が自分たちと Knowledge を保守するが、自分たちの authority を勝手に拡張できない」** 状態です。
