# Resolved Compose Candidate

Composeを起動する前に、公開skeleton、project namespace、image digest、network、volume、migration、healthcheckを一つの**資格情報非開示候補**へ固定します。

この候補は`docker compose config`の生JSONを保存しません。生JSONにはprocess environmentから解決したdatabase passwordとhost上の絶対pathが含まれるためです。代わりに、必要な構造をprocess内で検査した後、安全なprojectionだけをJSONへ出力します。

## 前提

- `runtime/compose-minimum`がshipped revisionのままvalidatorを通る
- Docker CLIとCompose pluginが利用できる
- digestまで固定したPostgreSQL image referenceを決めている
- Company DBとEvidence Storeへ別々のprivate passwordをprocess environmentから供給する

この段階ではDocker daemon、image pull、container、database connectionは不要です。

## 1. private process environmentを設定する

以下は変数名の例です。値をshell history、公開log、candidate JSONへ残さない方法は、対象hostのsecret mechanismに合わせてください。

```powershell
$env:KOTODAMA_POSTGRES_IMAGE = '<registry>/<repository>@sha256:<64-hex-digest>'
$env:KOTODAMA_COMPANY_DB_PASSWORD = '<private-distinct-value>'
$env:KOTODAMA_EVIDENCE_DB_PASSWORD = '<private-distinct-value>'
```

POSIX shellでは`export`を使います。次も値を埋めないプレースホルダー例です。実際の値は対象hostのsecret mechanismからshell historyや公開logへ出さずに供給してください。

```sh
export KOTODAMA_POSTGRES_IMAGE='<registry>/<repository>@sha256:<64-hex-digest>'
export KOTODAMA_COMPANY_DB_PASSWORD='<private-distinct-value>'
export KOTODAMA_EVIDENCE_DB_PASSWORD='<private-distinct-value>'
```

`.env`やcredential値をrepositoryへ追加しません。2つのpasswordが空、同一、またはComposeの解決結果と一致しない場合、resolverは候補を作りません。

## 2. safe candidateを作る

repository rootから実行します。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools\resolve_compose_candidate.py kotodama-local-r1 --output work\resolved-compose-candidate.json
```

POSIX shellでの同じ順序は次です。

```sh
mkdir -p work
python3 tools/resolve_compose_candidate.py kotodama-local-r1 --output work/resolved-compose-candidate.json
```

project nameは小文字英数字から始まる2〜63文字の小文字英数字、`_`、`-`だけを受け付けます。

成功時は終了code `0`です。標準出力には次だけが含まれます。

- shipped `skeleton.json`と4 bound fileのSHA-256 / byte size
- bounded project name
- `company-db` / `evidence-store`のrole、internal network、volume、migration binding
- repository名を含まないimageの`sha256:` digest部分
- credentialが2つとも存在し別値だったというboolean contract
- credentialや絶対pathを除外してから計算したresolved contract digest
- すべて`false`のruntime / authority / GO claims

passwordを別の有効な値へ変えても出力とdigestは変わりません。したがってcandidate digestをpassword推測の照合器として利用できません。

失敗時は終了code `1`で、限定されたreason codeだけを出します。Composeのstderr、環境変数名、image reference、credential、絶対pathは転送しません。使い方の誤りは終了code `2`です。

`--output`はUTF-8 JSONを新規作成し、既存fileを上書きしません。stdoutにも同じbyte列を返します。Windows PowerShellの版によってnative stdout redirectがUTF-16化されるため、保存には`>`ではなく`--output`を使います。

## 3. 保存したcandidateを再検査する

```powershell
python tools\validate_resolved_compose_candidate.py work\resolved-compose-candidate.json
```

POSIX shellでは次のように保存済みcandidateを再検査します。

```sh
python3 tools/validate_resolved_compose_candidate.py work/resolved-compose-candidate.json
```

validatorはstrict JSON、closed field set、現在のshipped skeleton revision、role別binding、credential非開示contract、resolved digest、全claim、`NO_GO_UNPUBLISHED`を再検査します。成功は終了code `0`と`PASS`です。

別revisionで作った候補は、sourceが現在のshipped skeletonと一致しないためfail closedになります。過去候補を監査するときは、その候補が束縛したcommitをcheckoutして検証してください。

## 4. 次のWork Orderへ束縛する

runtime preflightまたはimage stagingへ進む場合は、少なくとも次をexact Work Orderへ固定します。

- repository commitとcandidate file SHA-256
- `resolved_contract_sha256`
- target host locatorとproject name
- image digestのavailability確認方法
- 予定する作用（read-only inspection / pull / startなど）
- rollback、実行window、停止条件
- credentialをreceiptへ出さないredaction方法

このcandidateだけを根拠に`docker compose up`へ進みません。

次のread-only段階は[Compose Image Availability Preflight](IMAGE-AVAILABILITY-PREFLIGHT.md)です。既にlocalへ存在するimageだけを照合し、自動pullやcontainer startは行いません。

## 境界

`CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT`は、設定解決と安全なbindingだけを意味します。image availability、Docker daemon、pull、clean install、migration、health、application least privilege、restart、backup、restore、Promotion、Current Truth、Final Human GO、Public Beta GOはすべて未証明です。
