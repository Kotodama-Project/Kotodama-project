# Checkpoint Segment Transition Candidate Builder

R23は、R22の署名済みsegment-transition verifierへ渡すprivate candidateを、入力fileのexact bytesから決定的に組み立てる標準ライブラリCLIです。手作業でdigestやbindingを転記せず、既存fileを上書きしないためのcreation seamです。

builder自身は署名しません。successor checkpoint signatureのbytesはcandidateへSHA-256で束縛しますが、その署名もtransition signatureも検証しません。署名と全R22 verificationは、candidate作成後に別の手順として実行します。

## Public CLI seam

populated bundle、checkpoint、signature、allowed-signers、identity、生成candidateはprotected private boundaryに置き、public repository、Issue、log、test corpusへ置かないでください。Work Orderで対象fileのexpected digest、mode、transition ID、signed windowを先に固定します。

```powershell
python tools\create_attestation_nonce_store_checkpoint_segment_transition.py `
  <private-prior-r20-bundle.json> `
  <expected-prior-bundle-sha256> `
  <private-successor-checkpoint.json> `
  <private-successor-checkpoint.json.sig> `
  <expected-successor-checkpoint-sha256> `
  <prior-allowed-signers> `
  <prior-identity-file> `
  <successor-allowed-signers> `
  <successor-identity-file> `
  <transition-reviewer-allowed-signers> `
  <transition-reviewer-identity-file> `
  <KEY_ROTATION_SEGMENT-or-SAME_POLICY_SEGMENT> `
  <transition-id-sha256> `
  <issued-at-ISO-8601> `
  <expires-at-ISO-8601> `
  --output <new-private-transition.json>
```

成功時はexit `0`、status `SEGMENT_TRANSITION_CANDIDATE_CREATED`をstdoutへ返し、`--output`へcanonical UTF-8 JSONを新規作成します。同じ入力、mode、ID、時刻ならcandidate bytesは同一です。既存file、symlink、存在しないparent directoryへの出力は拒否し、既存bytesを変更しません。

structured refusalはexit `1`、status `INVALID`です。usage errorはexit `2`でstderrだけへusageを返します。refusal reportはprivate path、identity、input本文、signature本文を反映せず、作成失敗という固定メッセージだけを返します。

## Builderが作成前に検査するもの

- prior bundleとsuccessor checkpointのexpected SHA-256 pin
- strict JSON、closed R20 bundle/checkpoint structure、最大input size
- prior bundle signer policyと指定prior policyのexact一致
- successor checkpoint signer policyと指定successor policyのexact一致
- successorがprior headのimmediate childであること
- 同一store IDとappend-only reservation subset
- `KEY_ROTATION_SEGMENT`ではpolicy bytesと復号OpenSSH key-blob digest集合の両方が変わること
- `SAME_POLICY_SEGMENT`ではsigner policyがexactに同一であること
- reviewer policy file/identity hashがprior/successor policy hashと衝突しないこと
- lowercase SHA-256 transition ID、timezone-aware ISO-8601、正で900秒以下のwindow
- R22 transition schemaと同じclosed fields、全terminal claim `false`

この検査はsignature validity、人物としてのrole分離、外部authority、trusted clock、実store continuityを証明しません。

## Sign and verify

builderの成功reportにある`transition_file_sha256`をWork Orderへ照合してから、独立transition reviewerがcandidateを署名します。

```powershell
ssh-keygen -Y sign -f <private-transition-reviewer-key> `
  -n kotodama-nonce-store-checkpoint-segment-transition `
  <new-private-transition.json>

python tools\verify_attestation_nonce_store_checkpoint_segment_transition.py `
  <new-private-transition.json> `
  <new-private-transition.json.sig> `
  <expected-transition-sha256> `
  <private-prior-r20-bundle.json> `
  <expected-prior-bundle-sha256> `
  <private-successor-checkpoint.json> `
  <private-successor-checkpoint.json.sig> `
  <expected-successor-checkpoint-sha256> `
  <supplied-current-store.sqlite3> `
  <prior-allowed-signers> `
  <prior-identity-file> `
  <successor-allowed-signers> `
  <successor-identity-file> `
  <transition-reviewer-allowed-signers> `
  <transition-reviewer-identity-file> `
  <expected-ssh-keygen-sha256> `
  <evaluated-at-ISO-8601>
```

成功authorityはR22 verifier reportだけにあります。builder reportの`source_bindings_structurally_validated=true`はcandidate作成時の構造・digest・boundary検査を表すだけです。`transition_signature_created`、`transition_signature_verified`、`successor_checkpoint_signature_verified`、`actual_key_rotation_executed`、`protected_runner_execution_verified`、Promotion、Current Truth、Final Human GO、Public Beta GOは常に`false`です。

## Failure and cleanup

失敗時はoutputを修正して再利用せず、原因となったprivate inputまたはWork Order bindingを確認し、新しいoutput pathで再生成してください。署名後にR22 verifierが拒否したcandidateとsignatureは検証receiptへdigestだけを残し、該当するprivate retention policyに従って削除します。public repositoryへinputやsignatureを追加してデバッグしないでください。

公開schemaは次です。

- `schemas/attestation-nonce-store-checkpoint-segment-transition.schema.json`
- `schemas/attestation-nonce-store-checkpoint-segment-transition-creation.schema.json`

このbuilderはprotected runner、実key rotation、old-key revocation、segmentation policy adoption、runtime、backup/restore、Discord/Voice、provider、Promotion、Current Truth、Final Human GO、Public Beta GOを実行しません。
