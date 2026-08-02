# Attestation Nonce Store Checkpoint Chain

R20は、R19で作成したprivate checkpointをGenesisからcurrentまで再帰検証し、supplied SQLite storeのlogical snapshotとcurrent checkpointが一致することを確認するprotected-local seamです。成功statusは`SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE`です。

この成功は、**提示された1本のchain pathと提示されたstore snapshot**にだけ束縛されます。外部anchorの権威、履歴の完全性、parallel branchの不存在、storeの継続運用、backup作成、実際のrestore実行、Promotion、Current Truth、Public Beta GOは証明しません。

生成済みmanifest、checkpoint、signature、allowed-signers file、identity file、SQLite storeはすべてprivate operational dataです。公開repository、Issue、log、test corpusへ置かないでください。このrepositoryにはtool、schema、synthetic testだけを含めます。

## 1. Private chain directoryを用意する

chain directoryには次のexact pairだけを連番で置きます。

```text
checkpoint-000000.json
checkpoint-000000.json.sig
checkpoint-000001.json
checkpoint-000001.json.sig
...
```

`checkpoint-000000.json`はGenesisでなければなりません。以後は直前checkpointのfile digestとchain digestへ束縛されたsuccessorで、同じstore IDと同じsignature policyを使用します。欠番、余分なfile、directory、symlink、未知entry、policy変更、store ID変更、reservation集合の縮小を拒否します。

R20はkey rotationを対応済みと見せないため、chain全体で同一のallowed-signers bytes、identity bytes、namespace、roleを要求します。rotationとsegmentationは将来の別contractです。

## 2. Deterministic manifestを作る

manifest outputはchain directoryの外にある新規fileを指定します。既存fileは上書きしません。

```powershell
python tools\create_attestation_nonce_store_checkpoint_chain_bundle.py `
  <private-chain-directory> `
  --output <private-chain-manifest.json>
```

builderは最大1,024 checkpoint、各checkpoint最大2 MiB、各signature最大64 KiB、chain aggregate最大16 MiBに制限します。manifestは連番locator、checkpoint/signature SHA-256、Genesis/current binding、ordered-chain digest、homogeneous signature policyを持ちます。作成時点ではsignatureを検証しないため、manifestの全authority claimはfalseです。

## 3. Protected Work Orderでpinする

material verificationの前に、少なくとも次をWork Orderへ固定します。

- private chain directoryとsupplied storeの対象
- manifest SHA-256の独立protected pin
- allowed-signers file SHA-256とsigner identity file SHA-256
- 実行を許可する`ssh-keygen` executable bytesのSHA-256
- expected effect、rollback、expiry、stop conditions
- verifier revisionとmachine-readable reportの保存先

`EXPECTED_MANIFEST_SHA256`は検証対象manifestから同じ手順内で自己計算した値ではなく、別personまたはprotected systemが保存した独立pinから渡します。CLIへdigestを渡すだけでは、そのpinの権威や不可変性は証明されません。

## 4. Chainとstoreを検証する

```powershell
python tools\verify_attestation_nonce_store_checkpoint_chain.py `
  <private-chain-manifest.json> `
  <expected-manifest-sha256> `
  <private-chain-directory> `
  <supplied-store.sqlite3> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <expected-ssh-keygen-sha256>
```

verifierは次をすべて満たした場合だけ`SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE`を返します。

- supplied manifestのexact SHA-256とclosed structureが一致する
- directoryの全checkpoint/signature digestがmanifestと一致する
- 全checkpointのOpenSSH signatureが同じexact policy bytesで有効である
- PATHで解決した`ssh-keygen`のexact bytesが独立pinと一致し、そのcopyだけを実行する
- 先頭がGenesisで、以後の全linkが直前file/chain digestへ一致する
- 全checkpointが同じstore IDを持ち、reservation集合がappend-onlyである
- supplied storeのlogical snapshotがcurrent checkpointとexact matchする

supplied storeはrestore後に作られたcopyでも構いません。ただしlogical equivalenceが示すのはそのcopyの内容だけです。backupが作られたこと、restore手順が実行されたこと、元storeと同じ物理fileであることは示しません。

verifierは入力fileをdescriptorへ固定し、読込前にsizeを検査し、読込中のidentity/size/mtime driftを拒否します。nonce storeは最大64 MiB、10,000 reservationで、queryには30秒のdeadlineがあります。store snapshotを一貫させるため、成功または失敗reportを確定するまでSQLiteのDELETE-journal read transactionを保持します。最大1,024 signature、全体120秒、1 signature 30秒の上限があります。長いchainはwriterを待たせ得るため、protected maintenance windowで実行してください。

`EXPECTED_SSH_KEYGEN_SHA256`もmanifest pinと同じく、検証対象host上でその場計算した値ではなく独立protected pinから渡します。一致は実行bytesを固定しますが、そのbinaryのvendor provenance、supply-chain authority、脆弱性不存在までは証明しません。

## Exit codesとschema

- builder `0 / CHAIN_BUNDLE_CREATED`: deterministic private manifestを新規fileへ作成
- verifier `0 / SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE`: supplied chain pathとsupplied storeの限定された一致
- `1 / INVALID`: input、strict JSON、digest、signature、link、policy、store equivalenceのいずれかを拒否
- `2`: usage error

machine-readable contractは次の3件です。

- [`attestation-nonce-store-checkpoint-chain-bundle.schema.json`](../schemas/attestation-nonce-store-checkpoint-chain-bundle.schema.json)
- [`attestation-nonce-store-checkpoint-chain-bundle-creation.schema.json`](../schemas/attestation-nonce-store-checkpoint-chain-bundle-creation.schema.json)
- [`attestation-nonce-store-checkpoint-chain-verification.schema.json`](../schemas/attestation-nonce-store-checkpoint-chain-verification.schema.json)

## まだ証明しないこと

- external protected pinを管理するsystem/personの権威・不可変性
- pinned `ssh-keygen` binaryのvendor provenance / supply-chain authority
- trusted clock、freshness、timestamp attestation
- 提示されなかったcheckpoint、削除された履歴、parallel branchの不存在
- authoritative complete history、actual store continuity、anti-rollback anchor
- key rotation、1,024 checkpoint後または10,000 reservation後のsegmentation
- backup作成、restore実行、restore sourceの真正性
- reported Compose execution、current daemon/image/runtime
- Promotion、Current Truth、Final Human GO、Public Beta GO

従ってR20は、private recovery検証に使える強い候補bindingを作りますが、external anchorやrestore drillの代替ではありません。
