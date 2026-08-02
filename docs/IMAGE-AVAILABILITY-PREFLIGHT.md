# Compose Image Availability Preflight

Resolved Compose Candidateが要求するmanifest digestを、**既に存在するlocal Docker image**からread-onlyで照合します。imageを取得、tag変更、削除、container作成・起動するツールではありません。

## 証明する範囲

成功snapshotは、観測時刻に次が同時に確認できたことを示します。

- 入力したResolved Compose Candidateが現在のshipped skeletonへ正しく束縛されている
- Docker daemonへread-only queryで到達できた
- candidateの1つのmanifest digestに対応するlocal image IDを一意に特定できた
- `docker image inspect`のRepoDigestにも同じmanifest digestが存在した
- candidate file、project、resolved contract、image manifest、local image ID、rootfs、Docker CLI、daemon fingerprintがsnapshotへ束縛された

`local_image_available_verified: true`は、このsnapshotの`observed_at`と匿名化されたdaemon bindingだけに限定されます。現在も存在すること、別hostにも存在すること、imageの供給元・署名・脆弱性・実行適合性は証明しません。

## 非開示境界

生のdaemon ID、hostname、Docker root path、repository名、tag、RepoDigest文字列、layer digestは出力しません。

- daemon IDはdomain-separated SHA-256へ変換
- repository/tagは照合にだけ使い、出力しない
- layer一覧は順序付きfingerprintへ変換
- Docker CLIは実行fileのSHA-256だけを記録
- Docker stderrや入力file pathは拒否reportへ転送しない

daemon fingerprintも同じhostのsnapshotを相関できる識別子です。実際のsnapshotは公開repositoryへcommitせず、対象Work Orderと同じaccess boundaryで保管してください。

## 1. Resolved Compose CandidateをUTF-8で保存する

private process environmentを設定した後、`--output`を使います。既存fileは上書きしません。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools\resolve_compose_candidate.py kotodama-local-r1 --output work\resolved-compose-candidate.json
```

`>`はWindows PowerShellの版によってnative stdoutをUTF-16へ変換するため、JSON保存には使用しません。

## 2. local imageをread-onlyで照合する

Docker daemonが起動済みで、candidateのdigest-pinned imageが既にlocal inventoryへ存在する場合だけ成功します。

```powershell
python tools\preflight_compose_image_availability.py work\resolved-compose-candidate.json --output work\compose-image-availability.json
```

実行するDocker commandは次の3種類だけです。

- `docker info --format ...`
- `docker image ls --digests --no-trunc --format ...`
- `docker image inspect --format ... <local-image-id>`

imageがない場合は`IMAGE_NOT_AVAILABLE`で停止します。自動pullへfallbackしません。同じmanifest digestが複数のlocal image IDへ曖昧に対応する場合、inspect結果が一致しない場合、daemon/CLI/candidateを検証できない場合もfail closedです。

成功時は終了code `0`、安全な拒否は`1`、使い方の誤りは`2`です。`--output`はUTF-8 JSONを新規作成し、stdoutにも同じbyte列を返します。

## 3. 保存snapshotを候補へ再束縛する

```powershell
python tools\verify_compose_image_availability_preflight.py work\compose-image-availability.json work\resolved-compose-candidate.json
```

`VALID_SNAPSHOT_BINDING`は、snapshotのclosed structure、digest、read-only effects、candidate file hashと各bindingが一致することだけを示します。verifierはDockerへ問い合わせないため、`current_daemon_reachable_verified`と`current_local_image_available_verified`を常に`false`にします。fresh stateが必要ならpreflightを再実行し、新しい時刻・candidate・host bindingへ束縛します。

## 次のWork Order

clean installへ進む前に、少なくとも次をexact Work Orderへ固定します。

- candidate file SHA-256と`resolved_contract_sha256`
- preflight file SHA-256と`preflight_sha256`
- daemon fingerprint、manifest digest、local image ID digest
- target、実行window、作用、stop conditions
- volume/network衝突確認、backup/rollback方針
- credential非開示方法

このsnapshotはpull、start、migration、health、restart、backup、restore、Promotion、Current Truth、Final Human GO、Public Beta GOを許可しません。

## Schema

- [`compose-image-availability-preflight.schema.json`](../schemas/compose-image-availability-preflight.schema.json)

schema PASSもsnapshot integrity PASSも、live clean installやPublic Beta GOではありません。
