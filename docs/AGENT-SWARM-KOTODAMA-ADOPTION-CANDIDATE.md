# Agent Swarm × Kotodama Adoption Candidate

これは、Kotodama の governance chain と agent swarm の実行単位を対応づける
public-preview-only の設計候補です。ここでいう swarm は「エージェントを大量に
起動すること」ではなく、root orchestrator が独立した bounded worker に仕事を分け、
各 worker の対象・親子 edge・workspace / revision・handoff・lease / TTL・stop
condition・結果を比較可能にしたうえで、root が統合・検証する構造を指します。

## 設計の根拠

Kotodama の swarm は、次の要求から形を決めています。

- **流れはコードで固定する。** 依存しない仕事はコードで並列に配り、最終的な統合と共通の guardrail は root が持つ。handoff で制御を渡す場合も、どの worker が何を返すかを assignment に固定する。
- **作用の境界ごとに確かめる。** agent 全体の入口と出口だけでなく、tool や handoff を一つ呼ぶたびに対象と権限を確かめる。tracing、session、sandbox、human-in-the-loop といった実行基盤の機能を有効にしても、それだけでは Work Order や Human GO にならない。
- **並列化は独立した仕事だけにする。** 独立した文脈で並列に調べる仕事には効くが、token の消費が大きく、依存の密な仕事や全員が同じ文脈を要る仕事には向かない。曖昧な指示は重複・欠落・終わらない探索を生むので、worker ごとに objective、出力形式、tool、境界を明示し、複雑さに応じて worker 数を抑える。

参照: [OpenAI Agents SDK の orchestration](https://openai.github.io/openai-agents-js/guides/multi-agent/)、[guardrails](https://openai.github.io/openai-agents-python/guardrails/)、[Anthropic の multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)。

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

## Luna Task swarm との対応

main の [Luna Task swarm](LUNA-TASK-SWARM.md)（`runtime/task_swarm`）は、この契約の考え方を local runtime として実装したものです。この契約は計画の形を検証するだけで、Luna の実行や受入を代わりに証明しません。

| 契約の項目 | Luna Task swarm | まだ対応していないこと |
|---|---|---|
| budget: `attempt_budget_N`、`concurrency_cap_C`、`wave_width_W`、`verifier_reserve_V`、`max_workflow_depth` | packet の `budget`（`N`、`C`、`W`、`V`、`depth`、`max_depth`）と scheduler の予算（試行・同時実行・検証枠） | 契約は `max_workflow_depth=2`、Luna の既定例は `max_depth=1` |
| assignment: `attempt_ref`、`parent_edge_ref`、`objective_ref`、`ownership_ref`、`dependencies` | job の `job_id`、`kind`（work / review）、`dependencies`、`exclusive_keys`、packet の `objective` と `ownership` | 契約の opaque ref と Luna の job ID を対応づける変換はない |
| target: `workspace_ref`、`workspace_binding`、`public_revision` | Task の `task_id`、`revision`、`context_digest`、`active_home` | revision の hash binding を Luna 側で読む検証はない |
| handoff: 入力と期待する出力の binding | peer 通信（`peer_send` / `peer_ack` / `peer_reply` と `peer_status`） | handoff を契約の record として保存する経路はない |
| lifecycle: `ttl_seconds`、`epoch`、`dedup_key_ref`、`retry_owner_ref`、cancel / stop | lease と epoch、idempotency key、owner binding の期限、即時 stop の条件 | — |
| evidence: `verification_status=NOT_VERIFIED`、claims は false | 独立した verifier と owner の `accept`。offline fixture はモデルを呼ばない | 実 Codex / Luna での live 受入は未実施 |

## Current implementation boundary

この契約で採用するのは、schema、read-only validator、negative tests、docs、
machine-readable planning ledger までです。実行は上の Luna Task swarm が担い、この契約はそれを起動しません。Codex session の spawn、OpenAI / Anthropic
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
