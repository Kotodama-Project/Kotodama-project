# Compose Minimum Data-Plane Skeleton

Company DBとEvidence Store metadataを、1台のhost上でも別service・別internal network・別volumeに分離する最小候補です。

## Included

- PostgreSQL `company-db`と`evidence-store`の2 service
- host portを公開しない2つのinternal network
- serviceごとに分離したvolume
- process環境から必須passwordを受け取る設定（値はrepositoryに置かない）
- digest-pinned PostgreSQL image referenceを必須にし、暗黙pullを拒否する設定
- healthcheck、有限log rotation、停止猶予
- CompanyのRecord/Event/Link最小schema
- EvidenceのObject metadata/Receipt/Receipt-Object link最小schema
- ownerとは別の`NOLOGIN` reader/writer role（deployment固有LOGINは別Work Order）

## Not included

- agent、gateway、n8n、Discord、Voice、provider connector
- large evidence bytesのobject backend
- credential発行、LOGIN role、TLS、host firewall、backup job
- live clean-install、restart、rollback、restore receipt
- Promotion、Current Truth変更、Public Beta GO

## Validate before use

- Machine-readable contract: [`skeleton.json`](skeleton.json)
- Portable structure schema: [`compose-minimum-skeleton.schema.json`](../../schemas/compose-minimum-skeleton.schema.json)

Repository rootから実行します。

```powershell
python tools\validate_compose_minimum_skeleton.py runtime\compose-minimum
```

Validator PASSは、公開skeletonのexact bytesと安全契約だけを示します。
このCLIは上記4 bound fileのshipped revision専用です。`skeleton.json`のdigestを更新しただけのcustom Composeを安全認定しません。customizationは別candidateとしてschema、Compose構造、SQL、tests、review、receiptを更新してください。

## Private preflight values

実行する場合は、private process environmentへ次を設定します。`.env`をcommitしません。

- `KOTODAMA_POSTGRES_IMAGE`: registry/repositoryとSHA-256 digestまで固定した、事前取得済みimage reference
- `KOTODAMA_COMPANY_DB_PASSWORD`: Company DB bootstrap ownerの一時credential
- `KOTODAMA_EVIDENCE_DB_PASSWORD`: Evidence DB bootstrap ownerの一時credential

2つのpasswordは別値にし、runbook/receiptへ値を出しません。runtime application用LOGIN roleはこのskeletonに含まれません。必要なrole、権限、期限、rotation、rollbackを別Work Orderへ束縛します。

## Offline configuration check

値をprocess environmentへ設定した後、外部作用なしでComposeの解決結果を検査し、資格情報非開示のcandidateを作ります。

```powershell
python tools\resolve_compose_candidate.py <bounded-project-name> > work\resolved-compose-candidate.json
python tools\validate_resolved_compose_candidate.py work\resolved-compose-candidate.json
```

`docker compose config`の生出力には解決済みpasswordとhost絶対pathが入るため、保存やreceiptへの添付をしません。resolverは生出力をprocess内だけで検査し、credentialとpathを除外したprojectionを出力します。詳しくは[Resolved Compose Candidate](../../docs/RESOLVED-COMPOSE-CANDIDATE.md)を参照してください。

`pull_policy: never`のため、起動前にdigest-pinned imageを別のbounded手順で取得・照合する必要があります。実行順は[Compose Minimum Runbook](../../docs/COMPOSE-MINIMUM-RUNBOOK.md)に従います。

## Boundary

このskeletonはdata-plane候補です。2つのPostgreSQL containerが実際に起動したこと、migrationが通ったこと、backup/restoreできること、applicationが最小権限で接続できることは、同じcandidateへ束縛したruntime receiptがなければ未証明です。
