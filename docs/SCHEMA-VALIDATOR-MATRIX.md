# Schema / Validator / Test Matrix

このページは、公開Company starterを読む人が「どのschemaを、どのCLIで、どの
testとrunbookで確認するか」を一つの順序で辿るためのnavigation projectionです。
schema単体のPASS、validatorのPASS、testのPASSは、Human approval、runtime、
provider、Voice / Discord E2E、Promotion、Current Truth、Public Beta GOを作りません。
公開面は常にread-only / candidate-only、`NO_GO_UNPUBLISHED`です。

## Read next: ideal -> current -> smoke

- **Ideal:** [Company Template](../templates/company/README.md)、[Blocks](../templates/blocks/README.md)、
  [Governed Records](../templates/records/README.md)、[MOCs](../templates/mocs/README.md)の順に、
  会社の境界、仕事の単位、証拠の保存先、目的別の読み順を確認します。
- **Current:** [Company Pack Catalog](COMPANY-PACK-CATALOG.md)でschema対応の全体を一覧し、
  [Company Pack Guided Next Steps](COMPANY-PACK-NEXT-STEPS.md)で現在地と次の一手を選びます。
- **Artifact map:** [Review-chain artifact map](STARTER-WALKTHROUGH.md#review-chain-artifact-map)
  はReview Bundle, Review Request, Review Response, and Decision Handoffの保存物、
  candidate state、次のhandoffを一覧します。It is usable before or after the external-free smoke;
  read-only/candidate-onlyの案内であり、Human Decision、Promotion、Current Truth、
  runtime、Public Beta GOを作りません。
- **Smoke:** [Validation Guide](VALIDATION.md)、[Starter Walkthrough](STARTER-WALKTHROUGH.md)、
  [Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)、および
  [Public starter smoke regression](../tests/test_public_starter_runbook_smoke.py)で、
  外部接続なしのcandidate pathと回帰契約を確認します。

このfirst-stopはread-only/candidate-onlyの案内です。schema、validator、test、runbookの
PASSはruntime、provider、Voice / Discord E2E、Human approval、Promotion、Current Truth、
Final Human GOを作らず、公開状態は`NO_GO_UNPUBLISHED`のままです。

## 使い方

1. Company Templateから始め、下表を上から順に読む。
2. schemaはportableな形、CLIはcross-fileと公開安全境界、testは回帰例を確認する。
3. runbookのPowerShellまたはPOSIXコマンドを、自分の作業copyへ適用する。
4. `PASS`した範囲をreceiptやreview bundleへ束ねる。PASSの範囲をruntimeや承認へ
   拡張しない。

## Runbook smoke

公開starterの導入順を、外部接続なしの一時directoryで実際に通す回帰スモークを
[Company Pack Catalog](COMPANY-PACK-CATALOG.md)からも辿れます。対応する
[`test_public_starter_runbook_smoke.py`](../tests/test_public_starter_runbook_smoke.py)と
[`test_company_pack_catalog_runbook_smoke_entry.py`](../tests/test_company_pack_catalog_runbook_smoke_entry.py)
が実行します。guided optionを使う候補では、initializer → validator → Catalog →
customization → Public Preview → Next Steps → Review Bundle → Review Request →
Review Response → Review Decision Handoff → verifyの順に進み、保存した
bundle、request、response、handoffをそれぞれ照合します。実行順を一行で
再確認する場合は、次の完全chainを使います。

`initializer -> validator -> Catalog -> customization -> Public Preview -> Next Steps -> Review Bundle -> Review Request -> Review Response -> Review Decision Handoff -> verify`

これはexact bytesの候補固定であり、承認・Promotion・Current Truth・runtime
readiness・Public Beta GOではありません。
各verificationの結果が`MATCH`になることは、現在bytesと保存metadataが一致した
という意味だけで、Human DecisionやPromotionを意味しません。
生成側の状態は`CANDIDATE_FOR_GOVERNED_REVIEW`であり、Human Decisionではありません。

guided optionを指定しない通常の2引数initializerもスモーク対象です。この場合は
customizationが`CUSTOMIZATION_REQUIRED`のままなので、Review Bundle builderは
`BUNDLE_REFUSED`として停止します。拒否を成功bundleとして保存したりverifyしたりせず、
静的値を決めた新規Packでguided pathを使ってください。どちらの結果も
read-only/candidate-onlyであり、`NO_GO_UNPUBLISHED`を維持します。

## 1. Company Template

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-manifest.schema.json](../schemas/company-manifest.schema.json) | [`validate_template_pack.py`](../tools/validate_template_pack.py) | [`test_validate_template_pack.py`](../tests/test_validate_template_pack.py) | [Company Template](../templates/company/README.md)。manifestの形、参照、境界を検査する。runtimeやowner authorityは検証しない。 |

## 2. Blocks

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [block.schema.json](../schemas/block.schema.json) | [`validate_template_pack.py`](../tools/validate_template_pack.py) | [`test_validate_template_pack.py`](../tests/test_validate_template_pack.py) | [Blocks](../templates/blocks/README.md)。入力・出力・authority・denial・verificationの候補構造を検査する。実行権限は付与しない。 |

## 3. Governed Records

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [record.schema.json](../schemas/record.schema.json) | [`validate_template_pack.py`](../tools/validate_template_pack.py) | [`test_validate_template_pack.py`](../tests/test_validate_template_pack.py) | [Governed Records](../templates/records/README.md)。必須field、role分離、retention参照、denied claimsを候補として検査する。実データの真正性や保持実施は証明しない。 |

## 4. MOCs

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [moc.schema.json](../schemas/moc.schema.json) | [`validate_template_pack.py`](../tools/validate_template_pack.py) | [`test_validate_template_pack.py`](../tests/test_validate_template_pack.py) | [MOC index](../templates/mocs/README.md)。`navigation_only`、未知ID拒否、primary全順序、secondary ordered subsequenceを検査する。MOCはSSOTや実行権限にならない。 |

## 5. Company Pack Catalog

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-catalog.schema.json](../schemas/company-pack-catalog.schema.json) | [`catalog_company_pack.py`](../tools/catalog_company_pack.py) | [`test_catalog_company_pack.py`](../tests/test_catalog_company_pack.py) | [Company Pack Catalog](COMPANY-PACK-CATALOG.md)。PackのBlock / Record / MOC対応をread-onlyで一覧する。`INVALID_PACK`は安全な空出力を返すが、承認やCurrent Truthは作らない。 |

## 6. Customization

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [customization-report.schema.json](../schemas/customization-report.schema.json) | [`check_company_pack_customization.py`](../tools/check_company_pack_customization.py) | [`test_check_company_pack_customization.py`](../tests/test_check_company_pack_customization.py) | [Customization Checklist](CUSTOMIZATION-CHECKLIST.md)。placeholder、governed review、external evidenceを分離して列挙する。`READY_FOR_GOVERNED_REVIEW`は承認ではない。 |

## 7. Public Preview Self-check

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-public-preview-check.schema.json](../schemas/company-pack-public-preview-check.schema.json) | [`check_company_pack_public_preview.py`](../tools/check_company_pack_public_preview.py) | [`test_company_pack_public_preview_check.py`](../tests/test_company_pack_public_preview_check.py) | [Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)。validator、Catalog、customization、false-claim境界を一つのread-only reportへ集約する。Public Beta GOは常にfalse。 |

## 8. Company Pack Next Steps

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-next-steps.schema.json](../schemas/company-pack-next-steps.schema.json) | [`plan_company_pack_next_steps.py`](../tools/plan_company_pack_next_steps.py) | [`test_plan_company_pack_next_steps.py`](../tests/test_plan_company_pack_next_steps.py) | [Company Pack Next Steps](COMPANY-PACK-NEXT-STEPS.md)。現在地、理想flow、分類別件数、次コマンドをread-onlyで案内する。file変更、review、authority、GOは作らない。 |

## 9. Review Bundle

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-review-bundle.schema.json](../schemas/company-pack-review-bundle.schema.json) | [`build_company_pack_review_bundle.py`](../tools/build_company_pack_review_bundle.py) → [`verify_company_pack_review_bundle.py`](../tools/verify_company_pack_review_bundle.py) | [`test_build_company_pack_review_bundle.py`](../tests/test_build_company_pack_review_bundle.py)、[`test_verify_company_pack_review_bundle.py`](../tests/test_verify_company_pack_review_bundle.py) | [Review Bundle](REVIEW-BUNDLE.md)。manifest / Block / MOC / Recordのexact bytes、SHA-256、sizeを候補へ束縛する。MATCHはreviewer identity、Human Decision、Promotion、Current Truth、Final Human GOではない。 |

## 10. Review Request

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-review-request.schema.json](../schemas/company-pack-review-request.schema.json) | [`build_company_pack_review_request.py`](../tools/build_company_pack_review_request.py) | [`test_build_company_pack_review_request.py`](../tests/test_build_company_pack_review_request.py) | [Review Request](REVIEW-REQUEST.md)。保存済みbundleと現在Packの`MATCH`から、実際のreview itemとexternal evidence gapを手転記なしで束ねる。成功状態は`PENDING_AUTHORIZED_REVIEW`、`selected_outcome: null`で、承認を作らない。 |

PowerShell:

```powershell
python tools\build_company_pack_review_request.py `
  work\my-company-review-bundle.json `
  work\my-company
```

POSIX:

```bash
python3 tools/build_company_pack_review_request.py \
  work/my-company-review-bundle.json \
  work/my-company
```

## 11. Review Response

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-review-response.schema.json](../schemas/company-pack-review-response.schema.json)、[company-pack-review-response-verification.schema.json](../schemas/company-pack-review-response-verification.schema.json) | [`build_company_pack_review_response.py`](../tools/build_company_pack_review_response.py) → [`verify_company_pack_review_response.py`](../tools/verify_company_pack_review_response.py) | [`test_company_pack_review_response.py`](../tests/test_company_pack_review_response.py) | [Review Response](REVIEW-RESPONSE.md)。saved requestのimmutable itemを保持したまま、各outcome/noteだけを編集・照合する。`ITEM_RESPONSES_MATCH_REQUEST`は構造一致だけで、identity、authority、全体Decision、evidence解決を作らない。 |

PowerShell:

```powershell
python tools\build_company_pack_review_response.py `
  work\my-company-review-request.json
python tools\verify_company_pack_review_response.py `
  work\my-company-review-request.json `
  work\my-company-review-response.json
```

POSIX:

```bash
python3 tools/build_company_pack_review_response.py \
  work/my-company-review-request.json
python3 tools/verify_company_pack_review_response.py \
  work/my-company-review-request.json \
  work/my-company-review-response.json
```

## 12. Review Decision Handoff

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-review-decision-handoff.schema.json](../schemas/company-pack-review-decision-handoff.schema.json)、[company-pack-review-decision-handoff-verification.schema.json](../schemas/company-pack-review-decision-handoff-verification.schema.json) | [`build_company_pack_review_decision_handoff.py`](../tools/build_company_pack_review_decision_handoff.py) → [`verify_company_pack_review_decision_handoff.py`](../tools/verify_company_pack_review_decision_handoff.py) | [`test_company_pack_review_decision_handoff.py`](../tests/test_company_pack_review_decision_handoff.py) | [Review Evidence to Decision Handoff](REVIEW-DECISION-HANDOFF.md)。bundle、request、response、各verification、現在Packを再束縛する。`DECISION_HANDOFF_MATCH`でも`decision: null`、`selected_outcome: null`を維持し、Human DecisionやPromotionを作らない。 |

PowerShell:

```powershell
python tools\build_company_pack_review_decision_handoff.py `
  work\my-company-review-bundle.json `
  work\my-company `
  work\my-company-review-bundle-verification.json `
  work\my-company-review-request.json `
  work\my-company-review-response.json `
  work\my-company-review-response-verification.json
python tools\verify_company_pack_review_decision_handoff.py `
  work\my-company-review-bundle.json `
  work\my-company `
  work\my-company-review-bundle-verification.json `
  work\my-company-review-request.json `
  work\my-company-review-response.json `
  work\my-company-review-response-verification.json `
  work\my-company-review-decision-handoff.json
```

POSIX:

```bash
python3 tools/build_company_pack_review_decision_handoff.py \
  work/my-company-review-bundle.json \
  work/my-company \
  work/my-company-review-bundle-verification.json \
  work/my-company-review-request.json \
  work/my-company-review-response.json \
  work/my-company-review-response-verification.json
python3 tools/verify_company_pack_review_decision_handoff.py \
  work/my-company-review-bundle.json \
  work/my-company \
  work/my-company-review-bundle-verification.json \
  work/my-company-review-request.json \
  work/my-company-review-response.json \
  work/my-company-review-response-verification.json \
  work/my-company-review-decision-handoff.json
```

この10〜12のPASSは、review chainをcandidate bytesへ束縛するlocal / synthetic
証拠です。reviewer identity、authority、Human approval、trusted time、外部evidence
解決、runtime、Promotion、Current Truth、Final Human GOを作らず、公開状態は
`NO_GO_UNPUBLISHED`のままです。

## 13. Official Cloudflare OS bounded candidates

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [cloudflare-os-upstream-pin.schema.json](../schemas/cloudflare-os-upstream-pin.schema.json) | [`validate_cloudflare_os_candidate.py`](../tools/validate_cloudflare_os_candidate.py) | [`test_cloudflare_os_candidate.py`](../tests/test_cloudflare_os_candidate.py) | [Cloudflare OS adoption](CLOUDFLARE-OS-ADOPTION.md)。official starter/core の exact source pin と content-free Gatekeeper projection を検査する。install、provider execution、billing、private Context、Promotion、Current Truth、Public Beta GO は証明しない。 |
| [cloudflare-os-local-runtime-evaluation.schema.json](../schemas/cloudflare-os-local-runtime-evaluation.schema.json) | [`validate_cloudflare_os_local_runtime_evaluation.py`](../tools/validate_cloudflare_os_local_runtime_evaluation.py) | [`test_cloudflare_os_local_runtime_evaluation.py`](../tests/test_cloudflare_os_local_runtime_evaluation.py) | [Cloudflare OS local runtime evaluation](CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md)。保存済み content-free local receipt の source pin、integrity、1060-test totals、loopback/body/cleanup、P0/P1/P2、zero effect を検査する。再実行freshness、provider deployment、private Context、production、Public Beta GO は証明しない。 |

## Public starterの同じ実行順

既存exampleを変更せず、必ず新しい作業copyで実行します。

### PowerShell

```powershell
New-Item -ItemType Directory -Force work | Out-Null
$ExpiresAt = (Get-Date).ToUniversalTime().AddDays(1).ToString("o").Replace("+00:00", "Z")
python tools\create_company_pack.py my-company work\my-company `
  --human-intent-ref human-intent:governed-alpha-v1 `
  --authority-expires-at $ExpiresAt `
  --retention-policy-ref retention-policy:governed-v1
python tools\validate_template_pack.py work\my-company
python tools\catalog_company_pack.py work\my-company --format markdown
python tools\check_company_pack_customization.py work\my-company
python tools\check_company_pack_public_preview.py work\my-company --format markdown
python tools\plan_company_pack_next_steps.py work\my-company --format markdown
$BundlePath = 'work\my-company-review-bundle.json'
if (Test-Path -LiteralPath $BundlePath) { throw 'bundle target already exists' }
$BundleJson = python tools\build_company_pack_review_bundle.py work\my-company
if ($LASTEXITCODE -ne 0) { throw 'bundle was refused' }
[IO.File]::WriteAllText($BundlePath, ($BundleJson -join [Environment]::NewLine) + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
python tools\verify_company_pack_review_bundle.py $BundlePath work\my-company
```

### POSIX

```bash
mkdir -p work
expires_at="$(python3 -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"))')"
python3 tools/create_company_pack.py my-company work/my-company \
  --human-intent-ref human-intent:governed-alpha-v1 \
  --authority-expires-at "$expires_at" \
  --retention-policy-ref retention-policy:governed-v1
python3 tools/validate_template_pack.py work/my-company
python3 tools/catalog_company_pack.py work/my-company --format markdown
python3 tools/check_company_pack_customization.py work/my-company
python3 tools/check_company_pack_public_preview.py work/my-company --format markdown
python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown
bundle_path='work/my-company-review-bundle.json'
if [ -e "$bundle_path" ]; then
  printf '%s\n' 'bundle target already exists' >&2
  exit 1
fi
python3 tools/build_company_pack_review_bundle.py work/my-company > "$bundle_path"
python3 tools/verify_company_pack_review_bundle.py "$bundle_path" work/my-company
```

この順序は、構造 → 一覧 → customization → preview boundary → 次の一手 → exact
bytesの順に候補を狭めます。保存したreportやbundleは、candidate-bound reviewへ
渡すための入力であり、公開、deploy、restart、provider transfer、Voice / Discord
E2E、Promotion、Current Truth、Public Beta GOを意味しません。

## Full review-chain smoke

After the starter bundle reaches `MATCH`, the public executable smoke continues
through the complete candidate-only chain: Review Request -> Review Response ->
Review Decision Handoff. It runs all 13 existing Company Pack CLIs in an OS
temporary directory, removes the synthetic candidate and artifacts, and emits
one closed report only after cleanup.

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-review-chain-smoke.schema.json](../schemas/company-pack-review-chain-smoke.schema.json) | [`smoke_company_pack_review_chain.py`](../tools/smoke_company_pack_review_chain.py) | [`test_company_pack_review_chain_smoke_cli.py`](../tests/test_company_pack_review_chain_smoke_cli.py) | [Starter Walkthrough](STARTER-WALKTHROUGH.md)。13 step、temporary cleanup、all-false claimsだけを閉じる。Human approval、runtime、Promotion、Current Truth、Public Beta GOではない。 |

```powershell
python -S -B tools/smoke_company_pack_review_chain.py
```

```bash
python3 -S -B tools/smoke_company_pack_review_chain.py
```

The unittest remains the regression interface for the same flow:

```powershell
python -m unittest tests.test_public_starter_runbook_smoke.PublicStarterRunbookSmokeTests.test_guided_starter_chain_reaches_bundle_match_in_a_temporary_pack -v
```

```bash
python3 -m unittest tests.test_public_starter_runbook_smoke.PublicStarterRunbookSmokeTests.test_guided_starter_chain_reaches_bundle_match_in_a_temporary_pack -v
```

The smoke asserts pending request state, structural item response matching, and
`decision: null` / `selected_outcome: null` in the handoff. All claims remain
false and `NO_GO_UNPUBLISHED` remains in force; this does not create reviewer
identity, Human approval, runtime, Promotion, Current Truth, or Public Beta GO.

## Related guidance

- [Template Guide](TEMPLATE-GUIDE.md) — ideal/currentの会社テンプレート設計
- [Validation Guide](VALIDATION.md) — fail-closed validatorとnegative tests
- [Starter Walkthrough](STARTER-WALKTHROUGH.md) — 初回作業copyの歩き方
- [Installation Lifecycle](INSTALLATION-LIFECYCLE.md) — runtime profileを読む場合の別境界
