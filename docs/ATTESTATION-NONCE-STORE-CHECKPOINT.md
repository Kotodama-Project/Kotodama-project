# Attestation Nonce Store Checkpoint

R19は、R18のprivate SQLite nonce storeを、署名可能なpoint-in-time checkpointへ変換するprotected local seamです。checkpointはstore identity、exact schema contract、予約rowごとのdigestをsorted listとして束縛し、直前checkpointへの1リンクを検査します。

この機能はstore全履歴の継続性、外部anchorの権威、restore実行、trusted clockを証明しません。checkpoint本体にはnonceのraw値は入りませんが、予約digestの集合はprivate operational metadataです。**生成済みcheckpoint、署名、allowed-signers file、identity file、nonce storeを公開repositoryへ置かないでください。**

## 増える保証

`SIGNED_GENESIS_CHECKPOINT_STORE_MATCH`は次を示します。

- supplied current checkpoint SHA-256がexact checkpoint bytesと一致した
- exact checkpoint bytesのOpenSSH署名を固定namespaceで検証した
- checkpointがallowed-signers fileとsigner identity fileをSHA-256で束縛していた
- checkpointのself-chain digest、store ID、schema contract、reservation digest集合が有効だった
- 成功reportを出すまで同じDELETE-journal SQLite read transactionを保持し、観測中のwriter commitを遮断した
- supplied storeのlogical snapshotがcheckpointと完全一致した
- checkpointが明示的なGenesisだった

`SIGNED_SUCCESSOR_CHECKPOINT_STORE_MATCH`は上記に加えて、次を示します。

- supplied immediate-parent digestとparent signatureを検証した
- childがparentのexact file digestとchain digestを束縛していた
- parentとchildのstore IDが同じだった
- parentの全reservation digestがchildに含まれていた

このsubset検査とcurrent-store exact matchにより、直前checkpointより古いstoreへの巻き戻しや、件数だけ同じ別row集合への差替えを1リンクの範囲で拒否できます。

## 1. Work Orderでprivate inputsを束縛する

material checkpointの前にprotected Work Orderへ少なくとも次を固定します。

- exact nonce-store locatorとstore ID
- current checkpoint output locator
- Genesisまたはexact immediate-parent checkpoint / signature digest
- allowed-signers file digest、signer identity、OpenSSH namespace
- expected effect、rollback、expiry、stop conditions
- current checkpoint digestを独立にpinする先と担当者

CLIへexpected digestを渡すこと自体は、そのdigestをcanonicalに採用した権威を証明しません。外部pinの所在・ACL・署名・Human Decisionは別のevidenceです。

## 2. Genesis checkpointを作る

出力先は新規fileでなければなりません。

```powershell
python tools\create_attestation_nonce_store_checkpoint.py `
  <private-nonce-store.sqlite3> `
  GENESIS `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  --output <private-genesis-checkpoint.json>
```

作成reportは`CHECKPOINT_CREATED`または`INVALID`です。成功後、checkpointのexact bytesを独立reviewerが固定namespaceで署名します。

```powershell
ssh-keygen -Y sign `
  -f <private-reviewer-key> `
  -n kotodama-nonce-store-checkpoint `
  <private-genesis-checkpoint.json>
```

## 3. Genesisを検証する

`expected-current-sha256`は、検証対象fileからその場で自己計算した値ではなく、Work Orderまたは独立したprotected pinから取得します。

```powershell
python tools\verify_attestation_nonce_store_checkpoint.py `
  <private-genesis-checkpoint.json> `
  <private-genesis-checkpoint.json.sig> `
  <private-nonce-store.sqlite3> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <expected-current-sha256> `
  GENESIS GENESIS GENESIS
```

## 4. Successor checkpointを作成・検証する

新しいnonce予約がcommitされた後、直前checkpointをparentに指定します。

```powershell
python tools\create_attestation_nonce_store_checkpoint.py `
  <private-nonce-store.sqlite3> `
  <private-parent-checkpoint.json> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  --output <private-successor-checkpoint.json>

ssh-keygen -Y sign `
  -f <private-reviewer-key> `
  -n kotodama-nonce-store-checkpoint `
  <private-successor-checkpoint.json>

python tools\verify_attestation_nonce_store_checkpoint.py `
  <private-successor-checkpoint.json> `
  <private-successor-checkpoint.json.sig> `
  <private-nonce-store.sqlite3> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <expected-current-sha256> `
  <private-parent-checkpoint.json> `
  <private-parent-checkpoint.json.sig> `
  <expected-parent-sha256>
```

R19はparentとcurrentに同じallowed-signers file / identity bindingを要求します。key rotationは未対応です。このCLI単体はchain全体を再帰検証せず、supplied immediate parentだけを検証します。提示されたGenesis-to-current path全体を検証する場合は[Attestation Nonce Store Checkpoint Chain](ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)を使います。

## Exit codesとschema

- generator `0 / CHECKPOINT_CREATED`: private candidateを新規fileへ作成
- verifier `0 / SIGNED_GENESIS_CHECKPOINT_STORE_MATCH`: Genesis、署名、store exact match
- verifier `0 / SIGNED_SUCCESSOR_CHECKPOINT_STORE_MATCH`: current、immediate parent、署名、1-link subset、store exact match
- `1 / INVALID`: 入力、schema、store、digest、signature、parent linkのいずれかを拒否
- `2`: usage error

machine-readable contractは次の3件です。

- [`attestation-nonce-store-checkpoint.schema.json`](../schemas/attestation-nonce-store-checkpoint.schema.json)
- [`attestation-nonce-store-checkpoint-creation.schema.json`](../schemas/attestation-nonce-store-checkpoint-creation.schema.json)
- [`attestation-nonce-store-checkpoint-verification.schema.json`](../schemas/attestation-nonce-store-checkpoint-verification.schema.json)

checkpointは最大10,000 reservation、supplied nonce storeは最大64 MiBで、store queryには30秒のdeadlineがあります。上限到達後の安全なsegmentation / rotationは未実装です。stdoutはprivate path、identity、reservation list、public key、signature bodyを出さず、safe digest bindingだけを返します。

## まだ証明しないこと

- external pinを管理するsystemやpersonの権威・不可変性
- trusted clock、freshness、timestamp attestation
- 同じparentから複数successorを作るbranchの不存在
- checkpoint履歴の削除、再作成、repinの防止
- このCLI単体でのchain全体の再帰検証、key rotation、最大件数後のsegmentation
- store fileの物理byte同一性、backup作成、restore実行
- reported Compose executionの真実性、current daemon/image/runtime
- Promotion、Current Truth、Final Human GO、Public Beta GO

従ってR19の成功は、supplied external digestと署名に束縛されたprivate storeのpoint-in-time / immediate-parent検証です。store continuity、restore、production runtime、Public Beta公開判定ではありません。

R20のrecursive verifierを併用しても、検証できるのは提示された1 pathです。external anchor、authoritative complete history、parallel branch不存在、actual restore executionは別evidenceのままです。
