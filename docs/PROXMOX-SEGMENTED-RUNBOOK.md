# Proxmox Segmented Runbook

このrunbookは、既存または新規のProxmox環境からKotodama向けの分離構成を作る場合の**sanitized導入ライフサイクル候補**です。公開repositoryへguest ID、node名、hostname、IP、storage ID、credential、private source bodyを書きません。

機械可読契約は[`proxmox-segmented.json`](../examples/installation-lifecycle/proxmox-segmented.json)です。

## 理想と現在の公開candidate

### 理想の導入ライフサイクル

理想的には、Company Templateと必要なBlock、Governed Record、MOCを選び、
`preflight -> stage_candidate -> apply -> verify -> rollback -> restore_rehearsal`
の6フェーズを同じcandidateへ束縛します。role、network、identity、backup、
retentionの境界を含むmaterial effectは、exact Work Orderとfresh receiptで検証します。

### 現在の公開candidate

このrunbookに含まれるのは、local / syntheticなProxmox role/evidence契約、validator、
sanitized inventory導線だけです。target-bound receipt、guest変更、install、deploy、
restart、restore、provider connection、Voice / Discord E2E、Promotion、Current Truth、
Final Human GOは含まれず、公開状態は`NO_GO_UNPUBLISHED`です。

## Reference role model

環境固有のguestではなく、次のroleで設計します。

| Role | 主な責任 | 既定の境界 |
|---|---|---|
| ingress / voice | Discord等の入力、同意済みcapture、ASR handoff | DBや管理面へ直接writeしない |
| workflow | bounded orchestration、n8n等 | 必要なserviceだけへ接続 |
| company-db | Current Truth候補の業務data | Evidence Storeやpublic面と分離 |
| evidence-store | source/receipt/digest/retention evidence | Projectionから直接変更しない |
| optional outbound gateway | 明示された外部provider通信 | 初期状態は無効、別Work Order |

実環境では各roleをprivate locatorへ対応付けます。公開例に対応値を埋めません。

## 0. 公開契約を検証する

```powershell
python tools\validate_installation_lifecycle.py examples\installation-lifecycle\proxmox-segmented.json
```

```bash
python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json
```

ここでの`PASS`はrole/evidence契約だけです。

## 1. Preflight（read-only inventory）

private evidenceに次を保存します。

- Proxmox node、cluster、versionのlocatorと観測時刻
- roleからguest/serviceへの対応表
- guest type、OS、revision、config digest、稼働状態
- bridge/VLAN/firewallのsegmentation matrix
- storage、capacity、backup policy、最新backup digest
- service identityと最小権限matrix
- 現行health、既知の依存、停止条件

公開summaryはrole名、件数、digest、結果だけにsanitizationします。

次の場合は停止します。

- guest/serviceの正体またはownerを一意に特定できない
- network pathやfirewall current stateを取得できない
- fresh backupまたはlast-known-good revisionがない
- rollback/restore先を隔離できない
- Voiceのcapture/transfer/retention consentが不明

## 2. Stage candidate（local / synthetic）

- guest role、resource budget、network zone、allowed dependencyを宣言する
- config/revision/firewall ruleをdigestへ固定する
- host固有値をlocatorへ置換したpublic candidateを別に作る
- service identityがroleごとに分離されていることを検査する
- allow pathとdeny pathを含むtest matrixを作る
- backup/restoreとrollbackのtargetを事前に固定する

既存環境をtemplate sourceにする場合も、current guestをそのまま公開templateへcopyしません。inventory、sanitization、synthetic validationを挟みます。

## 3. Apply（exact Work Order必須）

Work Orderは、対象role/locator、candidate revision/digest、変更するguest/config/firewallの範囲、期待作用、backup pin、rollback、window、stop conditionsを明示します。

次は自動的に含まれません。

- node/cluster全体の設定変更
- credentialやpermission変更
- public ingressの開放
- providerへのデータ転送
- 既存guestの削除・置換

これらが必要なら、同じ候補へ具体的に束縛した別actionとして扱います。

## 4. Verify（service + boundary）

同じcandidateについて、次を確認します。

- roleごとのservice healthとrevision digest
- restart後のrevision/health一致
- 必要なrole間通信のpositive test
- 不要なcross-segment通信、管理面、public ingressのdeny test
- Company DBとEvidence Storeの分離write/read smoke
- n8n等workflowから許可対象だけに到達できること
- monitoringがservice down、capacity、backup failureを検出すること
- log、receipt、public summaryにprivate identifierやsecret値がないこと

Voiceを含む場合は、同意、capture、speaker attribution、15分rotation/post、保持、削除receiptを別のscope-matched E2Eとして扱います。role healthだけでVoice E2EをPASSにしません。

## 5. Rollback（exact Work Order必須）

- pinned last-known-good config/revisionへ戻す
- firewall/network policyを対応するrevisionへ戻す
- data schema互換性を確認する
- service healthとdeny matrixを再実行する
- rollback前後のdigestと結果をreceiptへ残す

guest削除、storage破棄、credential resetは一般rollbackに含めません。

## 6. Isolated restore rehearsal（別Work Order必須）

- backup digestを照合する
- productionとは異なるguest/segment/storage targetへ復元する
- 復元targetからproduction writeができないことをnegative testする
- service revision、schema、domain invariant、read smokeを確認する
- RTO/RPO観測値と失敗点をreceiptへ残す
- 演習targetの保持期限と安全な後処理をWork Orderへ含める

backup jobが成功した表示だけではrestore証明になりません。

## 完了条件

Proxmox profileを「導入・再起動・復元まで検証済み」と呼ぶには、同じcandidateに束縛したguest/service inventory、revision/config digest、segmentation、identity、health、deny test、restart、backup、isolated restore、rollbackのfresh receiptが必要です。公開runbookの存在やlocal validator PASSは、その代替になりません。
