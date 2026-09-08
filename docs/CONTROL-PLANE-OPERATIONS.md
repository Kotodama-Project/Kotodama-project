# Control Plane Operations

[Knowledge Workの実検証](KNOWLEDGE-WORK-ENGINEERING.md): 出典・主張・受入・成果物を固定し、CIでbytesと参照を検査する。candidate限定で、意味評価・承認・Promotionとは分ける。

> Status: **candidate-only / read-only + proposal-only**

このページは、Kotodama の戦略・Knowledge・Agent portfolio を継続監査するための運用入口です。

公開 Company starter の schema / validator / runbook は [`SCHEMA-VALIDATOR-MATRIX.md`](SCHEMA-VALIDATOR-MATRIX.md) を使い、Company OS 全体の戦略・知識・Agent control plane はこのページから辿ります。

## Canonical registries

| Concern | Machine-readable owner | Human projection |
|---|---|---|
| Goal / KGI / Key Factors / Phase | [`../governance/okf.json`](../governance/okf.json) | [`../OKF.md`](../OKF.md) |
| Knowledge ownership / freshness / contradiction | [`../governance/knowledge-registry.json`](../governance/knowledge-registry.json) | [`KNOWLEDGE-BASE.md`](KNOWLEDGE-BASE.md) |
| Agent portfolio / eval / authority / rollback | [`../governance/agent-registry.json`](../governance/agent-registry.json) | [`AGENT-FOUNDRY-OPERATIONS.md`](AGENT-FOUNDRY-OPERATIONS.md) |
| Audit cadence / gates / autonomy | [`../governance/audit-policy.json`](../governance/audit-policy.json) | this page / `OKF.md` |

## Validation contracts

- [`okf.schema.json`](../schemas/okf.schema.json)
- [`knowledge-registry.schema.json`](../schemas/knowledge-registry.schema.json)
- [`agent-registry.schema.json`](../schemas/agent-registry.schema.json)
- [`audit-policy.schema.json`](../schemas/audit-policy.schema.json)
- [`test_control_plane.py`](../tests/test_control_plane.py)

Schema の PASS は runtime、Human approval、Capability Grant、Promotion、Current Truth、Final Human GO、Public Beta GO を作りません。

## 1. Read-only audit

Repository root から実行します。

```bash
python tools/audit_control_plane.py --format markdown
```

日付を固定して再現可能に確認する場合:

```bash
python tools/audit_control_plane.py \
  --as-of 2026-09-07 \
  --format json \
  --fail-on error
```

監査対象:

- OKF ID / cross-link / baseline semantics
- Knowledge fact family / canonical owner
- repository classification coverage
- freshness SLA
- Agent registry / KGI / KF / Knowledge links
- active Agent の implementation / eval / runtime evidence / rollback
- autonomy boundary

初期 P0 では warning は visibility のために残し、`error` 以上で CI fail とします。

## 2. Finding → Candidate Work

```bash
python tools/plan_control_plane_maintenance.py --format markdown
```

planner は audit finding を次の governed role へ振り分けます。

| Finding | Role |
|---|---|
| stale / inventory / canonical / freshness | Knowledge Curator |
| KGI / KF / Phase / baseline | OKF Steward |
| Agent registry / activation / capability | Agent Auditor |
| autonomy / Promotion / evidence boundary | Evidence Auditor |

出力は **candidate-only Work** です。

各 candidate は:

- source finding
- severity / priority
- assigned Agent role
- KGI links
- Key Factor links
- bounded next action
- verification criteria
- `proposal_only` authority

を持ちます。

planner 自体は Issue を作らず、ファイルを書き換えず、Agent を activate しません。

## 3. Candidate execution

P3 では candidate work を、Context Compiler が必要な canonical knowledge と provenance へ束縛し、適切な Human / Agent lane へ渡します。

```text
Audit Finding
  ↓
Candidate Maintenance Work
  ↓
Context Compiler
  ↓
OKF Steward / Knowledge Curator / Agent Auditor / Evidence Auditor
  ↓
Candidate Patch / Eval / Issue / Work Order
  ↓
Verification
  ↓
Review / Promotion gate
```

P0 ではこの後半はまだ runtime activation しません。

## 4. CI cadence

`.github/workflows/control-plane-audit.yml` は設計上、以下で deterministic audit を実行します。

- Pull Request
- `main` push
- daily schedule
- manual dispatch

実行内容:

```text
full regression suite
  -> control-plane schema / audit tests
  -> read-only audit report
  -> proposal-only maintenance plan
```

GitHub Actions 自体が実行可能であることは repository / organization の runner 設定にも依存します。workflow がコード実行前の `Set up job` で失敗した場合、それを validator/test failure と解釈しません。

## 5. Weekly Agentic review — P3

将来の weekly agentic lane は `governance/audit-policy.json` に先に契約だけ置いています。

### Knowledge Curator

- stale / duplicate / contradiction
- missing provenance
- projection drift
- context index candidate

### Agent Auditor

- eval regression
- capability overlap
- authority overscope
- cost-quality regression
- merge / retire candidate

### OKF Steward

- KGI gap
- phase exit gap
- priority mismatch
- evidence-less metric claim

### Evidence Auditor / Quality Red Team

- claim-evidence mismatch
- boundary violation
- regression/adversarial case

Agentic review の default authority は `proposal_only` です。

## 6. Promotion boundary

自動処理が生成してよいもの:

- audit report
- candidate issue
- candidate Work Order
- candidate patch
- candidate eval case

自動処理だけでは生成してはいけないもの:

- Human approval
- Capability Grant
- Promotion
- Current Truth change
- runtime deployment
- destructive canonical deletion
- Final Human GO
- Public Beta GO

この境界は `governance/audit-policy.json` と `tools/audit_control_plane.py` の両方で検査します。

## 7. P0 exit

P0 が complete と言えるのは、少なくとも以下が evidence で確認できたときです。

- 4 registry が schema-valid
- repository classification coverage ≥ 98%
- canonical owner 欠落を検出できる
- current state freshness を観測できる
- active Agent を registry / eval / grant / runtime evidence / rollback なしで通せない
- finding を KGI/KF 付き candidate work へ変換できる
- full regression suite が利用可能な runner 上で通る

それまでは `P0 in_progress` のままです。

## 8. Unified workforce in Cloudflare OS — adoption candidate

[Cloudflare OS + OpenMaus integration design](OPENMAUS-UNIFIED-AGENT-CONTROL-PLANE.md) defines one native management surface, shared Work identity, and isolated Proxmox execution. It reuses the existing OS addon rather than creating a separate portal or Task authority.

- [Workforce integration contract](../governance/openmaus-integration.json)
- [Cloudflare OS / platform composition](../governance/cloudflare-os-integration.json)
- [Read-only composition validator](../tools/validate_cloudflare_os_integration.py)
- [Offline contract tests](../tests/test_cloudflare_os_integration.py)

These are design candidates, not deployment configuration, live inventory, Cloudflare account changes, or runtime acceptance. Existing native OS dependencies and the C0–C3 implementation gates are documented in the design.

## 9. Git Steward and bounded work cells

[Git担当と必要単位のエージェントシステム](GIT-STEWARD-AND-WORK-CELLS.md) adds
one candidate Git role to the existing registry, not another Task authority.
The [executable coordination kernel](../runtime/git-steward/README.md) covers
scope reservations, dependencies, durable leases/fences, independent candidate
verification and read-only Git observation. Native OS/GitHub/executor adapters
remain separate acceptance work; no running agent or deployment is claimed.

```sh
python -m unittest discover -s tests -p 'test_git_steward_runtime.py' -v
```
