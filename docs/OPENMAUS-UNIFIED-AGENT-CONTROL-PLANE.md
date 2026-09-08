# OpenMaus Unified Agent Control Plane

> Status: **candidate-only architecture / no runtime deployment**  
> Machine-readable contract: [`../governance/openmaus-integration.json`](../governance/openmaus-integration.json)  
> Validator: [`../tools/validate_openmaus_integration.py`](../tools/validate_openmaus_integration.py)  
> Upstream fixed point reviewed for this proposal: [`milind-soni/OpenMausBot@600e315`](https://github.com/milind-soni/OpenMausBot/tree/600e315cb7c3f61c214488678f7e6a99a7be157d)

## 1. Decision candidate

Kotodama では OpenMausBot を単なる「別の Agent UI」ではなく、**人間が Agent workforce を一括管理する標準 control surface の第一候補**として評価する。

狙いは Agent を一か所へ物理的に押し込むことではない。

```text
one human management surface
  + one shared work identity
  + one canonical governance model
  + multiple isolated execution runtimes
```

を成立させることで、Agent、project、knowledge、work、approval、runtime が別々の管理面に分断されるのを避ける。

**管理を統合し、実行境界は分離する。**

## 2. なぜ OpenMausBot を土台にするか

上流の固定コミットで確認した範囲では、OpenMausBot はすでに次の useful primitives を持つ。

- Bot roster と chat/task conversation
- project/context を分けられる Channel
- Bot/Channel の activity 表示
- agent CLI driver
- model switching
- inline approval / question UI
- computer panel
- local / server operation
- MCP による外部 orchestrator からの bounded control
- bot ごとの Self-hosted VPS computer

特に MCP v1 は、Bot/Channel/Task の確認・作成・編集、work dispatch、completion wait、interrupt、model switch を外部から扱える。一方で approval grant、credential、delete、team import、computer/VM lifecycle は意図的に MCP の外に残している。

この差は Kotodama にとって都合がよい。**既存の team UX と runtime primitives を利用しながら、Kotodama の authority / evidence contract を上に重ねられる**ためである。

この文書は上流の capability を Kotodama へ配備済みだとは主張しない。上流固定点の source/docs を基に integration contract を定義している段階である。

## 3. サイロを作らないための基本原則

### 3.1 Group は authority boundary ではない

UI 上は Agent を次の5グループで見られるようにする。

1. **Intake / Orchestration**
2. **Knowledge / Research**
3. **Build / Execution**
4. **Verification / Audit**
5. **Operations / Improvement**

ただし、これは **view / filtering / routing のための分類**であり、独立した仕事台帳や Knowledge base を作らない。

同じ Agent が複数 group / project に参加できる。handoff では新しい孤立 chat を作って背景をコピーするのではなく、同じ Work identity を参照する。

### 3.2 Project view と workforce view を両立する

人間は少なくとも次の切り口で同じデータを見られることを目標にする。

- **All agents** — workforce 全体
- **By group** — 上記5分類
- **By project** — Project/Goal ごとの担当者と work
- **Needs attention** — approval / needs-user / failed / stalled
- **Runtime** — 実行場所、connection、capacity
- **Verification** — execution 済みだが未検証の結果

view を変えても Agent / Work / Artifact の identity は変えない。

### 3.3 「見える」と「操作できる」を分ける

external agent を統合表示できても、その adapter が interrupt を実装していなければ Stop ボタンを active にしない。

**unsupported operation を成功したように見せない。**

## 4. Canonical ownership

OpenMausBot の transcript / bot config を Kotodama の第二の正本にはしない。

| Concern | Canonical owner |
|---|---|
| Goal / KGI / Key Factors | `governance/okf.json` |
| Knowledge ownership / freshness | `governance/knowledge-registry.json` |
| Agent purpose / authority / activation | `governance/agent-registry.json` |
| Audit / autonomy boundary | `governance/audit-policy.json` |
| OpenMaus integration policy | `governance/openmaus-integration.json` |

OpenMausBot の Bot / Channel / Task はこれらの runtime/control-surface projection として bind する。

例:

```text
Kotodama Agent ID
  -> OpenMaus Bot ID / external runtime ID

Kotodama Work ID
  -> OpenMaus Task conversation / external run ID

Kotodama Artifact/Evidence ref
  <- runtime result / file / receipt
```

Bot を削除・再作成しても Kotodama Agent identity を別物として捏造しない。逆に runtime identity が変わった場合は observation として記録する。

## 5. Unified agent view

一つの Agent card / detail page で最低限、次を見られる設計にする。

- Kotodama Agent ID
- name / purpose
- groups / projects
- authority / activation state
- runtime kind / runtime location
- connection state / last observed time
- current Work / parent Work
- artifacts
- verification state
- cost/resource observation
- available actions

### Connection state

少なくとも:

- `unknown`
- `offline`
- `idle`
- `running`
- `needs_user`
- `failed`
- `stalled`
- `interrupted`

を区別する。

最後の observation が古いのに `running` のまま固定しない。timeout 後は `unknown` / `offline` 側へ倒し、過去の最後の状態と現在観測を分ける。

## 6. Shared Work contract

Agent 間 handoff の中心は chat transcript ではなく Work identity とする。

handoff で保持するもの:

- objective
- constraints
- Source refs
- Decision refs
- Artifact refs
- open questions
- verification requirements
- authority boundary

### Result state

次を一つに丸めない。

```text
queued
  -> running
  -> needs_user
  -> execution_settled
  -> verification_pending
  -> verified_candidate
```

failure / cancellation / stall は別 terminal/attention state とする。

OpenMausBot MCP の `settled` は **Agent turn が落ち着いた observation** として扱い、成果の correctness / Promotion を意味させない。

### Retry / duplicate protection

dispatch は idempotent にする。同じ Work を UI retry、MCP reconnect、scheduler retry が同時に再発火して duplicate side effect を作らない contract が必要である。

### Stop

`interrupt requested` と `interrupted observed` を分ける。Stop API を送れたことだけで stopped と表示しない。

## 7. OpenMausBot adapter

### 7.1 初期利用対象

上流 MCP v1 で確認できた範囲を初期 adapter とする。

- health / bot / channel / activity inspection
- bounded transcript read/search
- Bot/Channel/Task create/update
- work dispatch
- wait
- interrupt
- idle Bot の model switch

### 7.2 MCP v1 の外側

固定点では次は MCP v1 に exposed されていない。

- approve request
- remembered permission grant
- delete
- team import
- credential mutation
- computer / VM lifecycle

Kotodama adapter はこの gap を「実装済み」と偽装しない。

将来これらを統合管理画面から操作する場合も、OpenMausBot 内部 endpoint の雑な直呼びではなく、対象 authority と readback を持つ明示的 adapter contract を作る。

## 8. External agent federation

すべての Agent を OpenMausBot process として実行することを要求しない。

既存 / 将来の外部 Agent は最低限、以下の adapter contract で workforce に参加させる。

1. stable Agent identity
2. health observation
3. dispatch、または明示的 read-only
4. status observation
5. result/artifact binding
6. interrupt、または明示的 unsupported
7. authority binding

これにより、runtime を交換しても UI と Work history を分断しない。

## 9. Proxmox architecture

Proxmox は **統合管理の裏側にある isolation / runtime substrate** として扱う。

初期 topology candidate:

```text
Human
  |
  v
OpenMausBot-based Kotodama control surface
  |
  +---- Kotodama management services / canonical records
  |
  +---- OpenMausBot harness + approved agent CLIs
  |       |
  |       +---- MCP / runtime adapters
  |       |
  |       +---- Docker-over-SSH
  |                |
  |                v
  |          dedicated Linux worker VM on Proxmox
  |                |
  |                +---- per-bot managed computer containers
  |
  +---- independent verification / evidence lane
```

これは論理構成であり、現在の Proxmox へ配備済みという意味ではない。

### 9.1 BYO VPS を使う理由と制約

OpenMausBot の BYO VPS は、Docker の SSH transport で x86_64 Linux 上の Docker daemon を使い、bot ごとの managed computer container を動かす。

重要な境界:

- **Agent process 自体は BYO VPS 側へ移らない。** OpenMausBot host 側に残る。
- SSH user が Docker group に入る必要があり、その VM 内では root-equivalent である。
- したがって既存の重要サーバーを兼用せず、dedicated worker VM を使う。
- container filesystem は disposable とみなし、必要な成果は外へ回収する。

### 9.2 Proxmox management API

Agent に Proxmox の管理 token を直接渡さない。

将来 control surface から VM start/stop/restart/capacity 操作を行う場合は、別の bounded management adapter を通す。

最低条件:

- allowlisted VM/container scope
- allowlisted operation
- dedicated credential
- network boundary
- resource limit
- audit receipt
- mutation 後 readback
- emergency administrator recovery path

UI が一つであることと、credential が一つであることは同義ではない。

## 10. Three execution zones

### Management zone

- canonical governance records
- control-plane services
- no ordinary work-agent execution

### Worker zone

- OpenMausBot harness / agent CLI / browser / computer workers
- external execution adapters
- no canonical authority ownership

### Verification zone

- independent validation
- evidence preservation
- worker が結果を書き換えられない monitoring/evidence path

この separation は organization silo ではない。**同じ Work を安全に通すための execution trust boundary** である。

## 11. Approval UX

目標 UX は approval queue も unified surface に集めることだが、approval の意味を弱めない。

画面では:

- which Work
- requesting Agent
- requested action
- target
- scope / duration
- evidence / reason
- current grant state

を確認できるようにする。

承認操作を統合する場合、approval receipt と Capability Grant の canonical owner に bind し、単なる UI click を万能権限へ変換しない。

## 12. Knowledge を silo 化しない

Agent ごとの conversation memory は working memory として残せるが、共有すべき内容は Knowledge candidate として Source / provenance を持たせる。

```text
Agent working memory
  -> candidate knowledge / finding
  -> independent review where required
  -> canonical knowledge / decision
  -> bounded context retrieval by every authorized Agent
```

「全員が見える」は「全Agentへ全データをprompt注入する」ことではない。

権限と task relevance に応じて同じ canonical knowledge graph / registry から取得する。

## 13. Rollout

### P0 — Inventory and visibility

- Kotodama Agent ID と runtime ID の mapping
- all-agent view
- 5 group views
- project view
- connection / work / verification state
- unsupported capability の明示

**Exit:** 管理対象 Agent がすべて表示されるか、unsupported と明示的に分類される。OpenMaus transcript が canonical authority に昇格していない。

### P1 — Governed dispatch and handoff

- Work ID binding
- idempotent dispatch
- handoff
- wait / interrupt
- stale observation handling

**Exit:** group/project をまたいでも同じ Work identity を保ち、duplicate dispatch と false stop を防げる。

### P2 — Artifact / evidence / verification

- artifact binding
- result digest / receipt
- verifier independence
- execution vs verification separation

**Exit:** 「Agent が終わった」と「結果が検証された」を機械的に区別できる。

### P3 — Proxmox lifecycle

- bounded Proxmox adapter
- worker VM lifecycle
- resource observation
- readback
- restore / isolation drill

**Exit:** Agent が Proxmox admin credential を持たずに必要な lifecycle を管理でき、isolation と emergency recovery を evidence 付きで確認できる。

## 14. Upstream drift management

OpenMausBot は active upstream なので、`main` の moving behavior をそのまま前提にしない。

adoption review は fixed commit を記録し、update candidate ごとに最低限:

- README capability
- MCP tool boundary
- authentication/session behavior
- computer/VPS behavior
- deployment model
- license
- relevant security changes

を再確認する。

固定点を更新するだけで runtime adoption とはしない。

## 15. Validation

```bash
python tools/validate_openmaus_integration.py --format markdown
python -m unittest tests.test_openmaus_integration -v
```

validator は少なくとも:

- one management plane / no parallel authority
- exactly five cross-functional views
- shared Work identity
- known upstream MCP omissions
- Proxmox direct-agent-management refusal
- management / worker / verification zone separation
- execution / verification state separation
- false deployment / authority claims

を fail-closed で確認する。

## 16. Non-claims

この candidate は次を意味しない。

- OpenMausBot が Kotodama 本番へ deployed 済み
- 全 Agent が integrated 済み
- Proxmox adapter が deployed 済み
- isolation が実機検証済み
- Capability Grant が発行済み
- Promotion / Current Truth change
- Final Human GO
- Public Beta GO

正式採用判断は、P0 以降の実測 evidence と既存 governance gate を通して別途行う。
