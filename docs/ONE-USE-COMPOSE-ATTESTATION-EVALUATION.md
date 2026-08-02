# One-Use Compose Attestation Evaluation

R18は、R17の署名済みattestationを**一度だけ**評価するためのprotected local seamです。外部で固定したpolicy digest、allowed signer file、nonce store identityを照合し、OpenSSH署名検証とSQLite nonce予約を一つの`BEGIN IMMEDIATE` transaction内で行います。

このツールはDocker、Compose、database service、networkへ接続しません。操作するdatabaseは、replay防止専用のprivate SQLite fileだけです。

## 増える保証

`ONE_USE_SIGNATURE_AND_POLICY_MATCH`は次を示します。

- policy fileのexact SHA-256がCLIへ別入力したexpected digestと一致した
- policyがallowed-signers fileとnonce-store identityをSHA-256で固定していた
- policyが`independent_reviewer`、`kotodama-compose-evidence`、最大900秒の署名window、最大300秒のreport-to-signを上限としていた
- R17と同じexact attestation/evidence/candidate/preflight/signature検査に成功した
- evaluationにlocal system UTCを使い、policy/attestationの両window内だった
- bound storeのschema、identity、一意制約がinitializerのexact contractと一致した
- 同じtransactionでnonce、attestation、policy、evidence、signature、allowed signers、identity file、評価時刻のhash bindingを記録した

同じstoreへ同じnonceを同時に二回送っても、一件だけがcommitされ、もう一件は`REPLAY_REFUSED`になります。無効署名・不一致policy・不正evidenceはrollbackされ、nonceを消費しません。

## 1. Work Orderで外部pinを決める

material evaluationの前に、protected Work Orderへ少なくとも次を固定します。

- exact policy file SHA-256
- allowed-signers file SHA-256
- nonce-store ID SHA-256とcanonical file locator
- candidate/evidence/attestationのrevisionまたはdigest
- evaluation window、expected effect、rollback、expiry、stop conditions

CLIへexpected policy digestを渡すだけでは、そのdigestを誰が採用したかは証明できません。`canonical_trust_policy_verified`は常にfalseです。

## 2. one-use storeを一度だけ初期化する

protected boundaryでランダムかつ衝突しない64桁lowercase SHA-256 store IDを作り、空の新規pathを指定します。

```powershell
python tools\initialize_attestation_nonce_store.py <private-nonce-store.sqlite3> <store-id-sha256>
```

initializerはOSのexclusive createを使い、既存file、同時作成、symlink parent、不正IDを拒否します。成功時だけschema version 1、exact table SQL、一意nonce keyを作ります。既存fileを上書きしません。

storeを削除して同じIDで作り直すと過去nonceが失われます。CLIは外部anchor、backup chain、rollback protectionを持たないため、`nonce_store_continuity_verified`は常にfalseです。運用ではcanonical pathへの書込み権限を絞り、store自体の世代管理・restore test・外部digest checkpointを別途行ってください。

commit後にprocessがstdoutを返す前に停止した場合も、store rowが一回限り状態の基準です。同じ入力を再実行すると`REPLAY_REFUSED`になるため、成功を推測で再生成せず、private storeとrunner logをreconcileしてください。

## 3. policy candidateを作る

shapeは[`compose-attestation-one-use-policy.schema.json`](../schemas/compose-attestation-one-use-policy.schema.json)に従います。policyは次を含みます。

- `allowed_signers_file_sha256`
- initializerへ渡した`nonce_store_id_sha256`
- 固定namespaceと`independent_reviewer` role
- `max_signed_window_seconds`（1〜900）
- `max_report_to_signature_seconds`（0〜300）
- policyの`not_before` / `expires_at`
- `clock_source: local_system_utc_untrusted`
- terminal/runtime claimの明示的false

policy、allowed signers、identity、store、attestation、signature、evidenceはprivate boundaryに置きます。成功を装うexampleやprivate identifierはrepositoryへ追加しません。

## 4. 一回限りで評価する

```powershell
python tools\evaluate_compose_attestation_once.py `
  <private-policy.json> `
  <expected-policy-sha256-from-work-order> `
  <private-attestation.json> `
  <private-attestation.json.sig> `
  <private-evidence-candidate.json> `
  <private-resolved-candidate.json> `
  <private-image-preflight.json> `
  <private-allowed-signers> `
  <private-signer-identity-file> `
  <private-nonce-store.sqlite3>
```

終了codeとstatusは次のとおりです。

- `0 / ONE_USE_SIGNATURE_AND_POLICY_MATCH`: 検証とnonce予約を同一transactionでcommit
- `1 / REPLAY_REFUSED`: bound storeにnonceが既に存在
- `1 / INVALID`: 入力、policy、署名、evidence、store、時刻のいずれかを拒否しrollback
- `2`: usage error

stdoutはJSONです。private path、identity、public key、signature body、raw evidenceを出さず、SHA-256 bindingと正規化評価時刻だけを返します。report schemaは[`compose-attestation-one-use-evaluation.schema.json`](../schemas/compose-attestation-one-use-evaluation.schema.json)、initializer reportは[`attestation-nonce-store-initialization.schema.json`](../schemas/attestation-nonce-store-initialization.schema.json)です。

## まだ証明しないこと

- expected policy digestのcanonical adoptionやHuman Decision
- local system clockの改ざん耐性・外部時刻attestation
- nonce storeの削除防止、継続性、backup/restore
- 署名されたreported checksの真実性や別人性
- current daemon/image、clean install、service start、migration、DB checks
- restart、rollback、backup、restore、Promotion、Current Truth
- Final Human GO、Public Beta GO

従ってR18の成功は、bound local store内のrace-safeな一回限り評価です。production runtime receiptやPublic Beta公開判定ではありません。
