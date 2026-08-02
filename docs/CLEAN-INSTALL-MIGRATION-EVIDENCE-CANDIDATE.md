# Clean Install / Migration Evidence Candidate

この契約は、Compose clean installと2つのdatabase migrationについて、外部runnerが報告した結果をexact candidateへ束縛するための**未attestation evidence candidate**です。Docker、Compose、PostgreSQLへ接続したり、container作成・起動・migration・write testを実行するツールではありません。

## 何を確認するか

saved verifierは次の3 fileを同時に読みます。

1. `compose_clean_install_migration_evidence_candidate`
2. [Resolved Compose Candidate](RESOLVED-COMPOSE-CANDIDATE.md)
3. [Compose Image Availability Preflight](IMAGE-AVAILABILITY-PREFLIGHT.md)の成功snapshot

evidence candidateについて、closed JSON structure、自己digest、candidate/preflightのfile SHA-256、project・resolved contract・image・daemon・local image binding、Work Order・target locator・before-stateのhash、executor/reviewerの異なるidentity hash、2 serviceのmigration path/hash、別々のevidence hash、positive/negative checkのreported completenessを検査します。

## 2 serviceで必要なreported checks

`company-db`と`evidence-store`をこの順で記録します。各serviceには別のprivate evidence objectを用意し、そのSHA-256だけをcandidateへ含めます。raw SQL、command output、credential、host/container identifierは含めません。

Positive checks:

- candidateのmigration digestと一致したと報告された
- 必須core tableが存在したと報告された
- 期待roleが存在したと報告された
- health queryが成功したと報告された
- transaction内write/read smokeが成功しrollbackされたと報告された

Negative checks:

- wrong roleのDDLが拒否されたと報告された
- wrong roleのwriteが拒否されたと報告された
- cross-store accessが拒否されたと報告された
- public network accessが拒否されたと報告された
- dirty schemaまたはduplicate migrationが拒否されたと報告された

これらはすべて`*_reported`です。JSON writerが自分でtrueを書けるため、この候補だけで実行事実を証明しません。

## 非開示と役割分離

- Work Order、target locator、before-state、executor、reviewerは生値ではなくSHA-256 binding
- executorとreviewerのidentity hashは異なることが必須
- `protected_attestation_verified`は常にfalse
- credential value、raw command output、raw host identityは非出力
- image pull/mutation、daemon変更、不可逆delete、provider transferはfalse
- 2 serviceで同じevidence digestを再利用しない

hashが異なることは、実在する別人や独立reviewを証明しません。protected runner側でidentity、署名、trust rootを検証する必要があります。

保存候補へOpenSSH署名、許可署名者、限定evaluation clock、nonce snapshotを重ねる次段は[Protected Compose Evidence Attestation](PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)です。そのpoint-in-time PASSもreported checksの真実性や原子的nonce予約を証明しません。

## 保存候補を検査する

```powershell
python tools\verify_compose_clean_install_migration_evidence_candidate.py <private-evidence-candidate.json> <private-resolved-candidate.json> <private-image-preflight.json>
```

終了codeは次のとおりです。

- `0`: `UNATTESTED_EVIDENCE_BINDING_ONLY`
- `1`: structured refusal `INVALID`
- `2`: 使い方の誤り

成功reportでtrueになり得るのは、evidence candidateの自己digest、candidate/preflight binding、reported check completeness、role-separation structureだけです。authenticity、freshness、atomicity、current daemon/image、clean install、service start、migration、DB checks、least privilege、restart/rollback/backup/restore、Promotion、Current Truth、Final Human GO、Public Beta GOは常にfalseです。

古い`reported_at`でもstructureが正しければhistorical bindingとして通り得ます。freshness判定は行いません。自己digestも署名ではありません。

## 公開exampleを置かない理由

このrepositoryには、成功したclean installやmigrationを装うsample receiptを置きません。schemaとtest fixtureはshapeを検証しますが、実環境receiptはprivate evidence boundaryでprotected runnerが生成し、別のtrust/freshness検証を通す必要があります。

## Schema

- [`compose-clean-install-migration-evidence-candidate.schema.json`](../schemas/compose-clean-install-migration-evidence-candidate.schema.json)

このschemaやsaved verifierのPASSは、live installation receiptやPublic Beta GOではありません。
