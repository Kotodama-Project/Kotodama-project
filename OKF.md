# Kotodama OKF — Strategic Control Plane

> Status: **candidate-only control plane**  
> Reviewed: **2026-09-07**  
> Machine-readable canonical owner for Goal / KGI / Key Factors / phase IDs: [`governance/okf.json`](governance/okf.json)

Kotodama の OKF は、単なる「目標一覧」ではありません。  
**Human Intent → Goal → KGI → Key Factors → Phase → Work → Evidence → Promotion → Learning**
を一つの監査可能な制御面としてつなぎます。

この文書は人間向け projection です。数値・ID・phase state の機械可読な正本は
`governance/okf.json` に置きます。`PASS` や agent の提案は Human approval、
Capability Grant、Promotion、Current Truth、runtime activation、Final Human GO、
Public Beta GO を自動的には作りません。

## 1. Goal

> **人間が自然に話し、相談し、仕事を依頼するだけで、Kotodama が意図を監査可能な仕事・成果・学習へ変換し、必要な正しい知識と適切なエージェントを継続的に整備できる Company OS になる。**

重要なのは「Agent を増やすこと」ではありません。

- 人間が毎回プロジェクト全体を説明し直さなくてよい
- Agent が古い・誤った・競合した情報を前提にしない
- 何を目的に、どの情報を根拠に、誰が何を許可したか追跡できる
- Agent が自分たちの品質・重複・権限・cost を監査できる
- 改善候補は自動で作れるが、authority を捏造しない
- 成果と失敗が Knowledge / Eval / Work planning へ戻る

という状態を作ることが Goal です。

## 2. 現在の状況

既存の Kotodama には強い土台があります。

- README に Human Intent、Evidence Chain、Company Pack、Context、Workforce、Business/Learning の全体像がある
- Company governance starter、schema、validator、review chain がある
- Source / Decision / Work / Verification / Promotion / Current Truth を短絡させない原則がある
- Candidate-only / read-only / `NO_GO_UNPUBLISHED` の境界が明示されている
- Public Preview の claim を live runtime と混同しない設計がある

一方、Company OS 全体を継続運用する control plane としては次が不足しています。

1. **Goal/KGI と実際の work がつながっていない**  
   ROADMAP は Public Beta へ向けた実装・公開条件をよく追跡していますが、プロジェクトの North Star、KGI、改善優先度を日々の work に戻す機械可読な層がありません。

2. **Knowledge の横断 registry がない**  
   README、STATUS、ROADMAP、docs、schema、template、runtime candidate、tool、test、example は豊富ですが、
   「どの fact family の正本はどれか」「いつ stale とみなすか」「どの projection が正本を参照するか」を一か所で監査できません。

3. **Agent portfolio の registry がない**  
   Agent Foundry / AI Workforce の方向はありますが、各 Agent の purpose、authority、eval、capability、rollback、重複、retirement を横断比較する control plane がありません。

4. **自己監査→改善候補の閉ループがない**  
   既存の deterministic validator は強い一方、Knowledge / Agent / OKF 自体の gap を継続的に発見して bounded work へ変換する loop はまだありません。

5. **live baseline がない**  
   Public Voice/Discord E2E、live Company-wide Context、Public Beta、Final Human GO は未成立なので、下記 KGI の多くは意図的に `not_measured` から開始します。

## 3. KGI

KGI は「実装量」ではなく、Kotodama が Company OS として価値を出しているかを測ります。

| ID | KGI | Target | 最初に測る Phase |
|---|---|---:|---|
| **KGI-01** | Verified intent-to-outcome completion | eligible work の **80%以上** が検証済み outcome / Promotion Candidate まで到達 | P4 |
| **KGI-02** | Promotion traceability integrity | Promotion / Current Truth 変更の **100%** が Source・authority・Work/Artifact・Verification に束縛 | P4 |
| **KGI-03** | Knowledge reliability | active canonical fact family の **95%以上** が freshness SLA 内、severity-1 contradiction を Promotion に通さない | P1 |
| **KGI-04** | Agent reliability and governance | critical eval pass **95%以上**、active Agent の registry/eval/grant/rollback **100%** | P2 |
| **KGI-05** | Human structuring load | eligible request の material clarification **P50 ≤ 1** | P4 |
| **KGI-06** | Control-plane responsiveness | critical finding が owner + bounded next work を持つまで **P95 ≤ 1日** | P3 |

### KGI の読み方

- `not_measured` は失敗ではなく、まだ live evidence がないことを正確に表します。
- KGI-01 や KGI-05 を良くするために KGI-02 / KGI-04 を犠牲にしてはいけません。
- Agent が数値を更新する場合も、元の receipt / eval / observation へ binding します。
- target 変更も通常の candidate → review → Promotion の対象です。

## 4. Key Factors

### KF-01 — Canonical Knowledge Base

必要な正しい情報を **fact family + canonical owner + provenance + freshness + authority**
として整備します。

Agent は検索結果を「真実」とみなすのではなく、canonical source と候補情報を区別します。

### KF-02 — Explicit Strategy and Metrics

Goal、KGI、Key Factor、Phase、Work を ID で接続します。

「今週たくさん作った」ではなく、
**どの KGI gap を縮めるために何を作り、何が evidence で改善したか**
を追跡します。

### KF-03 — Agent Foundry and Registry

すべての active Agent に最低限、以下を要求します。

- purpose / beneficiary
- input / output
- capability / authority
- prohibited actions
- eval suite / baseline / target
- latency / cost / failure modes
- owner / rollback
- duplicate or replacement relationship
- retirement condition

### KF-04 — Evidence and Governance

既存の Kotodama の最重要原則です。

```text
Source
  -> Intent Candidate
  -> Human / Policy Decision
  -> Work Order
  -> Capability Grant
  -> Execution
  -> Verification Receipt
  -> Promotion Gate
  -> Promotion Decision
  -> Current Truth
```

Agentic optimization はこの chain を短絡しません。

### KF-05 — Context Compiler

Agent に「全部のデータ」を雑に渡すのではなく、task ごとに必要な情報だけを組み立てます。

Context bundle は最低限、

- canonical source
- provenance
- freshness
- competing candidate
- permission
- task-specific constraints

を持ちます。

### KF-06 — Evaluation and Observability

Agent と Knowledge の改善を感覚で判断しません。

測るもの:

- task success / critical eval
- correction rate
- policy / authority violation
- knowledge freshness / contradiction
- latency
- token / compute / external cost
- human clarification
- rollback frequency
- promotion rejection reason

### KF-07 — Closed-loop Orchestration

理想の loop:

```text
Audit
  -> Finding
  -> Priority against KGI
  -> Candidate Work Order
  -> Context Compile
  -> Agent / Human execution
  -> Verification
  -> Candidate change
  -> Review / Promotion
  -> Registry + Knowledge + Eval update
  -> Re-audit
```

### KF-08 — Human Authority and Simple UX

内部 governance は厳密でも、人間の UI は軽くします。

人間に確認するのは主に、

- 本当に重要な曖昧さ
- authority / consent
- irreversible or high-impact action
- Promotion / GO

です。

## 5. Phase

### P0 — Control Plane Baseline — **現在**

作るもの:

- `governance/okf.json`
- `governance/knowledge-registry.json`
- `governance/agent-registry.json`
- `governance/audit-policy.json`
- JSON Schema
- read-only audit CLI
- PR / daily deterministic audit

Exit:

- 4 registry が schema-valid
- repository classification coverage ≥ 98%
- canonical source の欠落を検出できる
- active Agent を registry / eval / authority / runtime evidence なしで扱えない

### P1 — Canonical Knowledge

- fact family を実データへ適用
- stale / contradiction / duplicate detection
- provenance-aware retrieval
- Context bundle contract
- KGI-03 baseline

### P2 — Agent Foundry

- Agent eval harness
- capability map
- Agent duplication / merge / retirement
- cost-quality regression
- activation gate
- KGI-04 baseline

### P3 — Agentic Maintenance Loop

まず `proposal-only` で以下を動かします。

- **Knowledge Curator**
- **Agent Auditor**
- **OKF Steward**

Agent は finding から Issue / Work Order / PR candidate を作れますが、
Promotion や runtime activation は行いません。

### P4 — Dogfood End-to-End

実際の bounded dogfood で、

`Office / Voice -> Intent -> Work -> Artifact -> Verification -> Promotion Candidate`

を回し KGI-01 / 02 / 05 を測ります。

### P5 — Public Beta Gate

Public Beta は「docs が揃った」ではなく、

- live install / restart / rollback / restore
- Voice / Discord E2E
- consent / retention / deletion enforcement
- security / privacy
- operational SLO
- Agent critical eval
- support / incident path
- **Final Human GO**

が evidence で揃ってから判断します。

### P6 — Self-Optimizing Company OS

Agent と Knowledge 自体を継続改善します。

- A/B / canary eval
- Agent merge / retire
- prompt / model / tool / context policy optimization
- Knowledge compaction
- regression auto-stop / rollback
- cost-quality optimization

ただし最適化順序は常に:

**Human Intent & authority > governance integrity > knowledge correctness > quality > recoverability > human load > latency > cost**

です。

## 6. Agent が Agent と Knowledge を整備する

目標状態では、人間が毎回整理しません。

### Knowledge Curator

- stale source を検出
- competing facts を束縛
- canonical owner 候補を提案
- docs / index / context projection の修正 PR を作る
- provenance が弱い情報を Current Truth 候補から外す

### Agent Auditor

- Agent の eval regression を検出
- capability overlap を比較
- 権限過多を検出
- unused / inferior Agent の retire / merge 候補を出す
- 新 Agent 作成より既存 Agent 改善が良い場合はそれを優先する

### OKF Steward

- KGI gap と audit finding を接続
- work の優先順位を提案
- metric evidence を更新候補にする
- phase exit gate の未達を可視化する

### Evidence Auditor / Quality Red Team

- 「できた」という claim が evidence を超えていないか確認
- adversarial / regression eval を追加
- Promotion を止めるべき候補を明示する

## 7. 監査の頻度

| Cadence | 実行 | Authority |
|---|---|---|
| PRごと | schema / registry / inventory / boundary | read-only |
| 毎日 | repository inventory / freshness | read-only |
| 毎週 | Knowledge + Agent portfolio review | proposal-only |
| 毎週 | KGI / Phase / priority review | proposal-only |
| 毎月 | governance / authority / retention / architecture review | human + agent |

初期の GitHub Actions は deterministic audit だけを自動実行します。
Agentic review は P3 で proposal-only として接続します。

## 8. 何を「最適化」と呼ぶか

Agent を増やすことは最適化ではありません。

改善候補は少なくとも次を比較します。

1. correctness / task success は上がるか
2. Human Intent と authority を守るか
3. rollback できるか
4. context を減らせるか
5. duplicate Agent / duplicate Knowledge を減らせるか
6. human clarification を減らせるか
7. latency / cost を下げられるか

quality や governance が落ちる cost 削減は reject します。

## 9. この変更で「成立しない」もの

この control plane を追加しても、次は成立しません。

- Agent runtime が live になった
- Public Voice Bot が動いた
- Discord access が公開された
- Company-wide Context Platform が deployed になった
- Human approval / Capability Grant が作られた
- Current Truth が自動更新された
- Final Human GO が完了した
- Public Beta が open になった

これは **P0 の制御面**です。  
自律化を安全に始めるために、まず「目的・正本・Agent・監査」を明示します。
