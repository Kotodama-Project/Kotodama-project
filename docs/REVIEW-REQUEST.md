# Company Pack Review Request

`build_company_pack_review_request.py`は、保存済みreview bundleと現在のCompany Packが`MATCH`することを再確認し、そのexact candidateについて未解決の46 review itemを手転記なしで依頼artifactへまとめます。5つのexternal evidence gapは別配列に保ちます。

このartifactは**依頼**であり、review結果でもapprovalでもありません。成功時も`state`は`PENDING_AUTHORIZED_REVIEW`、`selected_outcome`は常に`null`、全claimはfalseです。

## Before you run it

先にreview bundleを新規fileへ保存します。既存fileは上書きしません。

```powershell
$BundlePath = 'work\my-company-review-bundle.json'
if (Test-Path -LiteralPath $BundlePath) { throw 'bundle target already exists' }
$BundleJson = python tools\build_company_pack_review_bundle.py work\my-company
if ($LASTEXITCODE -ne 0) { throw 'bundle was refused' }
[IO.File]::WriteAllText($BundlePath, $BundleJson + "`n", [Text.UTF8Encoding]::new($false))
```

```bash
test ! -e work/my-company-review-bundle.json
BundleJson=$(python3 tools/build_company_pack_review_bundle.py work/my-company) || exit 1
printf '%s\n' "$BundleJson" > work/my-company-review-bundle.json
```

bundleの意味と保存形式は[Company Pack Review Bundle](REVIEW-BUNDLE.md)を参照してください。

## Build and save the pending request

PowerShell 7:

```powershell
$RequestPath = 'work\my-company-review-request.json'
if (Test-Path -LiteralPath $RequestPath) { throw 'request target already exists' }
$RequestJson = python tools\build_company_pack_review_request.py `
  $BundlePath `
  work\my-company
if ($LASTEXITCODE -ne 0) { throw 'request was refused' }
[IO.File]::WriteAllText($RequestPath, $RequestJson + "`n", [Text.UTF8Encoding]::new($false))
```

Bash:

```bash
test ! -e work/my-company-review-request.json
RequestJson=$(python3 tools/build_company_pack_review_request.py \
  work/my-company-review-bundle.json \
  work/my-company) || exit 1
printf '%s\n' "$RequestJson" > work/my-company-review-request.json
```

CLI自体はfileを作らず、UTF-8の1行JSONをstdoutへ返します。上のshell例が非上書きで保存します。引数はfile/directory pathだけです。locator値やcredentialをcommand lineへ渡さないでください。

## Success contract

終了code `0`、`CANDIDATE_REVIEW_REQUEST`は次だけを示します。

- 保存bundleがclosed contractとdigestを満たす
- bundleと現在のPackが2回とも`MATCH`した
- bundle fileのSHA-256/byte sizeと22-file bundle digestを依頼へ束縛した
- customization reportが両方とも同一の`READY_FOR_GOVERNED_REVIEW`だった
- `replacement_required=0`で、review/evidence item配列長がbundleのcountと一致した
- 46件の`id/category/path/reason`を`review_request.items`へ、5件を`unresolved_evidence.items`へ値本文なしで分離した

同じsaved bundle bytes、Pack bytes、tool bytesからは同じrequest JSONになります。request fileを共有またはDecision Recordへ参照するときは、保存したrequest file自体のSHA-256も別途記録してください。

## Refusal

終了code `1`、`REQUEST_REFUSED`は候補bindingもitemも作りません。

| Reason | 意味 |
|---|---|
| `BUNDLE_VERIFICATION_FAILED` | bundleが不正、Packが未準備、またはsaved bindingとPackが一致しない |
| `SOURCE_DRIFT_DETECTED` | 読み取り区間でbundle/checker/Packの結果が変化、またはcount/item整合が崩れた |

usage errorは終了code `2`です。拒否JSONは入力path、locator、document本文、validator error本文を反射しません。CLIの複数回checkは通常のlocal filesystem上のdrift検知であり、敵対的processに対するatomic snapshotや署名ではありません。

## Request is not a decision

`permitted_outcomes`の`accept / request_changes / reject`は、後続Decision Recordで使える語彙を示すだけです。このrequestではどれも選択されません。

authorized reviewerは、保存bundle、Pack、requestを照合した後、次を**別のgoverned Decision Record**へ残します。

- reviewer identity / role、authority、独立性、観測時刻
- 各review itemの判断と根拠
- external evidence gapの状態
- 選択したoutcome、scope、expiry / review trigger
- saved bundle file、bundle digest、verification report、request fileの各SHA-256

このtoolはidentity、signature、authority、Human Intent真正性、retention enforcement、人物分離、runtime、deployment、Promotion、Current Truth、Final Human GO、Public Beta GOを作りません。

機械可読contractは[`company-pack-review-request.schema.json`](../schemas/company-pack-review-request.schema.json)、全体順序は[Candidate-bound Review Workflow](REVIEW-WORKFLOW.md)です。
