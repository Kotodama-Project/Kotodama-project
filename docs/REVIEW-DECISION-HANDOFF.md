# Review Evidence to Decision Handoff

保存済みのreview bundle、bundle verification、request、response、response verificationの5成果物を、後続のHuman Decisionへ渡すための**非承認handoff candidate**です。builderは現在のCompany Packを再照合し、5ファイルのSHA-256とbyte数を固定します。verifierは保存handoffと現在の同じ入力鎖をもう一度比較します。

成功しても`decision: null`、`selected_outcome: null`、`HUMAN_DECISION_REQUIRED`です。reviewerやdecision makerの本人性・authority、承認、全体Decision、evidence解決、Promotion、Current Truth、runtime、Final Human GO、Public Beta GOは作成も検証もしません。

## Ideal use

1. content-addressed/protected storeが5成果物とhandoffをimmutableに保持する。
2. reviewer identity・role・authority・independenceを別の信頼できる証拠で検証する。
3. exact `intent_candidate_ref`とHuman Intent ownerを別のgoverned sourceへ束縛する。
4. authorized decision makerが5件の未解決evidenceを評価し、全体outcomeを明示する。
5. Decision instanceがhandoff binding、identity/authority evidence、scope、時刻、expiry、review trigger、retention policyを一つに束縛する。
6. 別のauthorityがDecisionと検証receiptを評価してからPromotionする。

## Current implementation

現在のpublic CLIはlocal filesystemを読み、stdlibだけでdeterministic UTF-8 JSONをstdoutへ返します。外部identity provider、署名、trusted clock、protected store、atomic snapshot、Decision instance作成、Promotionへは接続しません。

builderが確認するのは次です。

- saved bundleがstrict JSONで、現在の22-file Packと`MATCH`
- saved bundle verificationがfresh verifier outputと完全一致
- saved requestが同じbundle/Packからfreshに再生成した結果と完全一致
- saved response verificationがrequest/responseからfreshに再計算した結果と完全一致
- 46件のitem responseが完了し、5件のexternal evidenceが未解決のまま分離
- 5成果物が最初と最後のreadで同じbytes

これは通常のlocal filesystem上のdrift検知であり、敵対的writerに対するatomic snapshotではありません。

## Inputs

順序を変えず、次の6入力をbuilderへ渡します。

1. saved review bundle JSON
2. current Company Pack directory
3. saved bundle verification JSON
4. saved review request JSON
5. saved review response JSON
6. saved response verification JSON

## 1. Build and save without overwriting

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

$HandoffPath = 'work\my-company-review-decision-handoff.json'
$HandoffJson = python tools\build_company_pack_review_decision_handoff.py `
  work\my-company-review-bundle.json `
  work\my-company `
  work\my-company-review-bundle-verification.json `
  work\my-company-review-request.json `
  work\my-company-review-response.json `
  work\my-company-review-response-verification.json
if ($LASTEXITCODE -ne 0) { throw 'decision handoff was refused' }
Write-NewUtf8File -LiteralPath $HandoffPath -Text ($HandoffJson + "`n")
```

Bash (`noclobber`):

```bash
HandoffPath=work/my-company-review-decision-handoff.json
HandoffJson=$(python3 tools/build_company_pack_review_decision_handoff.py \
  work/my-company-review-bundle.json \
  work/my-company \
  work/my-company-review-bundle-verification.json \
  work/my-company-review-request.json \
  work/my-company-review-response.json \
  work/my-company-review-response-verification.json) || exit 1
(set -o noclobber; printf '%s\n' "$HandoffJson" > "$HandoffPath") || {
  printf '%s\n' 'failed to create handoff target without overwriting' >&2
  exit 1
}
```

CLI自体はfileを書きません。既存targetは上書きせず、新しいcandidate名を使います。

| Result | Exit | 意味 |
|---|---:|---|
| `CANDIDATE_DECISION_HANDOFF` | 0 | 5成果物、current Pack、46 response、5 evidence gapが同じcandidateへ束縛された |
| `HANDOFF_BUILD_REFUSED` | 1 | source不正、chain差分、または読み取り中drift |
| usage error | 2 | CLI引数が不正 |

## 2. Verify the saved handoff

PowerShell 7:

```powershell
$VerificationPath = 'work\my-company-review-decision-handoff-verification.json'
$VerificationJson = python tools\verify_company_pack_review_decision_handoff.py `
  work\my-company-review-bundle.json `
  work\my-company `
  work\my-company-review-bundle-verification.json `
  work\my-company-review-request.json `
  work\my-company-review-response.json `
  work\my-company-review-response-verification.json `
  work\my-company-review-decision-handoff.json
if ($LASTEXITCODE -ne 0) { throw 'saved decision handoff did not match' }
Write-NewUtf8File -LiteralPath $VerificationPath -Text ($VerificationJson + "`n")
```

Bash:

```bash
python3 tools/verify_company_pack_review_decision_handoff.py \
  work/my-company-review-bundle.json \
  work/my-company \
  work/my-company-review-bundle-verification.json \
  work/my-company-review-request.json \
  work/my-company-review-response.json \
  work/my-company-review-response-verification.json \
  work/my-company-review-decision-handoff.json
```

`DECISION_HANDOFF_MATCH`は保存handoffと現在の入力鎖の一致だけを示します。Decisionを検証したという意味ではありません。

## 3. Map into a separate Decision Record

starterのgeneric [`decision-record.json`](../examples/company-starter/records/decision-record.json)はRecord **template**であり、実Decision instanceではありません。generic templateをhandoff固有に変更せず、実Decisionを別のgoverned schema/processで作るときに次のように使います。

| Generic field | Human-governed value |
|---|---|
| `decision_id` | 新しいDecisionの一意ID |
| `intent_candidate_ref` | handoffとは別に検証したexact Intent Candidate参照 |
| `decision` | authorized Humanが明示した全体outcome。item countから自動導出しない |
| `approver_role` | identity/authority evidenceと一致するrole |
| `evidence_ref` | saved handoff、handoff verification、5成果物、未解決evidenceへのcontent binding |
| `decided_at` | trust boundaryが定める時刻証拠 |
| `review_condition` | expiry、再review trigger、未解決evidence、candidate drift条件 |

handoff内の`required_fields`は、実運用のDecision instanceでさらに必要なreviewer/decision-maker identity・authority・scope・retentionなど20項目を列挙します。これはgeneric templateや`record.schema.json`が実Decisionを検証済みだという主張ではありません。

特に次はhandoffから推測せず、別証拠を要求します。

- `intent_candidate_ref`
- `reviewer_identity_ref` / `reviewer_authority_ref` / `reviewer_independence_ref`
- `decision_maker_identity_ref` / `decision_maker_authority_ref`
- `reviewed_at` / `decided_at`
- overall `decision` / `selected_outcome` / reason / scope
- unresolved evidence references、expiry、review trigger、retention policy

## Safe refusal and disclosure boundary

各JSONは1 MiB、depth、duplicate key、非finite値をfail closedで制限します。saved report差し替え、Pack drift、handoff tamper、unknown/extra fieldも一致しません。拒否reportは入力path、Pack内のprivate locator、review item、note、hostile値、OS exception本文を反射しません。

成功handoffも個別itemやreviewer noteを複製せず、digest、byte count、集計count、否定claimだけを持ちます。test corpus、credential、token、個人情報、private Human Intent本文を公開handoffへ入れないでください。

## Machine-readable contracts

- [`company-pack-review-decision-handoff.schema.json`](../schemas/company-pack-review-decision-handoff.schema.json)
- [`company-pack-review-decision-handoff-verification.schema.json`](../schemas/company-pack-review-decision-handoff-verification.schema.json)

どちらも`decision: null`、`selected_outcome: null`、全authority/approval/Promotion/runtime/GO claimの`false`、`NO_GO_UNPUBLISHED`を閉じます。

handoffとは別に必要なexact Intent Candidateのschema-only private instance形は[Company Pack Intent Candidate Instance Contract](INTENT-CANDIDATE-INSTANCE.md)で確認できます。Source ref、抽出結果、Human確認entryが埋まってもHuman IntentやDecisionを証明しません。

実Decision instanceへ進む前のfield/claim形だけを確認する次stepは[Company Pack Decision Record Candidate Contract](DECISION-RECORD-CANDIDATE.md)です。現時点ではschema-onlyであり、builder/verifierやHuman Decisionを提供しません。
