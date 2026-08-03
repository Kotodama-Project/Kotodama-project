# Candidate-bound Review Workflow

このworkflowは、Company packの作成、bytes照合、人間の判断、後続Promotionを一つの操作にまとめず、追跡可能な別stepとして扱います。review bundleの`MATCH`は「同じbytesを見ている」ことだけを示します。

## Roles and artifacts

| Step | 主なrole | Artifact | このstepだけでは作らないもの |
|---|---|---|---|
| 1. Prepare | Pack preparer | draft Company pack | approval、authority |
| 2. Bind | Candidate builder | saved review bundle + bundle file SHA-256 | reviewer identity、Decision |
| 3. Verify | Independent reviewer | verification report + report file SHA-256 | approval、Promotion |
| 4. Request | Review coordinator | pending review request + request file SHA-256 | selected outcome、approval |
| 5. Respond | authorized reviewer under separate policy | item response candidate + structural report SHA-256 | identity proof、overall Decision |
| 6. Handoff | review coordinator | five-artifact handoff candidate + verification | identity proof、overall Decision |
| 7. Decide | authorized Human / policy | candidate-bound Decision Record | deployment result、Current Truth |
| 8. Execute | bounded Work Order owner | Change Candidate + Verification Receipt | self-Promotion |
| 9. Promote | separate promotion authority | Promotion Decision Record | automatic Public Beta GO |

小さなチームで同じ人が複数roleを担当する場合も、artifactと時刻、どのauthorityで行ったかを分けて記録します。独立性が必須のlaneでは、同一人物を別role名で書くだけでは要件を満たしません。

## 1. Build and save an exact candidate

構造validatorとcustomization checkerを通し、`replacement_required`を0にします。その後、bundle JSONを保存します。

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

$BundlePath = 'work\my-company-review-bundle.json'
$BundleJson = python tools\build_company_pack_review_bundle.py work\my-company
if ($LASTEXITCODE -ne 0) { throw 'bundle was refused' }
Write-NewUtf8File -LiteralPath $BundlePath -Text ($BundleJson + "`n")
```

Bash:

```bash
BundlePath=work/my-company-review-bundle.json
BundleJson=$(python3 tools/build_company_pack_review_bundle.py work/my-company) || exit 1
(set -C; printf '%s\n' "$BundleJson" > "$BundlePath") || {
  printf '%s\n' 'failed to create bundle target without overwriting' >&2
  exit 1
}
```

保存先が既にある場合は上書きせず、新しいcandidate名を使います。bundle内の`bundle_digest`はgoverned JSON bindingsを固定し、bundle fileのSHA-256はverifierが別に計算します。

## 2. Verify the saved bundle

reviewerは、受け取ったbundle fileと候補packを指定します。

```powershell
python tools\verify_company_pack_review_bundle.py `
  work\my-company-review-bundle.json `
  work\my-company
```

```bash
python3 tools/verify_company_pack_review_bundle.py \
  work/my-company-review-bundle.json \
  work/my-company
```

| Result | Exit | 意味 |
|---|---:|---|
| `MATCH` | 0 | saved metadata、bindings、digestと現在のreview-ready Packが一致 |
| `MISMATCH` | 1 | bundle不正、Pack未準備、ID/metadata/binding差分のいずれか |
| usage error | 2 | CLI引数が不正 |

verifierはduplicate JSON key、非finite JSON、unknown/不足field、falseでないclaim、unsafe/重複path、count/order、digestをfail closedで拒否します。Pack側はbuilderと同じ二重checkを再実行します。

`mismatched_paths`は検証済みrelative JSON pathだけを列挙し、Human Intentやretention locatorの値、文書本文は出力しません。bundle自体が不正、またはPackがreview-readyでない場合はpath比較を出しません。

## 3. Prepare the exact pending review request

`MATCH`したsaved bundleとPackから、46件の個別review itemを手転記せず、5件のevidence gapと分けたpending requestを作れます。

```powershell
python tools\build_company_pack_review_request.py `
  work\my-company-review-bundle.json `
  work\my-company
```

```bash
python3 tools/build_company_pack_review_request.py \
  work/my-company-review-bundle.json \
  work/my-company
```

`CANDIDATE_REVIEW_REQUEST`の`selected_outcome`は常に`null`です。保存と非上書きを含む手順、schema、refusal条件は[Company Pack Review Request](REVIEW-REQUEST.md)を参照してください。

## 4. Complete and verify per-item responses

saved requestから46件の`id/category/path/reason`を再入力せず、outcomeと短いnoteだけを編集するresponse candidateを作ります。

```powershell
python tools\build_company_pack_review_response.py `
  work\my-company-review-request.json

python tools\verify_company_pack_review_response.py `
  work\my-company-review-request.json `
  work\my-company-review-response.json
```

```bash
python3 tools/build_company_pack_review_response.py \
  work/my-company-review-request.json

python3 tools/verify_company_pack_review_response.py \
  work/my-company-review-request.json \
  work/my-company-review-response.json
```

`ITEM_RESPONSES_MATCH_REQUEST`は46件のimmutable itemと全outcomeが元requestへ一致したことだけを示します。個別item/noteはverification reportへ反射せず、5件のevidence gapと`selected_outcome=null`を維持します。保存、編集範囲、note hygiene、schema、refusal条件は[Company Pack Review Response Candidate](REVIEW-RESPONSE.md)を参照してください。

## 5. Bind the complete review evidence without deciding

complete response chainを後続Decisionへ手転記せず渡す場合は[Review Evidence to Decision Handoff](REVIEW-DECISION-HANDOFF.md)を使います。builder/verifierはsaved bundle、bundle verification、request、response、response verificationと現在のPackを再照合しますが、`decision: null`、`selected_outcome: null`を維持します。

## 6. Record the Human decision separately

`MATCH`を得た後も、次をDecision Recordへ明示します。

- candidate pack ID
- saved bundle file SHA-256
- bundle digest
- verification report file SHA-256
- request、item response、response verificationの各file SHA-256
- reviewer identity / roleとverified-at
- decision maker identity / authorityとdecided-at
- selected outcome: accept / request changes / reject
- scope、expiry / review trigger、reason
- 未解決の`review_required` / `evidence_required`

bundle/response verifierはidentity、署名、authority、同意、時刻を推測しません。これらをCLI出力へ後付けして元のdeterministic reportを改変せず、別のgoverned Recordへ束縛します。Decision直前にはsaved bundleと現在のPackも再度`MATCH`させます。

## 7. Handle changes without silent rebinding

Packを1 byteでも変更したら、旧bundleは更新しません。

1. 旧candidateを`MISMATCH`またはsupersededとして保持する。
2. validatorとcustomization checkerを再実行する。
3. 新しいbundle fileを新しい名前で保存する。
4. reviewerが新しいbundleをverifyする。
5. 新しいrequest/responseを作り直して再照合する。
6. Human Decisionを新しいbundle/request/response digestへ束縛する。

Decision後の変更を同じcandidateとして扱わず、reviewを最初からやり直します。

## Boundary

このworkflowは署名サービス、protected evidence store、atomic filesystem snapshot、runtime deployment、provider E2E、rollback実行、Promotion、Current Truth、Final Human GO、Public Beta GOを実装しません。重要なlaneではbundle/report bytesをcontent-addressed storeまたはGit revisionへ保存し、identity・signature・retention・access policyを別のWork Orderで閉じます。

機械可読contractは[`company-pack-review-bundle-verification.schema.json`](../schemas/company-pack-review-bundle-verification.schema.json)、[`company-pack-review-response.schema.json`](../schemas/company-pack-review-response.schema.json)、[`company-pack-review-response-verification.schema.json`](../schemas/company-pack-review-response-verification.schema.json)、[`company-pack-review-decision-handoff.schema.json`](../schemas/company-pack-review-decision-handoff.schema.json)、[`company-pack-review-decision-handoff-verification.schema.json`](../schemas/company-pack-review-decision-handoff-verification.schema.json)です。
