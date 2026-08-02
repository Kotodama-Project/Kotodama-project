# Attestation Nonce Store Head Anchor and Restore Drill

R21は、R20のself-contained checkpoint-chain bundleを、独立pinされた署名済みhead anchorへ束縛し、さらにsource/restored storeのR20 verification reportとprivate backup/restore receiptを一つの署名済みreported drill candidateへ束縛するprotected-local contractです。

R21は二つのpublic CLI seamを持ちます。

1. `verify_attestation_nonce_store_checkpoint_head_anchor.py`
2. `verify_attestation_nonce_store_restore_drill_evidence.py`

成功しても、external anchorのcanonical authority、trusted clock、authoritative complete history、parallel branch不存在、実際のbackup/restore、protected runner、人物としてのrole分離、Promotion、Current Truth、Final Human GO、Public Beta GOは証明しません。

## Seam 1: signed checkpoint-head anchor

head anchorは次をexact bytesへ固定します。

- R20 bundle SHA-256
- current checkpoint SHA-256
- store ID SHA-256
- checkpoint count
- 64桁anchor ID
- 最大900秒のsigned evaluation window
- `independent_anchor_reviewer` role、allowed-signers digest、identity-file digest
- namespace `kotodama-nonce-store-checkpoint-head`

```powershell
ssh-keygen -Y sign -f <private-anchor-reviewer-key> `
  -n kotodama-nonce-store-checkpoint-head <private-head-anchor.json>

python tools\verify_attestation_nonce_store_checkpoint_head_anchor.py `
  <private-head-anchor.json> `
  <private-head-anchor.json.sig> `
  <expected-anchor-sha256-from-protected-work-order> `
  <private-r20-bundle.json> `
  <expected-bundle-sha256-from-protected-work-order> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <expected-ssh-keygen-sha256> `
  <evaluated-at-ISO-8601>
```

`SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH`は、anchor/bundleの独立pin、bundleのclosed structure、head/store/count binding、OpenSSH signature、signer policy、local-clock evaluation window、pinと一致する`ssh-keygen` exact copyの実行だけを示します。

## Seam 2: signed reported restore-drill evidence

restore-drill evidenceは次のprivate inputsをexact digestで束縛します。

- 成功したhead-anchor verification report
- source storeに対する成功R20 chain-verification report
- restored storeに対する別実行の成功R20 chain-verification report
- distinctなprivate backup receiptとrestore receipt
- source/restored reportで一致するbundle、head、store ID、checkpoint/reservation count
- runner identity hashとreviewer identity hashの構造上の不一致
- backup/restoreについて要求されたreported check全件
- namespace `kotodama-nonce-store-restore-drill`

```powershell
ssh-keygen -Y sign -f <private-restore-reviewer-key> `
  -n kotodama-nonce-store-restore-drill <private-restore-drill-evidence.json>

python tools\verify_attestation_nonce_store_restore_drill_evidence.py `
  <private-restore-drill-evidence.json> `
  <private-restore-drill-evidence.json.sig> `
  <expected-evidence-sha256-from-protected-work-order> `
  <private-head-anchor-verification-report.json> `
  <private-source-chain-verification-report.json> `
  <private-restored-chain-verification-report.json> `
  <private-backup-receipt> `
  <private-restore-receipt> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <expected-ssh-keygen-sha256> `
  <evaluated-at-ISO-8601>
```

`SIGNED_RESTORE_DRILL_REPORT_BINDING`は、署名者がexact reports/receiptsとreported checksを一つのcandidateとして署名したことを示します。opaque receipt本文の真実性、runner実在、backup artifact、restore command、元storeとrestored storeの物理的な系譜は再実行しません。従って`backup_execution_verified`、`restore_execution_verified`、`protected_runner_execution_verified`は常にfalseです。

## 共通境界

- populated anchor、signature、bundle、store、report、receipt、identity、allowed-signersはprivate operational dataです。公開repository、Issue、log、test corpusへ置きません。
- inputはstable regular fileとして読み、private path、identity、signature body、receipt bodyをstdoutへ出しません。
- anchor/evidence/report/receipt/policy inputは各1 MiB以下、R20 bundleは24 MiB以下、signatureは64 KiB以下、identityは4 KiB以下、`ssh-keygen`は16 MiB以下です。
- `ssh-keygen`はPATHから解決した後にexact bytesを独立pinと比較し、private temporary copyだけを最大30秒実行します。
- success reportはsafe SHA-256 bindingとcountだけを返します。invalid reportでは全success claimがfalseです。
- schemasはclosed Draft 2020-12 contractで、terminal authority claimを`const: false`にします。

CLI終了codeは成功`0`、structured refusal`1`、usage error`2`です。R21のpublic testsはsynthetic key/store/reportだけを一時directoryで生成し、生成物を再利用・共有しません。
