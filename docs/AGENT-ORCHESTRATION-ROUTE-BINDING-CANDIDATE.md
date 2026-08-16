# Agent Orchestration Route-Binding Candidate

これは、公開 Kotodama Preview における **agent orchestration の送信先取り違えを
防ぐための比較契約**です。実行器や Codex transport を公開するものではなく、
source と target を同じ候補の中で対照できるように、opaque reference、workspace /
revision binding、route policy、preview、confirmation、rollback、停止条件を固定します。

## Public boundary

この契約と preflight は、次の範囲だけを扱います。

- 公開してよい `ref/...` と SHA-1 / SHA-256 / byte size の形を検査する
- `source_task` と `target_task` の task / thread / host / title / workspace を、実値ではなく opaque reference と binding で対照する
- `route_id_ref` と `operation_id_ref` を分け、同じ候補内で route と operation を取り違えない形を記録する
- `recorded_at <= preview.observed_at < preview.expires_at <= expires_at` の順序を read-only で検査する
- preview は記録済みでも未検証、confirmation は常に未確認、外部作用は常に禁止として閉じる

この repository からは、Codex session の読み出し、subagent の spawn、cwd / host の
解決、private evidence の取得、task message の送信、provider / device / public route
の呼び出し、replay ledger の永続化、Human Decision、Promotion、Current Truth の変更を
行いません。したがって preflight の成功は `PRECONDITIONS_MATCH_UNVERIFIED` であり、
`CANDIDATE_ONLY` と `NO_GO_UNPUBLISHED` を維持します。

## Comparison contract

対照は、次の順序で一つの candidate に閉じます。

| 対照対象 | 固定するもの | 不一致時の停止理由 |
|---|---|---|
| source → target | `task_ref`, `thread_ref`, `host_ref`, `title_ref`, `workspace_ref`, `workspace_binding` | `source_target_mismatch` |
| workspace / revision | `repository_ref`, public commit SHA-1、candidate manifest SHA-256 / bytes、`resource_scope_ref` | `workspace_or_revision_drift` |
| route / effect | `route_id_ref`, `operation_id_ref`, allowed action、`expected_effects=INTERNAL_CANDIDATE_RECORD_ONLY`、correlation ref、policy binding | `route_policy_drift` |
| preview | preview SHA-256 / bytes、観測時刻、expiry、`confirmation_required=true` | `preview_stale_or_expired` |
| confirmation | `confirmation_ref=null`, `human_gate=false`, `NOT_CONFIRMED` | `confirmation_missing_or_mismatch` |
| effect boundary | internal candidate only、external / provider / device / public effects は false | `external_effect_detected` |
| replay boundary | operation identity を候補へ記録し、public 側では実行や reservation を主張しない | `operation_replay_conflict` |

source と target の task / thread reference が一致する候補は、self-route として
`SOURCE_TARGET_IDENTITY_COLLISION` で拒否します。これは、表示名や nickname ではなく、
比較対象を明示してから次段へ進むための fail-closed 条件です。

ただし、public candidate は opaque reference の関係を記録するだけです。
`workspace_binding`、host / title reference、`source_target_correlation_ref` の実値を
解決して相互一致させることはなく、複数 candidate 間の operation reservation や replay
防止も行いません。したがって `replay_prevented=false` と
`PRECONDITIONS_MATCH_UNVERIFIED` は意図的な境界であり、実効的な誤送信防止と実送信の
証明は private runner の別 Work Order / ledger / re-observe gate に残ります。

## Candidate flow

```text
Source Evidence
  -> route-binding candidate (source / target / resource / route)
  -> preview recorded (unverified, bounded expiry)
  -> confirmation candidate (always NOT_CONFIRMED in public)
  -> private re-observe / verify (not provided here)
  -> internal dispatch only after a separate private Work Order
```

`confirmation` が未確認のままなのは意図的です。route policy の allowed action も
`INTERNAL_AGENT_HANDOFF` だけに閉じ、外部作用や public launch をこの
候補から暗黙に許可しないため、private runner 側で別の Work Order、rollback、stop
condition、Human gate を束ねない限り dispatch へ進めません。既存の Protected
Execution Request / Handoff Candidate は変更せず、この route-binding candidate と
補完関係にあります。

schema の `route_state=REFUSED_UNVERIFIED` は拒否候補を記録するための構造上の状態です。
CLI はこの状態を `CANDIDATE_MARKED_REFUSED` として常に拒否し、成功時の
`PRECONDITIONS_MATCH_UNVERIFIED` にはしません。CLI の Draft 2020-12 検証には
`requirements-test.txt` の `jsonschema` が必要で、未導入時も `VALIDATOR_UNAVAILABLE`
で fail-closed します。これは starter smoke の standard-library-only 境界を広げず、
この追加 preflightだけに固定依存を閉じるためです。

## Read-only preflight

PowerShell:

```powershell
python tools\validate_company_pack_agent_orchestration_route_binding_candidate.py `
  path\to\route-binding-candidate.json
```

POSIX:

```bash
python3 tools/validate_company_pack_agent_orchestration_route_binding_candidate.py \
  path/to/route-binding-candidate.json
```

成功時は `CANDIDATE_ONLY` / `PRECONDITIONS_MATCH_UNVERIFIED`、拒否時は
`REFUSED` と安定した reason code を返します。どちらも claims は全て false、
`public_beta` は `NO_GO_UNPUBLISHED` です。validator は入力を上書きせず、候補を
実行したり receipt を生成したりしません。

## Review triggers and safe handoff

source / target identity、workspace / revision、route policy、manifest / preview、
clock / expiry、rollback / stop condition、confirmation / authority、schema のいずれか
が変わったら、既存候補を再利用せず新しい candidate として再レビューします。
public 側で確認できるのは schema / preflight / negative test の local evidence までで、
runtime、provider、device、public、Promotion、Current Truth、Final Human GO は別の
candidate-bound gate です。
