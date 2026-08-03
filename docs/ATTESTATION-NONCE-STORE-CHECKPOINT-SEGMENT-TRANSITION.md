# Attestation Nonce Store Checkpoint Segment Transition

R22は、提示された1つのR20 checkpoint-chain bundleのheadと、その直後に置く1つのsuccessor checkpointを、署名済みsegment transition candidateとして検証するprotected-local contractです。checkpoint signer policyを維持するsegment分割と、別のkey setへ移るsegment境界の両方を扱います。

このcontractが検査するのは、提示された境界だけです。global sequence番号や「全履歴」という表現は使いません。成功してもcanonical anchor authority、trusted clock、authoritative complete history、parallel branch不存在、旧鍵の失効、鍵侵害の不存在、segmentation policyの採用、実storeの稼働継続、backup/restore、protected runner、人物としてのrole分離、Promotion、Current Truth、Final Human GO、Public Beta GOは証明しません。

## 2つのmode

- `KEY_ROTATION_SEGMENT`: prior bundleのsigner policyとsuccessor checkpointのsigner policyが異なり、allowed-signers bytesのSHA-256も変わっていることを要求します。これは境界上の新旧policy bindingであり、旧鍵の失効や侵害不存在の証明ではありません。
- `SAME_POLICY_SEGMENT`: priorとsuccessorのsigner policyがexactに一致することを要求します。これは同じpolicyのまま提示されたsegmentを開始するためのmodeです。

transition candidateは、次をexact digestまたはclosed fieldで束縛します。

- prior R20 bundle、prior head checkpoint、prior chain hash、store ID、checkpoint count
- prior allowed-signers fileとidentity file
- successor checkpoint、successor chain hash、store ID、reservation count
- successor allowed-signers fileとidentity file
- 構造上distinctな`independent_transition_reviewer` policy
- 最大900秒のsigned evaluation window
- terminal authority claimがすべて`false`であること

## Private-boundary workflow

populated transition、bundle、checkpoint、SQLite store、allowed-signers、identity、private key、signatureをpublic repository、Issue、log、test corpusへ置かないでください。Work Orderから渡すexpected digestと評価時刻も、対象candidateへ束縛してください。

```powershell
ssh-keygen -Y sign -f <private-transition-reviewer-key> `
  -n kotodama-nonce-store-checkpoint-segment-transition `
  <private-segment-transition.json>

python tools\verify_attestation_nonce_store_checkpoint_segment_transition.py `
  <private-segment-transition.json> `
  <private-segment-transition.json.sig> `
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

成功statusは`SIGNED_KEY_ROTATION_SEGMENT_TRANSITION`または`SIGNED_SAME_POLICY_SEGMENT_TRANSITION`です。verifierは以下を同時に満たしたときだけ成功します。

1. transition、prior bundle、successor checkpointの独立digest pinが一致する。
2. prior bundleのclosed structure、全checkpoint digest、全signature digest、Genesisからheadまでのparent link、append-only reservation pathが妥当である。
3. prior bundle内の全checkpoint signatureがprior policyで検証できる。
4. successor checkpointがprior headをimmediate parentとして参照し、同じstore IDとreservation subsetを維持する。
5. 最初に開いたsupplied SQLite objectのstable copyと通常snapshotが一致し、successor checkpointのstore bindingとexactに一致する。
6. successor checkpoint signatureがsuccessor policyで検証できる。
7. transition signatureが構造上distinctなreviewer policyで検証できる。
8. modeごとのsigner policy条件、900秒以下のwindow、pinned `ssh-keygen` exact bytesが一致する。

## Fail-closed limits

- inputはstable regular fileとして読み、transitionは1 MiB、R20 bundleは24 MiB、checkpointは2 MiB、各signatureは64 KiB、allowed-signersは各1 MiB、identityは各4 KiB、`ssh-keygen`は16 MiBまでです。
- `ssh-keygen`はPATHから一度だけ解決・読取し、expected SHA-256と一致したexact temporary copyだけを使います。1署名30秒、全署名180秒が上限です。
- signature検証が終わるまでsource SQLite read transactionとopened-object snapshotを保持します。長いchainはmaintenance windowで検査してください。
- duplicate key、non-finite number、過深JSON、unknown field、digest drift、wrong parent、store drift、policy drift、期限外、signature tamper、authority overclaimはstructured `INVALID`として拒否します。
- invalid reportでは全success claimが`false`です。private input本文、path、identity、signature bodyはstdout/stderrへ反映しません。
- CLI終了codeは成功`0`、structured refusal`1`、usage error`2`です。

公開schemaは次の2つです。

- `schemas/attestation-nonce-store-checkpoint-segment-transition.schema.json`
- `schemas/attestation-nonce-store-checkpoint-segment-transition-verification.schema.json`

schemaとCLIはcandidate/report shapeを閉じますが、外部authorityや実行事実を生成しません。
