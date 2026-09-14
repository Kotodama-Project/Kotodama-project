# Agent Swarm × Kotodama Adoption Candidate

これは、Kotodama の governance chain と agent swarm の実行単位を対応づける
public-preview-only の設計候補です。ここでいう swarm は「エージェントを大量に
起動すること」ではなく、root orchestrator が独立した bounded worker に仕事を分け、
各 worker の対象・親子 edge・workspace / revision・handoff・lease / TTL・stop
condition・結果を比較可能にしたうえで、root が統合・検証する構造を指します。

## Primary-source findings

OpenAI Agents SDK の公式ガイドは、複数 agent の orchestration を、LLM に流れを
決めさせる方式とコードで流れを決める方式に分けています。典型的な二つの形は、
manager が specialist を `agent.asTool()` として呼び出す **agents as tools** と、
triage agent が specialist へ制御を渡す **handoff** です。[Agent Orchestration
guide](https://openai.github.io/openai-agents-js/guides/multi-agent/) は、依存しない
仕事はコードで並列実行でき、最終回答・共有 guardrail を root が所有する場合は
manager pattern が適すると説明しています。

同 SDK の公式説明では、guardrail は agent の最初／最後だけでなく、各 function-tool
呼び出しの前後に置けます。agent-level の guardrail だけでは delegated specialist
の各作用を覆えないため、作用境界は tool / handoff の近くで再確認する必要があります。
[Guardrails guide](https://openai.github.io/openai-agents-python/guardrails/) を参照して
います。また SDK は tracing、sessions、sandbox agents、human-in-the-loop を提供
しますが、それらの機能を有効にしたこと自体は Kotodama の Work Order や Human GO
ではありません。[OpenAI Agents SDK overview](https://openai.github.io/openai-agents-python/)
にある runtime capability と、Kotodama の evidence gate は分離します。

Anthropic の公式 engineering report は、orchestrator-worker で専門 subagent を
独立 context で並列に走らせると、breadth-first の調査で有効だと説明しています。
同時に、multi-agent は通常の chat より大幅に token を消費し、依存関係が密な仕事や
全員が同じ context を必要とする仕事には向かない、と報告しています。曖昧な task
説明は重複・欠落・無限探索を生むため、objective、output format、tools、境界を各
worker に明示し、complexity に応じて agent 数を制限する必要があります。[How we
built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
の orchestrator-worker、cost、decomposition、prompt engineering の知見を採用
しています。

## Kotodama mapping

```text
Source Evidence
  -> Intent Candidate
  -> Decision
  -> Work Order (root-owned swarm plan)
  -> Capability Grant (per worker, if ever authorized privately)
  -> Change Candidate (worker output, never Current Truth)
  -> Verification Receipt (independent verifier)
  -> Promotion Candidate / Decision
  -> Current Truth
```

public candidate が固定するのは、Source / Intent / Work Order に相当する計画情報と、
future worker handoff の比較項目です。worker は public 側で起動せず、public schema は
Capability Grant、実行 receipt、Promotion、Current Truth を発行しません。

### Root / worker responsibilities

| 役割 | Kotodama での責任 | public candidate の扱い |
|---|---|---|
| root orchestrator | intent を bounded work order にし、assignment を分け、結果を統合する | `root_task_ref`、`root_operation_ref`、budget、root policy を固定する |
| worker | 一つの objective と ownership の範囲で Change Candidate / evidence packet を作る | `attempt_ref`、role、objective ref、ownership ref、target workspace / revision、handoff を固定する |
| verifier | worker の結論を引き継がず、candidate と acceptance criteria を独立に検査する | verifier reserve と `verification_status=NOT_VERIFIED` を固定する |
| canonical writer | fact family ごとに一つだけ Current Truth へ書く | public candidate では `ROOT_ONLY`。worker に shared SSOT write を与えない |
| human gate | material effect、Promotion、Public GO を承認する | `human_gate=false`、`public_beta=NO_GO_UNPUBLISHED` を維持する |

## Contract fields

新しい schema は、既存 route-binding schema と protected execution schema を変更せず、
次のフィールドを別の candidate として閉じます。

- root: `swarm_id_ref`, `root_task_ref`, `root_operation_ref`, `orchestrator`
- budget: `attempt_budget_N`, `concurrency_cap_C`, `wave_width_W`, `max_workflow_depth=2`, `verifier_reserve_V`
- assignment: `attempt_ref`, `parent_attempt_ref`, `parent_edge_ref`, `role_ref`, `kind`, `objective_ref`, `ownership_ref`, `depth`, `wave`, `dependencies`, `planned_child_attempt_refs`
- target: `source_task_ref`, `target_task_ref`, `workspace_ref`, `workspace_binding`, `public_revision`, `candidate_binding`
- handoff: input / expected-output bindings、source / target attempt、`HANDOFF_DEFINED_UNVERIFIED`
- lifecycle: `ttl_seconds`, `epoch`, `dedup_key_ref`, `retry_owner_ref`, cancel / stop conditions
- effects: `expected_effects=INTERNAL_CANDIDATE_RECORD_ONLY`、provider / device / public / external effects は false
- evidence: result / receipt refs は null、claims は false、`verification_status=NOT_VERIFIED`

親子 edge は nickname や role 名ではなく、opaque ref と parent edge ref で固定します。
workspace と revision は hash binding で表現し、public candidate から物理 cwd、host、
session、credential、raw prompt、private content を解決しません。

## Bounded swarm rules

1. 独立していない仕事を無理に並列化しない。共有 fact family、同じ file、同じ provider、
   同じ device、同じ authenticated session は root-owned として直列化する。
2. 一つの assignment は一つの objective、ownership、acceptance criteria、expected
   output、stop condition を持つ。曖昧な「全部調べて」は assignment にしない。
3. `N` は試行総数、`C` は同時実行上限、`W` は一 wave の幅として別々に記録する。
   verifier reserve `V` を通常 worker で使い切らない。
4. worker output は Change Candidate / evidence packet であり、root が inspect・reconcile・
   verify するまでは採用しない。worker conclusion をそのまま Current Truth にしない。
5. 二回連続で yield しない wave、TTL、cancel、retry owner、dedup key を ledger に残す。
   runtime metadata が確認できない child は成功扱いしない。
6. public preview では dispatch を行わない。private runtime に進む場合も route-binding、
   Work Order、Capability Grant、Human gate、re-observe、persistent idempotency を別々に
   満たす。

## Current implementation boundary

この repository で採用するのは、schema、read-only validator、negative tests、docs、
machine-readable planning ledger までです。Codex session の spawn、OpenAI / Anthropic
provider 呼び出し、subagent の実 runtime verification、worktree の作成、external send、
device / provider mutation、Promotion、Current Truth、Public Beta GO は含みません。

`PRECONDITIONS_MATCH_UNVERIFIED` は、opaque plan の構造と時間窓が整っているという意味
だけです。swarm runtime が利用可能になった後は、fresh child の thread / turn / model /
effort / parent-edge receipt を root が検証できた時だけ、private candidate を次の gate
へ進めます。

validator は `Draft202012Validator` を使うため、公開候補の preflight 環境に
`requirements-test.txt` の検証依存がない場合は `VALIDATOR_UNAVAILABLE` として
fail-closed になります。これは実行環境を自動導入したり、runtime swarm を代替したり
するものではありません。
