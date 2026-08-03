# Company Pack Intent Candidate Instance Contract

Source Evidenceから人間の意図らしき内容を抽出し、R29 Decision Record Candidateへ進める前に必要なfieldと否定claimを固定する**schema-only**契約です。公開するのは契約だけで、実Source、source body、抽出結果、Human確認、builder、verifierは作成しません。

## Ideal use

1. privateなcontent-addressed Evidence Storeが、strict JSONで検証した実Source Recordとsource bytesを同じrevisionへ固定する。
2. 別のauthorityが、sourceごとのaccess/consent scope、subject attribution、保持・削除方針を検証する。
3. boundedなextractorがsourceを命令ではなくuntrusted dataとして扱い、actor/tool/model/prompt template/execution receiptをexact revisionへ固定する。
4. 抽出結果をprivate Intent Candidateへ保存し、このDraft 2020-12 schemaとdate-time format assertionでshapeを検証する。
5. Human Intent ownerがprivate candidateを確認し、本人性、authority、source scope、意図との一致を別の信頼境界で検証する。
6. 検証済みIntent Candidateだけをimmutable bytesへ束縛し、別のDecision processがR29 candidateとHuman Decisionを扱う。

各段階は別receiptを持ちます。source hash、抽出confidence、Human入力欄の文字列、schema PASSだけからHuman IntentやDecisionを導出しません。

## Current implementation

現在公開しているのは[`company-pack-intent-candidate-instance.schema.json`](../schemas/company-pack-intent-candidate-instance.schema.json)、このHuman runbook、実Draft 2020-12 contract testsだけです。既存のSource RecordとIntent Candidate Recordは、実データではなく`required_fields`を示すgeneric templateです。

R30へ渡す前のprivate Source Record shapeは[Company Pack Source Record Instance Contract](SOURCE-RECORD-INSTANCE.md)で確認できます。このschema-only契約もsource authenticity、consent、attribution、retention enforcementを証明しません。

このroundには次がありません。

- populated Source Record instance、strict parser、retriever、verifier
- source locatorやSHA-256の真正性・完全性・current性の検査
- access/consent、subject identity/attribution、retention enforcement
- extraction actor/tool/model/prompt/receiptの真正性検査
- prompt injection、secret、PII、private locatorのcontent-safe verifier
- Human本人性、authority、entry authenticity、trusted clock
- Intent Candidate builder/verifier、R29 Decision builder、外部write、runtime

したがってschema PASSは「このprivate candidateが閉じたshapeに合う」ことだけを示します。Human Intent、Decision、authority、Current Truthを示しません。

## Three candidate states

### `EXTRACTION_REQUIRED`

一つ以上のsource bindingを記録し、まだ抽出していない状態です。`intent_content`、`extraction_provenance`、`human_confirmation`はすべて`null`です。

### `EXTRACTED_UNVERIFIED`

抽出されたpurpose、beneficiary、constraints、success conditions、stop conditions、unresolved itemsとprovenance参照を持つ状態です。contentは常に`UNTRUSTED_INFERENCE`、provenanceは`NOT_VERIFIED`です。Human confirmationはありません。

### `HUMAN_CONFIRMATION_ENTERED_UNVERIFIED`

Human向け入力欄が埋まった形です。選べるのは`confirm_candidate`、`request_changes`、`reject_candidate`だけですが、stateは常に`UNVERIFIED_HUMAN_ENTRY`です。

`confirm_candidate`はUI入力値であり、Human本人性、authority、同意、Intent確認、Decisionを証明しません。確認後もroot statusは`CANDIDATE_ONLY`です。

## Source bindings

`source_bindings`は1〜16件のobjectで、source IDをJSON keyとして重複なく保持します。各bindingは次を分離します。

- Source Recordのgoverned locatorとSHA-256/byte size
- private raw source contentのgoverned locatorと別SHA-256/byte size
- declared media type
- source revision
- editable observed-at
- `source_record_schema_status: NOT_VERIFIED`
- derived-source refsと`lineage_status: NOT_VERIFIED`
- access/consent evidenceのexact binding、declared permitted uses、subject scope、expiry、任意revocation ref、`verification_status: NOT_VERIFIED`
- retention policyのexact binding、retain-until、deletion trigger、任意deletion receipt ref、`enforcement_status: NOT_VERIFIED`

source bodyやexcerptは埋め込めません。locator/hash/sizeが記録されても、参照先の存在、同じbytesの取得、sourceの真正性・完全性、同意・保持の有効性は証明されません。

JSON Schemaは既にparseされたobjectを検証します。duplicate JSON key、非finite JSON、encoding、resource limit、read-driftを閉じるstrict parser/retrieverはfuture verifierの責任です。

## Private content boundary

`content_handling`は次を固定します。

- `source_content_embedded: false`
- `candidate_visibility: PRIVATE_GOVERNED_ONLY`
- `prompt_treatment: UNTRUSTED_DATA_ONLY`
- `disclosure_review_status: NOT_REVIEWED`

公開repositoryへ populated candidateをcommitしないでください。schemaが文字列長と構造を制限しても、candidate textがsecret、個人情報、private locator、著作物、prompt injectionを含まないことは検査できません。成功・拒否・logへprivate textを反射しないfuture implementationが必要です。

`intent_content`は参照source ID、in/out scope、bounded text、redaction policy refと`status: NOT_VERIFIED`を必須にします。JSON Schemaは`source_refs`やprovenanceのinput refsが`source_bindings`のkey全体と一致することを横断検証しません。この一致、derived lineage、redaction実施はfuture verifierがexact bytesへ束縛します。

## Extraction and Human-entry evidence

`extraction_provenance`のactor、tool、tool version、model、config、prompt template、execution receiptはopaque refです。input source ID群とoutput bindingも持ちますが、schemaは実行や対応関係を再計算しません。raw promptとraw model outputはclosed objectへ格納できません。`extracted_at`はRFC 3339 date-time形式ですがtrusted clockではなく、`verification_status`は常に`NOT_VERIFIED`です。

`human_confirmation`のidentity/authority/entry evidenceもopaque refです。`entered_at`のformat PASSは本人性、authority、freshnessの証明ではありません。抽出item数、confidence、多数決、`confirm_candidate`文字列からDecisionやexecution authorityを作れません。

## Generic Intent Candidate Record mapping

既存の[`intent-candidate.json`](../examples/company-starter/records/intent-candidate.json)は九つのrequired fieldを列挙するgeneric Intent Candidate Record templateです。このR30 schemaはtemplateや[`record.schema.json`](../schemas/record.schema.json)を書き換えず、具体candidateの追加安全fieldを別契約にします。

| Generic field | R30 private candidate source |
|---|---|
| `intent_id` | `intent_candidate_id`。governed adoption時はregistry uniquenessが必要 |
| `source_refs` | `source_bindings`。現在はschema/current/authenticity未検証 |
| `purpose` | `intent_content.purpose`。現在はuntrusted inference |
| `beneficiary` | `intent_content.beneficiary`。現在はuntrusted inference |
| `constraints` | `intent_content.constraints` |
| `success_conditions` | `intent_content.success_conditions` |
| `stop_conditions` | `intent_content.stop_conditions` |
| `unresolved_items` | `intent_content.unresolved_items` |
| `revision` | `candidate_revision`。anti-replay registryは未実装 |

このmappingをコピーしてもHuman Intent、Decision、Promotion、Current Truthにはなりません。R29の`intent_candidate_binding.schema_status`も、実verifierができるまで`NOT_VERIFIED`のままです。

## Review trigger and expiry

Source Record digest、raw content digest、source set/lineage、access/consent scope/revocation、retention deadline、extraction provenance、redaction、intent content/scope、unresolved items、Human confirmation、candidate revision/replay conflict、candidate/authority expiryを固定12 triggerとして列挙します。`candidate_recorded_at`と`expires_at`はformat-check済みのeditable値であり、trusted timeや現在性を証明しません。

## Claims and future gate

37 claimはすべて`false`固定です。Source Record schema/bytes、raw content bytes、authenticity/completeness/lineage、access/consent、retention、subject identity/attribution、extraction provenance、prompt-injection clearance、redaction/sensitive-content review、Human confirmation、Human Intent、candidate ID uniqueness/replay、Decision、execution/Work Order authority、Promotion、Current Truth、runtime、Voice、Discord、provider/external transfer、Final Human GO、Public Beta GOのどれも成立しません。

unknown fieldは拒否され、`confirmed`、`approved`、`verified`、`decision`、`effective_at`、`execution_authority`、`promotion`、`current_truth`は追加できません。Public Betaは`NO_GO_UNPUBLISHED`です。

builder/verifierを追加する前に、real Source Record instance、immutable retrieval、strict parsing、consent/retention、subject attribution、extractor provenance、content safety、Human identity/authority/authenticity、trusted time、cross-candidate substitution/replay、private-output non-reflectionを別contractとevidenceで閉じます。
