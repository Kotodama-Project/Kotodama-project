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

## Session Conversation/Event Ledger Candidate 2

| Schema | Validator / projector | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [session-conversation-event-ledger.schema.json](../schemas/session-conversation-event-ledger.schema.json)、[session-knowledge-projection.schema.json](../schemas/session-knowledge-projection.schema.json) | [`validate_session_conversation_ledger.py`](../tools/validate_session_conversation_ledger.py) | [`test_session_conversation_ledger.py`](../tests/test_session_conversation_ledger.py) | [Session Conversation/Event Ledger](SESSION-CONVERSATION-LEDGER.md)。append-only event、unassigned inboxからの後付けbinding、embedded provider ID/tokenも拒否するpublic-safe refs、actor-kind/authority整合、`UNVERIFIED_PUBLIC_CLAIM`のHuman-shaped identity、非system consent、discord_voiceのspeaker/source/evidence parityとreceipt-bound `voice_reply`、hash chain、idempotency、causal/lifecycle target、raw/derived artifact lineageとstorage-class parity、Session/Task/Invocation/grant provenance、tiered provider-neutral Archive Target、invalidation、候補とHuman evidenceの分離、projection digest/head再構築だけを標準ライブラリで検査する。Schemaとvalidatorはderived parent、archive/delete tuple、integrity marker、offline recovery、model provenanceの同じ負例を拒否する。`LEDGER_VALID` は構造上の `LOCAL_PASS` のみで、person authentication、promotion eligibility、device/provider/public/Human GO、Current Truth、live connector、compaction summaryのsource authorityを意味しない。 |

```powershell
python tools\validate_session_conversation_ledger.py validate path\to\ledger.jsonl
python tools\validate_session_conversation_ledger.py project path\to\ledger.jsonl ref/session/example
```

```bash
python3 tools/validate_session_conversation_ledger.py validate path/to/ledger.jsonl
python3 tools/validate_session_conversation_ledger.py project path/to/ledger.jsonl ref/session/example
```

## 13. Agent orchestration route-binding candidate

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-agent-orchestration-route-binding-candidate.schema.json](../schemas/company-pack-agent-orchestration-route-binding-candidate.schema.json) | [`validate_company_pack_agent_orchestration_route_binding_candidate.py`](../tools/validate_company_pack_agent_orchestration_route_binding_candidate.py) | [`test_company_pack_agent_orchestration_route_binding_candidate_contract.py`](../tests/test_company_pack_agent_orchestration_route_binding_candidate_contract.py) | [Agent Orchestration Route-Binding Candidate](AGENT-ORCHESTRATION-ROUTE-BINDING-CANDIDATE.md)。source / target、workspace / revision、route、preview / confirmation、rollback の opaque comparison と順序だけを read-only で検査する。`PRECONDITIONS_MATCH_UNVERIFIED` は構造・時間窓の候補一致であり、Codex transport、subagent spawn、task send、provider / device / public effect、Human approval、Promotion、Current Truth、Public Beta GOではない。 |

PowerShell:

```powershell
python tools\validate_company_pack_agent_orchestration_route_binding_candidate.py `
  path\to\route-binding-candidate.json
```

POSIX:

```bash
python3 tools/validate_company_pack_agent_orchestration_route_binding_candidate.py \
  path/to/route-binding-candidate.json
```

この candidate は既存の Protected Execution Request / Handoff Candidate schemaを
変更せず、public previewの opaque contractとして追加されます。入力値、private path、
session、host、cwd、credentialは解決・出力せず、複数candidate間のreplay reservationも
証明しません。schemaの`REFUSED_UNVERIFIED`は構造上の拒否候補であり、CLIは
`CANDIDATE_MARKED_REFUSED`で拒否します。Draft 2020-12検証には`requirements-test.txt`の
`jsonschema`が必要で、未導入時は`VALIDATOR_UNAVAILABLE`にfail-closedします。成功・拒否の
どちらも `CANDIDATE_ONLY` / `NO_GO_UNPUBLISHED`を維持します。

## 14. Agent swarm execution candidate

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [company-pack-agent-swarm-execution-candidate.schema.json](../schemas/company-pack-agent-swarm-execution-candidate.schema.json) | [`validate_company_pack_agent_swarm_execution_candidate.py`](../tools/validate_company_pack_agent_swarm_execution_candidate.py) | [`test_company_pack_agent_swarm_execution_candidate_contract.py`](../tests/test_company_pack_agent_swarm_execution_candidate_contract.py) | [Agent Swarm × Kotodama Adoption Candidate](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md)。root / worker / verifier、N/C/W/V budget、parent edge、assignment identity、workspace / revision、handoff binding、lease / TTL、stop conditions の opaque plan を read-only で検査する。`PRECONDITIONS_MATCH_UNVERIFIED` は候補 bytes の構造と内部比較が整ったという意味だけで、Codex transport、subagent spawn、runtime model verification、provider / device / public effect、Human approval、Promotion、Current Truth、Public Beta GOではない。 |

PowerShell:

```powershell
python tools\validate_company_pack_agent_swarm_execution_candidate.py `
  path\to\agent-swarm-execution-candidate.json
```

POSIX:

```bash
python3 tools/validate_company_pack_agent_swarm_execution_candidate.py \
  path/to/agent-swarm-execution-candidate.json
```

この contract は既存 v1 / route-binding schema を変更せず、public preview に bounded
swarm の比較項目を追加します。opaque ref から thread、host、cwd、credential、raw
prompt、private content を解決せず、複数candidate間の replay reservation、実際の child
起動、モデル identity、handoff の送達、lease fencing を証明しません。`V` は verifier の
予約数として記録するだけで、独立検証が実行済みという意味ではありません。schema の
`REFUSED_UNVERIFIED` は構造上の拒否候補であり、CLI は `CANDIDATE_MARKED_REFUSED` で
拒否します。Draft 2020-12 検証には `requirements-test.txt` の `jsonschema` が必要で、
未導入時は `VALIDATOR_UNAVAILABLE` に fail-closed します。成功・拒否のどちらも
`CANDIDATE_ONLY` / `NO_GO_UNPUBLISHED` を維持します。

## 15. Public migration ledger

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [public-migration-ledger.schema.json](../schemas/public-migration-ledger.schema.json) | [`validate_public_migration_ledger.py`](../tools/validate_public_migration_ledger.py) | [`test_public_migration_ledger_contract.py`](../tests/test_public_migration_ledger_contract.py) | [Public Migration Ledger](PUBLIC-MIGRATION-LEDGER.md)。追記専用 JSONL の schema、連番、hash chain、終端分類と移送機構の語彙分離、gate 一貫性だけを read-only で検査する。`LEDGER_CONSISTENT_UNVERIFIED` は記録された処遇が内部整合しているという意味だけで、移行の実行、private 継続性、公開抽出物の公開、依存切替、rollback 予行、独立検証、Human Decision、Promotion、Current Truth、Public Beta GOではない。 |

PowerShell:

```powershell
python tools\validate_public_migration_ledger.py `
  migration\public-migration-ledger.v1.jsonl
```

POSIX:

```bash
python3 tools/validate_public_migration_ledger.py \
  migration/public-migration-ledger.v1.jsonl
```

台帳は `terminal_classification`（`PUBLIC_EXTRACT` / `PRIVATE_RETAIN` / `REGENERATE` /
`DROP`、blocked 中は `null`）と `transfer_mode`（`REAUTHOR` / `GENERATE` / `NO_COPY`）を
別フィールドとして持ち、片方の語彙をもう片方へ入れることを拒否します。これがないと
unclassified 0 件を機械検証できません。すべての識別子は `ref/...` の opaque 参照で、
private path、provider handle、host、参加者識別子、素材そのものは記録しません。
`migration/public-migration-ledger.v1.jsonl` は現時点で未作成であり、空・不在の入力は
`INPUT_INVALID` で fail-closed します。Draft 2020-12 検証には `requirements-test.txt` の
`jsonschema` が必要で、未導入時は `VALIDATOR_UNAVAILABLE` に fail-closed します。

## 16. Public agent lifecycle registry

| Schema | Validator / CLI | Regression test | Runbook / PASSの意味 |
|---|---|---|---|
| [public-agent-lifecycle-registry.schema.json](../schemas/public-agent-lifecycle-registry.schema.json) | [`validate_public_agent_lifecycle_registry.py`](../tools/validate_public_agent_lifecycle_registry.py) | [`test_public_agent_lifecycle_registry_contract.py`](../tests/test_public_agent_lifecycle_registry_contract.py) | [Public Agent Lifecycle Registry](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md)。agent spec / instance / run / lease / event / evidence receipt の追記専用記録を read-only で検査する。fail-closed な outcome contract、親子 edge と zero-capable depth / fan-out budget、失敗終端後だけのretry、lease/event identity、実日時、termination-state対応、bounded input、state machine、hash chainだけを対象にする。`REGISTRY_CONSISTENT_UNVERIFIED` は記録された lifecycle が内部整合しているという意味だけで、agent 起動、dispatch 実行、provider instance の再利用、証跡の独立検証、Human approval、Promotion、Current Truth、Public Beta GOではない。 |

PowerShell:

```powershell
python tools\validate_public_agent_lifecycle_registry.py `
  path\to\registry.jsonl
```

POSIX:

```bash
python3 tools/validate_public_agent_lifecycle_registry.py \
  path/to/registry.jsonl
```

lifecycle state は `prepared -> dispatched -> running -> completed | failed | cancelled | expired` の 7 つだけです。
`degraded` は state ではなく属性で、成功は保存されず `state == completed` かつ完了理由かつ証跡 1 件以上から導出します。
継続性は決して verified になりません。再起動をまたいで前提条件がすべて一致しても結果は
`PRECONDITIONS_MATCH_UNVERIFIED` で、1 つでも食い違えば `WORK_RESUME_ONLY` です。公開レコードは provider が
同じ認可済み instance を再利用したことを証明できないためで、`claims.continuity_verified` と
`claims.provider_instance_reused` は常に `false` です。Draft 2020-12 検証には `requirements-test.txt` の
`jsonschema` が必要で、未導入時は `VALIDATOR_UNAVAILABLE` に fail-closed します。

## Related guidance

- [Template Guide](TEMPLATE-GUIDE.md) — ideal/currentの会社テンプレート設計
- [Validation Guide](VALIDATION.md) — fail-closed validatorとnegative tests
- [Starter Walkthrough](STARTER-WALKTHROUGH.md) — 初回作業copyの歩き方
- [Installation Lifecycle](INSTALLATION-LIFECYCLE.md) — runtime profileを読む場合の別境界
