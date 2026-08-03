# Company Pack Source Record Instance Contract

Source ItemをprivateなSource Record候補へ記述し、R30 Intent Candidate
Instanceへ渡す前に必要なfieldと否定claimを固定する**schema-only**契約です。
公開するのは契約だけで、実Source、content、transcript、audio、capture、
attribution、builder、verifierは作成しません。

## Ideal use

1. protected Evidence Storeがpurpose/useごとのaccessまたはconsentを確認してから
   Source Itemを取得し、取得前後のrevisionとbytesをatomicに固定する。
2. strict parserがduplicate key、non-finite number、depth/size上限、BOMを含む
   UTF-8、surrogate、media mismatchをfail-closedで検査し、raw contentや
   private locatorをerror/receiptへ出さないnon-reflectionを保証する。
3. 独立authorityがorigin、completeness、lineage、subject/speaker/channel/
   session attribution、consent scope、retention/deletion、redaction、
   trusted timeを別evidenceから検証する。
4. protected verifierがSource Record serialized bytesとcontent bytesを同じ
   snapshotへ束縛し、外部bindingとしてR30へ渡す。

## Current implementation

現在公開しているのは
[`company-pack-source-record-instance.schema.json`](../schemas/company-pack-source-record-instance.schema.json)、
このHuman runbook、実Draft 2020-12 contract testsだけです。既存の
[`source-record.json`](../examples/company-starter/records/source-record.json)は
実instanceではなくrequired field名を示すgeneric templateです。

このroundには次がありません。

- capture、retriever、strict parser、builder、verifier、protected store
- real source、audio、transcript、excerpt、prompt、model output、private ID
- locator resolution、atomic before/after read、byte currentness
- source authenticity/completeness、media/encoding、lineage
- subject/speaker/channel/session identityまたはattribution
- access/consent authenticity、revocation、retention/deletion enforcement
- trusted clock、record ID uniqueness、replay prevention
- Intent extraction、Human Intent、Decision、Work Order authority
- runtime、Voice、Discord、provider、deployment、Promotion、Current Truth、GO

## Candidate states

- `REFERENCE_DECLARED_UNVERIFIED`: governed locator、source kind/revision/time、
  policy declarationのshapeだけを記録する。`acquisition_mode: reference`で
  contentとacquisition provenanceは`null`。
- `CONTENT_BINDING_RECORDED_UNVERIFIED`: capture/import/syntheticによるprivate
  content locator、SHA-256/byte size、declared media/encoding/revision/timeと
  acquisition refsを入力したが、current bytesやoriginは未検証。
- `DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED`: parent Source Record、
  transformation、任意segmentationを宣言したderived content候補。lineageは
  `DECLARED_DERIVED`だが未検証。
- `WITHDRAWAL_RECORDED_UNVERIFIED`: useの一つにwithdrawal evidence refを
  入力しただけで、取消の真正性、削除、保持停止を証明しない。

attributionはcontent lifecycleのstateにしません。nullableな
`attribution_candidate`として独立し、どのstateでも入力だけでは本人性や
authorityを作りません。全stateのroot statusは`CANDIDATE_ONLY`です。

## Source and content boundary

rootは`source_item_kind`、governed `source_locator_ref`、
`source_revision`、editable `source_observed_at`を分離します。refは
`ref/...`形式に限定し、Windows absolute path、`file://`、raw URLやprivate
machine locatorを構造的に拒否します。

`content_observation`は次のmetadataだけを持ちます。

- private content storage locator ref
- SHA-256とbyte size
- strict `type/subtype`形のdeclared media type
- encoding ref、source revision、editable observed time
- `observation_status: NOT_VERIFIED`

source body、excerpt、transcript、audio、prompt、model outputは埋め込みません。
SHA-256/sizeが一致してもauthenticity、completeness、freshness、media、
encoding、同じretrieval snapshotを証明しません。

## Acquisition and lineage

`acquisition_mode`は`reference`, `capture`, `import`, `derived`,
`synthetic`を区別します。`acquisition_provenance`はactor、tool/version、
config、runtime、execution receipt、input locator、output binding、
started/completed timeのopaque ref/metadataだけを持ち、
`verification_status: NOT_VERIFIED`です。

`lineage`は`DECLARED_ORIGINAL`または`DECLARED_DERIVED`を明示し、derived
stateではparent Source Recordとtransformationを最低1件要求します。これは
lineage authenticityや同じcontentを証明しません。

## Attribution candidate

`subject_refs`, `speaker_refs`, `channel_refs`, `session_refs`を別配列へ
置き、表示名や公開IDを直接格納しません。入力者、identity evidence、
authority evidence、entry evidenceはそれぞれrefとbindingを持ちますが、全て
`NOT_VERIFIED`です。attribution entry、Human identity、Human authority、
Human confirmation authenticityのclaimもfalseです。

## Access or consent declarations

`access_or_consent.use_declarations`は`capture`, `read`, `analyze`,
`store`, `transfer`, `reuse`を閉じた6 fieldとして分離します。各useは
独自のevidence binding、purpose scope、subject scope、expiry、revocation ref、
verification statusを持ちます。

`capture`は全Sourceに必須のpermissionではありません。imported sourceは
captureを`DECLARED_NOT_PERMITTED`のままread/analyze/storeを個別宣言でき、
derived/syntheticもacquisition modeに応じて分けます。
`DECLARED_PERMITTED_UNVERIFIED`もauthorizationではなく、全useの
authorization claimはfalseです。

## Retention, redaction, and deletion

`retention.covered_artifacts`はSource Record serialized bytes、Source Content
bytes、storage metadataを別々に列挙します。policy binding、retain-until、
expiry/withdrawal trigger、任意deletion receipt refがあっても保持や削除を
証明せず、`enforcement_status: NOT_VERIFIED`です。

`redaction`もpolicy bindingとcovered artifactsを持ちますが、
`verification_status: NOT_VERIFIED`です。private candidateであることは、
sensitive content reviewやredaction完了を意味しません。

## R30 mapping

R31自身にself-hashは持たせません。self-hashをrecord内へ入れるとserialized
record bytesが変化して循環するためです。`r30_binding_handoff`は
`serialized_record_locator: null`, `serialized_record_binding: null`,
`EXTERNAL_BINDING_REQUIRED`, `NOT_VERIFIED`に固定します。

future verifierがR31を外部保存した後、保存済みR31 serialized bytesのlocator、
SHA-256、byte sizeをR30の`source_record_locator/source_record_binding`へ、
R31 content observationのstorage locator/bindingをR30の
`source_content_locator/source_content_binding`へ写します。schemaはこの
mapping、同一snapshot、currentnessを検証しません。

## generic template mapping

generic `source-record.json`のfield名との対応は次です。

- `source_id` → `source_record_id`
- `source_locator_ref` → `source_locator_ref`
- `observed_at` → `source_observed_at`
- `digest_sha256` → `content_observation.content_binding.sha256`
- `access_or_consent_ref` → `access_or_consent.basis_ref`
- `retention_policy_ref` → `retention.policy_ref`

これはfield mappingであり、generic template、R31 instance、content bytes、
R30 bindingのauthenticityや同一性を証明しません。

## Private content handling

全candidateは`PRIVATE_GOVERNED_ONLY`、`source_content_embedded: false`、
`prompt_treatment: UNTRUSTED_DATA_ONLY`、
`disclosure_review_status: NOT_REVIEWED`です。実instanceをpublic repository、
Issue、PR、log、test fixture、review promptへ置きません。

## Review trigger and expiry

source locator/kind/revision、content digest/size/observation、media/encoding、
acquisition mode/provenance、lineage、attribution、use/scope/revocation、
retention scope/deletion、redaction、record revision/R30 binding/replay、
private storage/parser/retrieval policy、candidate/authority expiryを固定12
triggerとして列挙します。時刻はformat-check済みのeditable値であり、trusted
timeや正しい順序を証明しません。

## Claims and future verifier

57 claimはすべて`false`固定です。locator、kind、revision、record schema/
bytes/external binding、content bytes、authenticity/completeness/lineage/
media/encoding、acquisition、identity/attribution、各use authorization、
revocation、retention/deletion/redaction、uniqueness/replay、Human identity/
authority/confirmation/Intent、Decision、execution/Work Order authority、
Promotion、Current Truth、runtime、Voice、Discord、provider/external transfer、
Final Human GO、Public Beta GOのどれも成立しません。

schemaはunknown fieldやphysical locator、malformed media typeを拒否します。
一方、output binding mismatch、time ordering、record/content revision mismatch、
unbound lineage/revocation/deletion ref、source/content/candidate substitution、
atomic retrieval、strict JSON/UTF-8/resource limits、ID uniquenessは実行しません。
duplicate key、non-finite、depth、size、UTF-8/BOM、surrogate、bool-int、
symlink/junction/reparse point、TOCTOU、late drift、truncation、secret/PII
non-reflectionを閉じるfuture verifierとprotected evidenceができるまで、R30
Intent builder/verifierを追加しません。Public Betaは
`NO_GO_UNPUBLISHED`です。
