# Protected Compose Evidence Attestation

このCLIは、保存済みのCompose clean-install/migration evidence candidateに対し、独立reviewerが作ったOpenSSH detached signatureと限定された時刻・nonce policyを検査します。Docker、Compose、database、networkへ接続せず、秘密鍵を読みません。

## この段階で増える保証

`SIGNATURE_AND_POLICY_MATCH_POINT_IN_TIME`は、次の条件が同時に成立したことだけを示します。

- R16のevidence candidate、resolved candidate、image preflightが再検証に成功した
- attestation JSONの**exact bytes**に対するOpenSSH署名が、指定された`allowed_signers` trust rootで検証できた
- CLIへ渡したsigner identityのSHA-256がattestation内のbindingと一致した
- signer roleが`independent_reviewer`、namespaceが`kotodama-compose-evidence`である
- evidence fileのexact SHA-256が署名済みattestationと一致した
- `reported_at`から署名発行までが0〜300秒、署名windowが正の値かつ最大900秒、明示した評価時刻がwindow内である
- nonce-use snapshotが評価時刻以前かつ60秒以内で、対象nonceがそのsnapshotに存在しなかった

署名は「許可された鍵を持つ主体がattestation bytesへ署名した」ことを示します。署名対象のreported checksが実際に実行されたこと、報告が真実であること、reviewerが別人であることまでは証明しません。

## 必要なprivate inputs

公開repositoryへ値を保存せず、protected runner内で次を用意します。

1. `protected_compose_evidence_attestation` JSON
2. そのexact bytesに対するOpenSSH detached signature
3. R16 evidence candidate
4. resolved Compose candidate
5. image availability preflight snapshot
6. OpenSSH `allowed_signers` file
7. nonce-use snapshot
8. signer identityだけを1行で持つfile
9. 明示的な評価時刻

attestationのportable shapeは[`protected-compose-evidence-attestation.schema.json`](../schemas/protected-compose-evidence-attestation.schema.json)、nonce snapshotは[`nonce-use-snapshot.schema.json`](../schemas/nonce-use-snapshot.schema.json)です。identity、public key、署名、private evidenceの成功exampleはrepositoryへ置きません。

## 署名と検証

attestation JSONを完成させた後、そのfile bytesを変更せず署名します。

```powershell
ssh-keygen -Y sign -f <private-reviewer-key> -n kotodama-compose-evidence <private-attestation.json>
```

検証では同じattestation bytesと`.sig`を渡します。

```powershell
python tools\verify_protected_compose_evidence_attestation.py `
  <private-attestation.json> `
  <private-attestation.json.sig> `
  <private-evidence-candidate.json> `
  <private-resolved-candidate.json> `
  <private-image-preflight.json> `
  <private-allowed-signers> `
  <private-nonce-snapshot.json> `
  <private-signer-identity-file> `
  <evaluated-at-ISO-8601>
```

CLIは`ssh-keygen -Y verify`だけを実行します。終了codeは、成功`0`、structured refusal`1`、usage error`2`です。identity値をprocess argumentへ載せずfileから読みます。標準出力には入力path、identity、public key、署名内容、raw evidenceを出さず、各入力のSHA-256と正規化した評価時刻だけを返します。

## replay境界

nonce snapshotの検査はread-onlyです。成功しても`nonce_absent_in_snapshot_verified=true`にしかならず、`atomic_nonce_reservation_verified`は常にfalseです。並行実行間のraceを防ぐには、protected system側で次を一つのtransactionとして実行する必要があります。

1. nonce未使用を確認する
2. 同じnonceを一意制約付きで予約する
3. attestationを評価する
4. outcomeとevaluation clockをappend-only receiptへ固定する

このrepositoryのCLIはそのstate mutationを行いません。さらに、supplied trust rootがcanonical pinと一致すること、評価時刻がtrusted clock由来であること、nonce snapshotがauthoritative source由来であることも単独では証明しません。対応する3 claimは常にfalseです。したがってpoint-in-time PASSを、完全なreplay preventionやone-use execution approvalとして扱わないでください。

同一private SQLite store内のrace-safeな一回限り予約を行う次段は[One-Use Compose Attestation Evaluation](ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)です。store continuityやtrusted clockはその段階でも別gateです。

## 常にfalseの範囲

成功時でも、execution authenticity、observation freshness/atomicity、current daemon/image、clean install、service start、migration、database checks、least privilege、restart、rollback、backup、restore、Promotion、Current Truth、Final Human GO、Public Beta GOはすべてfalseです。

実環境で次の段階へ進むには、trust rootのcanonical pin、原子的nonce予約、実行主体と独立reviewerの実在分離、protected receipt、scope-matched E2E、candidate-bound Human Decisionが別途必要です。
