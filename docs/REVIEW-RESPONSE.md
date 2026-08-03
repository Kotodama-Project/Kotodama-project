# Company Pack Review Response Candidate

pending requestに含まれるreview itemを、ID・path・reasonの再入力なしで一件ずつ確認するための編集用candidateです。builderはrequestの各itemへ`outcome: null`と`reviewer_note: null`だけを追加します。verifierは編集後も元requestと全itemが一致し、requestが示す件数すべてにoutcomeがあることを確認します。

公開 Company starter の例は22 bindings / 46 review items / 5 evidence itemsです。recordless Packのように構成が異なる場合、builder/verifierは保存済みrequestの実際の`binding_count`、`review_request.item_count`、`unresolved_evidence.item_count`へ追従します。現在のrecordless fixtureは13 / 19 / 5です。

これは**review worksheetと構造照合**です。reviewer identity、authority、独立性、Human approval、全体outcome、Decision Record、5件のexternal evidence、Promotion、Current Truth、Final Human GO、Public Beta GOではありません。

## Ideal use

1. authorized reviewerがsaved bundleと現在のPackを再照合する。
2. saved requestから新しいresponse candidateを生成し、既存fileを上書きせず保存する。
3. 各itemでは`outcome`と必要な`reviewer_note`だけを編集する。
4. 元requestと編集済みresponseをverifierへ渡し、検証reportも新しいfileへ保存する。
5. 別のgoverned Decision Recordがrequest/response/reportのSHA-256、reviewer identity・authority・時刻、全体outcome、未解決evidenceを参照する。
6. PromotionとCurrent Truth変更はさらに別のauthority/processで行う。

## Current implementation

現在のpublic CLIはlocal fileを読み、deterministic UTF-8 JSONをstdoutへ返します。外部provider、identity store、signature、protected evidence store、Packのatomic snapshotへ接続しません。`ITEM_RESPONSES_MATCH_REQUEST`は「保存requestと、そのrequestが束縛する全item responseが構造的に一致した」というpoint-in-timeのlocal resultだけです。

## 1. Build and save the editable candidate

PowerShell 7:

```powershell
function Write-NewUtf8File {
  param([string]$LiteralPath, [string]$Text)
  $Bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
  $Stream = [IO.FileStream]::new(
    $LiteralPath,
    [IO.FileMode]::CreateNew,
    [IO.FileAccess]::Write,
    [IO.FileShare]::None
  )
  try { $Stream.Write($Bytes, 0, $Bytes.Length) }
  finally { $Stream.Dispose() }
}

$RequestPath = 'work\my-company-review-request.json'
$ResponsePath = 'work\my-company-review-response.json'
$ResponseJson = python tools\build_company_pack_review_response.py $RequestPath
if ($LASTEXITCODE -ne 0) { throw 'response candidate was refused' }
Write-NewUtf8File -LiteralPath $ResponsePath -Text ($ResponseJson + "`n")
```

Bash:

```bash
RequestPath=work/my-company-review-request.json
ResponsePath=work/my-company-review-response.json
ResponseJson=$(python3 tools/build_company_pack_review_response.py "$RequestPath") || exit 1
(set -C; printf '%s\n' "$ResponseJson" > "$ResponsePath") || {
  printf '%s\n' 'failed to create response target without overwriting' >&2
  exit 1
}
```

CLI自体はfileを書きません。上の例は既存targetを上書きしません。保存先が存在する場合は、別名の新しいcandidateを作ります。

## 2. Edit only the response fields

`review_response.items`はrequestと同じ順序・件数です。編集してよいのは次だけです。

- `outcome`: `accept` / `request_changes` / `reject`
- `reviewer_note`: `accept`では`null`または短い説明、`request_changes`と`reject`では必須の短い説明

`id`、`category`、`path`、`reason`、`item_count`、binding、evidence、claim、`selected_outcome`は編集しません。noteへcredential、token、個人情報、private absolute path、Human Intent本文を入れず、必要ならsecret-freeなgoverned evidence referenceを使います。

responseの`selected_outcome`は常に`null`です。全itemのoutcomeを埋めても、全体のaccept/request changes/rejectを自動決定しません。

## 3. Verify and save the structural report

PowerShell 7:

```powershell
$ReportPath = 'work\my-company-review-response-verification.json'
$ReportJson = python tools\verify_company_pack_review_response.py `
  work\my-company-review-request.json `
  work\my-company-review-response.json
if ($LASTEXITCODE -ne 0) { throw 'response verification was refused' }
Write-NewUtf8File -LiteralPath $ReportPath -Text ($ReportJson + "`n")
```

Bash:

```bash
ReportPath=work/my-company-review-response-verification.json
ReportJson=$(python3 tools/verify_company_pack_review_response.py \
  work/my-company-review-request.json \
  work/my-company-review-response.json) || exit 1
(set -C; printf '%s\n' "$ReportJson" > "$ReportPath") || {
  printf '%s\n' 'failed to create verification target without overwriting' >&2
  exit 1
}
```

| Result | Exit | 意味 |
|---|---:|---|
| `ITEM_RESPONSES_MATCH_REQUEST` | 0 | request bytes、candidate binding、requestが束縛するimmutable item、全outcome、必要note、unresolved evidenceが一致 |
| `RESPONSE_MISMATCH` | 1 | request/response不正、binding差分、未入力、または読み取り中drift |
| usage error | 2 | CLI引数が不正 |

成功reportは個別itemやnoteを反射せず、request/response file SHA-256・byte count、candidate binding、request由来の完了数、3 outcomeのcount、未解決evidence countだけを返します。

## Safe refusal

builder/verifierは1 MiBを超えるfile、深すぎるJSON、duplicate key、非finite値、unknown/missing field、unsafe/重複item、falseでないclaim、request/response byte driftをfail closedで拒否します。verifierはunknown outcome、欠落/追加/reorder/tamper、`request_changes`/`reject`のnote欠落、高信頼secretらしいnote、private absolute pathらしいnoteも拒否します。

schemaのnote規則は型・長さ・条件付き必須だけを表す構造契約です。verifierのsecret/private-path検査は追加の保守的denylistであり、完全な情報漏えい検出器ではありません。そのためschema validation PASSや`ITEM_RESPONSES_MATCH_REQUEST`だけではnoteの公開安全性を証明しません。authorized reviewerとDecision作成者は、個人情報、private locator、Human Intent本文、denylist未検出のcredentialを含まないことを別途確認します。

拒否reportはPack ID、binding、item、note、入力path、hostile値、OS exception本文を返しません。複数回readは通常のlocal filesystemでのdrift検知であり、敵対的processに対するatomic snapshotやsignatureではありません。

## Before the Human Decision

response検証直前または直後にPackが変わり得るため、Decision Recordを作る前に[saved bundle verifier](REVIEW-WORKFLOW.md#2-verify-the-saved-bundle)で現在のPackをもう一度`MATCH`させます。Decision Recordには少なくとも次を別途束縛します。

5成果物を一つの非承認candidateへ機械的に束縛する手順は[Review Evidence to Decision Handoff](REVIEW-DECISION-HANDOFF.md)です。handoff verifierのMATCHもidentity、authority、全体Decisionを証明せず、`decision: null`を維持します。

- saved bundle、bundle verification、request、response、response verificationの各file SHA-256
- reviewer identity / role / authority / independence evidence / reviewed-at
- decision maker identity / authority / decided-at
- selected overall outcome、scope、reason、expiry / review trigger
- 5件のexternal evidence gapとその他の未解決gate

このpublic CLIは上記の真正性やauthorityを検証しません。machine-readable contractは[`company-pack-review-response.schema.json`](../schemas/company-pack-review-response.schema.json)と[`company-pack-review-response-verification.schema.json`](../schemas/company-pack-review-response-verification.schema.json)です。
