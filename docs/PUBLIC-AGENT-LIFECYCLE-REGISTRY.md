# Public Agent Lifecycle Registry

エージェントの仕様・実体・実行・lease・状態遷移・証跡を、provider に依存しない形で
追記専用に記録するための公開契約です。エージェントを起動するものでも、provider へ
接続するものでもありません。記録されるのは opaque な参照、digest、状態、budget、
gate 結果だけです。

- Schema: `schemas/public-agent-lifecycle-registry.schema.json`
- Verifier: `tools/validate_public_agent_lifecycle_registry.py`
- Tests: `tests/test_public_agent_lifecycle_registry_contract.py`
- Fixture: `tests/fixtures/public-agent-lifecycle/valid.jsonl`

## 6 つの record kind

| kind | 役割 |
|---|---|
| `agent_spec` | 再利用可能なエージェント定義。`policy_version`、capability 参照、`max_depth`、`max_fan_out` を持つ。leafは `max_fan_out: 0` で子delegationを禁止できる |
| `agent_instance` | spec を具体化した実体の**観測**。restart をまたいで同じ `instance_ref` が複数回現れうる |
| `agent_run` | 1 回の実行試行。親子 edge、depth、attempt、idempotency key、終端理由、証跡参照を持つ |
| `worker_lease` | run に対する所有権。`epoch`、heartbeat、期限を持つ |
| `run_event` | 状態遷移 1 件。run ごとに `subject_sequence` が 1 から連続する |
| `evidence_receipt` | 成果物 digest と private receipt への opaque 参照 |

## 成否は「導出」であって「保存」ではない

lifecycle state は次の 7 つだけです。

```
prepared -> dispatched -> running -> completed | failed | cancelled | expired
```

- payload を組み立てただけの段階は `prepared` で終わります。
- 委任が受理されただけの段階は `dispatched` で終わります。
- `degraded` は **state ではなく属性** です。品質や転送の劣化を表すだけで、
  それ自体は成功でも失敗でもありません。schema の `state` enum に `degraded` は
  含まれません。
- 成功は保存されません。verifier は
  `state == "completed"` かつ `termination_reason == "EVIDENCE_COMPLETE"` かつ
  証跡参照が 1 件以上あるときにのみ、`derived_success_count` に数えます。
- 空結果、例外、timeout、状態不明、証跡欠落は `EMPTY_RESULT` / `WORKER_ERROR` /
  `TIMEOUT` / `UNKNOWN_STATE` / `MISSING_EVIDENCE` として fail-closed に記録し、
  `completed` にはなれません。

verifier は次を拒否します。証跡のない `completed`、完了理由を名乗る失敗、
終端理由のない終端 run、終端理由や証跡を持つ非終端 run、event 履歴と食い違う
run state、履歴のない run、遷移表にない state 変化。

## 継続性は「検証済み」にならない

再起動をまたいで同じ `instance_ref` が 2 回以上観測されたとき、verifier は
記録された前提条件（`spec_ref`、`spec_digest`、`policy_version`、
`provider_locator_ref`、`context_capsule_digest`、`repository_ref`、`revision`）を
突き合わせて 1 件の assessment を返します。

| assessment | 意味 |
|---|---|
| `PRECONDITIONS_MATCH_UNVERIFIED` | 記録された前提条件がすべて一致した。**それだけ** |
| `WORK_RESUME_ONLY` | 1 つ以上が食い違った。計画やタスクの再構成であって、同一 instance の再利用ではない |

`CONTINUITY_VERIFIED` はこの契約から出力されません。公開レコードは、provider が
実際に同じ認可済み instance を再利用したことを証明できないからです。証明には
private 側の authority が要り、それはこの registry が持たないものです。
`claims.continuity_verified` と `claims.provider_instance_reused` は常に `false` です。

## Budget と idempotency

- 子 run の `depth` は親 `depth` + 1 でなければなりません。root run は `depth` 0 で、
  親も parent edge も持ちません。
- `depth` は spec の `max_depth` を、親ごとの子の数は `max_fan_out` を超えられません。
- retry は同じidempotency keyの直前attemptが `failed` / `cancelled` / `expired` のいずれかで終端した時だけ許可され、completedまたは非終端runと重複実行できません。
- `termination_reason` は終端stateに対応し、event/leaseのopaque参照はregistry内で一意です。timestampは実在するUTC date-timeとして検証されます。
- verifierはregular fileだけを最大8 MiB + 1 byteのbounded readで受け取り、oversized/non-regular inputを処理前に拒否します。
- `parent_run_ref` と `parent_edge_ref` は両方あるか両方ないかのどちらかです。
- 同じ `idempotency_key_ref` の `attempt` は 1 から連続し、重複できません。
- 同じ run の lease `epoch` は狭義単調増加で、heartbeat は期限を超えられません。

## 追記と改竄検知

`prev_hash` / `content_hash` の連鎖は
[Public Migration Ledger](PUBLIC-MIGRATION-LEDGER.md) と同じ規則です。先頭は 64 個の
`0`、`content_hash` は `content_hash` を除いた canonical JSON の SHA-256、追記時は
verifier の `canonical_content_hash()` を唯一の実装として使います。

## 実行

```
python tools/validate_public_agent_lifecycle_registry.py path/to/registry.jsonl
```

## この検証が意味しないこと

`REGISTRY_CONSISTENT_UNVERIFIED` は、記録された lifecycle が内部整合していることだけを
示します。エージェントが起動したこと、dispatch が実行されたこと、provider instance が
再利用されたこと、証跡が独立検証されたこと、Human Decision、Promotion、Current Truth、
Public Beta GO のいずれも意味しません。verifier の出力は claim をすべて `false` として
返し、`public_beta` は常に `NO_GO_UNPUBLISHED` です。

## 公開 source provenance と現在の境界

公開元は [PR #36](https://github.com/Kotodama-Project/Kotodama-project/pull/36)、
固定 source head `29cad12dc20c6be07a6c9740cfc8b4ab1794d873` です。文書・schema・validator・
契約 test・合成 fixture と matrix の lifecycle 節だけを抽出し、旧 branch の governance、
license、workflow は移植しません。依存する #35 の再導入は
`082ad3bcb2b6f4de590e17616518525f4b19a964` に固定しています。
実 registry は未作成です。fixture の 32 records は合成例で、実 agent の観測ではありません。

## Luna Task swarm との対応

main の [Luna Task swarm](LUNA-TASK-SWARM.md) (`runtime/task_swarm/state.py`) は
Task に束縛した SQLite の実行記録です。この公開 JSONL を読み書きする adapter はありません。

| 公開 lifecycle | Luna の近い項目 | 未対応の境界 |
|---|---|---|
| `agent_spec` / `agent_instance` | owner-bound plan と worker reference | agent definition、provider locator、restart observation を結ぶ registry は無い。worker reference は人や provider の identity 証明ではない |
| `agent_run`、attempt、idempotency、親子 edge | `runs` / `jobs` / `attempts` と attempt token | job attempt と registry run の変換、親子 edge の出力は無い |
| `worker_lease`、epoch、heartbeat、expiry | attempt の `epoch` / `lease_until` と heartbeat | public lease record の発行、hash chain は無い |
| `run_event` | claim、report、accept と attempt/job state | 7-state lifecycle の event stream は出力しない。Luna の状態語彙をそのまま転記しない |
| `evidence_receipt` と導出成功 | owner `accept` の result digest と verification reference | 受入は registry receipt、独立証跡検証、Promotion の証明ではない |
| continuity assessment | owner による persisted run の resume | 再開は provider instance の同一性・継続性・runtime の実モデル受入を証明しない |

この対応表は概念の比較だけです。adapter、実 registry、provider continuity rehearsal、
実 Codex/Luna の live 受入は未実施で、すべての false claims と `NO_GO_UNPUBLISHED` を維持します。
深く入れ子になった JSON も CLI は `INPUT_INVALID` の構造化 refusal として返します。

### 固定 source からの変更

再導入時の validator 差分は、深い object JSON (depth 5000) の `RecursionError` を
`INPUT_INVALID` で拒否すること、retry の最初の event を前 attempt の失敗終端 event より
後の append sequence に限定すること、拒否された registry の `derived_success_count` を
常に 0 にすることです。成功集計は schema・参照・receipt binding・event history を含む
semantic 検証が通った入力だけで行います。それぞれ CLI 回帰試験を追加しました。
その他の source fields、schema、合成 fixture、authority boundaries は維持しています。

JSON decoder の platform ごとの stack 上限に依存しないよう、各行の parse 前に
object/array の nesting を 64 段までに制限します。文字列内の括弧と escape は数えません。
65 段以上は `INPUT_INVALID` です。境界64/65、quoted bracket/escape、depth5000の
回帰試験で確認します。この明示的な入力上限も固定 source #36 からの追加差分です。
