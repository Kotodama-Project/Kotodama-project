# OpenManus × Proxmox Executor Candidate

OpenManusをKotodamaの**交換可能な実行worker**として評価するためのcandidate設計です。

この文書は正式採用・本番配備・安全性の証明ではありません。現在の状態は`candidate_only`です。
機械可読な候補は[`openmanus-proxmox.json`](../examples/executor-runtime/openmanus-proxmox.json)を参照してください。

## Decision under evaluation

KotodamaがHuman Intent、Decision、Work Order、Capability Grant、Verification、Promotionの正本を保持したまま、OpenManusへ限定された実作業を委譲できるかを評価します。

```text
Human / Discord / Voice / Issue
             |
             v
          Kotodama
  Intent / Work Order / Grant
             |
             v
     executor adapter boundary
             |
             v
 Proxmox KVM: OpenManus worker
 browser / MCP / bounded tools
             |
             v
 artifacts + evidence + trace digest
             |
             v
 independent verification
             |
             v
 Kotodama Promotion Gate
```

OpenManusの会話履歴、終了メッセージ、内部memoryをCurrent Truthの正本にしません。
`completed`は「workerが処理を終えた」という観測であり、Promotionではありません。

## Upstream pin

初期評価candidateは次へ固定します。

- Repository: [`FoundationAgents/OpenManus`](https://github.com/FoundationAgents/OpenManus)
- Revision: [`3309bf4e416fb1c74b008f3e86494439a31bad53`](https://github.com/FoundationAgents/OpenManus/commit/3309bf4e416fb1c74b008f3e86494439a31bad53)
- License: MIT
- Python: upstream READMEは3.12環境を案内
- Single-prompt MCP runner: `python run_mcp.py --prompt ...`
- Browser: upstream READMEではBrowser Use CLI 3.0 MCPをdefaultとして起動

upstreamのDockerfileは依存を導入した後`CMD ["bash"]`で終了するため、Kotodamaの常駐worker supervisorやhealth contractが完成済みだとは扱いません。またBrowser Useはupstream READMEで`uvx browser-use --cli-mcp`として起動されるため、protected deploymentではOpenManus commitだけでなく解決済みBrowser Use package/versionも別途pinしてreceiptへ束縛します。

## Responsibility split

| Component | Responsibility | Must not own |
|---|---|---|
| Kotodama | intent、Work Order、Capability Grant、canonical state、promotion | worker内部状態への依存 |
| Executor adapter | scope rendering、request/response binding、stop、trace/evidence handoff | grant拡張、自己承認 |
| OpenManus worker | 許可されたtoolでWork Orderを実行しartifact候補を返す | Current Truth promotion、Proxmox管理権限 |
| Proxmox | KVM isolation、resource boundary、restart/backup/restore | business authorization |
| Independent verifier | artifact/source/scope/negative test確認 | executionと同一identityでの自己承認 |

## Why a dedicated KVM guest first

OpenManusはbrowser automation、MCP tool、Python/process実行を含むため、初期評価では既存serviceと同居させず専用KVM guestを使います。

初期resource hypothesisは次です。これはbenchmark済みminimumではありません。

- 4 vCPU
- 8 GiB RAM
- 60 GiB disk
- max concurrency: 1
- dedicated service identity
- task-scoped workspace only
- management-plane route: deny
- outbound: gateway allowlist only

resourceは実測peak、task latency、browser負荷、LLM/provider rate limitをreceipt化してから変更します。

## Proxmox boundary

既存[`PROXMOX-SEGMENTED-RUNBOOK.md`](PROXMOX-SEGMENTED-RUNBOOK.md)のrole / network / identity / restore境界を利用します。

### Phase 0 / 1: worker runs *on* Proxmox

worker guestには次を渡しません。

- PVE root credential
- unrestricted SSH key to the host
- PVE API token
- cluster-wide storage credential
- Company DB owner credential
- Evidence Store administrator credential

OpenManusがProxmox上で動くことと、OpenManusがProxmoxを操作できることを分離します。

### Future optional phase: brokered Proxmox operations

実務上の必要性とnegative testが成立した場合だけ、Proxmox操作はworkerへtokenを直接渡さず、別のbroker / adapterへ限定actionを要求する構成を評価します。

例:

- read-only health query
- exact guest start/stop
- isolated test guest snapshot request

cluster設定変更、guest削除、storage破棄、credential変更はdefault capabilityに含めません。

## Request contract

OpenManusへ渡す前に最低限、次を同じrequestへ束縛します。

1. Work Order IDまたはdigest
2. Capability Grant IDまたはdigest
3. candidate revision / config digest
4. budget / deadline
5. stop conditions
6. task-scoped input locatorまたはsanitized rendered prompt

scopeとgrantが一致しない場合は、推測で拡張せずstopします。

## Result contract

workerの結果は自然言語だけで完了扱いにしません。最低限、次を回収します。

- execution status
- artifact locator / digest
- source / evidence references
- tool trace digest
- unresolved items / failed checks
- verification candidate

Verification ReceiptとPromotion DecisionはKotodama側で別に生成します。

## Initial prohibited operations

- OpenManus guestからProxmox management planeへ直接接続
- Capability Grantの自己変更
- Current Truthへの直接write / promotion
- company-wide filesystemの無制限mount
- production deletionやdestructive infra mutationの暗黙実行
- credential storeの列挙・export
- 明示grant外のpayment、contract、legal commitment

## Network model

```text
[OpenManus KVM]
      |
      +-- task-scoped data -> explicitly allowed Kotodama service
      |
      +-- outbound -> controlled gateway -> allowlisted destinations
      |
      X-- Proxmox management plane
      X-- unrelated company segments
      X-- unrestricted shared storage
```

初期評価では「必要な通信を通す」だけでなく、不要な経路がdenyされることをtestします。

## Rollout gates

### G0 — repository candidate

- [x] upstream revision pin
- [x] machine-readable executor candidate
- [x] JSON Schema
- [x] static security invariants test
- [ ] protected VM created
- [ ] dependency lock captured

### G1 — isolated local evaluation

- [ ] dedicated KVM guest
- [ ] non-production test identity
- [ ] provider/model compatibility test
- [ ] Browser Use version pin
- [ ] task-scoped workspace
- [ ] default-deny management-plane test
- [ ] stop/cancel test
- [ ] restart test

### G2 — benchmark

同一20 taskを各3回実行し、既存方式と比較します。

計測するもの:

- task success / verification acceptance
- human active minutes
- correction minutes
- model/provider cost
- VM/runtime cost
- source/evidence completeness
- scope violation count
- duplicate/replay behavior
- cancellation latency

`human_time_reduction_hypothesis = 0.30`は採用済みKGIではなく、最初の評価仮説です。

### G3 — bounded production pilot

G1/G2を満たした場合だけ、低リスク業務へ限定します。

初期candidate:

- public research
- source-backed comparison
- draft artifact generation
- bounded browser collection
- disposable test-environment tasks

初期対象外:

- billing / payment
- contract / legal commitment
- production destructive action
- credential administration
- canonical DB promotion
- Proxmox cluster administration

### G4 — adoption decision

正式採用は、少なくとも次を満たす別Decision / Promotionで行います。

- authority breach: 0
- deny-path tests PASS
- restart / rollback / isolated restore receipts
- dependency/revision reproducibility
- independent verification path
- human-time / quality / total-cost advantage
- incident stop and revocation tested

## Failure semantics

次は`failed`または`blocked`として返し、workerが自己判断で権限を広げません。

- required toolがgrant外
- source/evidenceを取得できない
- budget/deadline超過
- browser/provider unavailable
- request binding mismatch
- target identity ambiguity
- management plane accessが必要になった
- destructive actionが必要になった

「できなかったので別経路で勝手に実行」は許可しません。

## Next implementation Work Orders

1. executor adapterのtransport contractを実装する
2. OpenManus/Browser Use/dependency lockを生成しdigest固定する
3. dedicated Proxmox KVM candidateをprivate inventoryへ対応付ける
4. ingress/egress deny matrixを実行する
5. 20×3 benchmark harnessを実装する
6. independent verifierへartifact/evidenceを接続する
7. restart/rollback/isolated restore rehearsalを行う
8. Adoption Decisionを作る

この順番では、OpenManusはKotodamaを置き換えません。Kotodamaの会社OS契約の後ろで交換可能な実行エンジンとして扱います。
