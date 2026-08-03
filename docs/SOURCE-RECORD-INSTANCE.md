# Company Pack Source Record Instance Contract

Source ItemをprivateなSource Record候補へ記述し、R30 Intent Candidate
Instanceへ渡す前に必要なfieldと否定claimを固定する**schema-only**契約です。
このschemaが公開するのは契約だけで、実Source、content、transcript、audio、
capture、attribution、builderは作成しません。保存済みsynthetic/private bytesの
限定照合は別の[Source Binding Verification Candidate](SOURCE-BINDING-VERIFIER-CANDIDATE.md)が扱います。

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
このHuman runbook、実Draft 2020-12 contract testsに加え、別契約として
strict/local/read-onlyな[Source Binding Verification Candidate](SOURCE-BINDING-VERIFIER-CANDIDATE.md)です。既存の
[`source-record.json`](../examples/company-starter/records/source-record.json)は
実instanceではなくrequired field名を示すgeneric templateです。

R32 candidateはprojectionに必要なR31/access evidenceのclosed subset、exact raw
bytes、content digest/size、terminal rereadを照合します。ただしreportは常に
`CANDIDATE_ONLY`で、full R31 schemaとatomic multi-file snapshotをclaimしません。

現在も次がありません。

- capture、protected retriever/verifier、builder、protected store
- real source、audio、transcript、excerpt、prompt、model output、private ID
- locator resolution、transactional atomic snapshot、post-return currentness
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
- `WITHDRAWAL_RECORDED_UNVERIFIED`: content-bound source onlyのstate。
  `content_observation`と`acquisition_provenance`を保持したSourceで、useの一つに
  withdrawal evidence refを入力した形だけを許す。locator-only referenceをこの
  stateへ変更することはできず、取消の真正性、削除、保持停止も証明しない。

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

R32 candidateまたは将来のprotected verifierがR31を外部保存した後、次のfield
mappingを構築します。R32は`Stable Source Read Set`から非公開projection digest
だけを作り、atomic snapshotをclaimしません。これはprojection, not object reuseです。

projection eligibilityはfail closedです。`REFERENCE_DECLARED_UNVERIFIED` cannot be projected
because `content_observation` is absent while R30 requires content locator、binding、media
type、observed-at。`CONTENT_BINDING_RECORDED_UNVERIFIED`と
`DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED`だけが次の条件付きprojection候補です。
any `WITHDRAWAL_ENTERED_UNVERIFIED` in the six use declarations、またはroot
`WITHDRAWAL_RECORDED_UNVERIFIED`があれば、R30はper-use withdrawalをlosslessに
表せないためprojectionを拒否します。

R30 containerはR31 `source_record_id`をkeyにした
`source_bindings[source_record_id]`として作ります。R30 `intent_content.source_refs`と
`extraction_provenance.input_binding_refs`が存在するstateでは、そのkey集合も同じ
Source Record集合へ一致させます。key不一致、欠落、別recordへのaliasはfail closedです。

| R30 required field | R31 input / fail-closed rule |
| --- | --- |
| `source_record_locator` | 保存済みR31 serialized bytesの外部governed locator。R31自身には書き戻さない |
| `source_record_binding` | 保存済みR31 serialized bytesを保存後に計算したSHA-256とbyte size |
| `source_content_locator` | `content_observation.storage_locator_ref` |
| `source_content_binding` | `content_observation.content_binding` |
| `declared_media_type` | `content_observation.declared_media_type` |
| `source_revision` | root `source_revision`と`content_observation.declared_source_revision`が一致するときだけ、その値を写す。不一致はfail closed |
| `observed_at` | bytes bindingの観測時刻として`content_observation.observed_at`を写す。root `source_observed_at`はSource Item観測として別に保持し、time orderingは別途検証する |
| `source_record_schema_status` | 常に`NOT_VERIFIED`。R31 schema PASSをsource/currentness verificationへ昇格しない |
| `derived_from_refs` | `lineage.lineage_kind`が`DECLARED_ORIGINAL`なら空配列、`DECLARED_DERIVED`なら`lineage.parent_source_record_refs`。状態と配列が矛盾すればfail closed |
| `lineage_status` | 常に`NOT_VERIFIED` |
| `access_or_consent` | 下記の明示projectionを作る。R31 objectをそのまま再利用しない |
| `retention` | 下記の明示projectionを作る。R31 objectをそのまま再利用しない |

R30 `access_or_consent`は、statusが`DECLARED_PERMITTED_UNVERIFIED`のuse名だけから
`declared_permitted_uses`を作ります。all projected permitted usesの
`purpose_scope_ref`、`subject_scope_ref`、`scope_expires_at`、
`revocation_evidence_ref`がそれぞれ同一の場合だけprojection候補にできます。
一つでも異なる場合、permitted useが空の場合、またはany
`WITHDRAWAL_ENTERED_UNVERIFIED`がある場合は、単一のR30 shapeではlosslessに
表せないためfail closedです。

R30には`purpose_scope_ref` fieldがないため、R32 candidateまたはfuture verifierは共通purpose、
permitted uses、subject、expiry、revocation、R31 basisと各use evidenceのexact
bindingsを一つのgoverned aggregate evidence artifactへ束縛し、そのartifactの
locator/bindingだけをR30 `evidence_ref/evidence_binding`へ入れます。R31
`access_or_consent.basis_ref/basis_binding`を無条件にcopyしてはいけません。
aggregate artifactが無い、全入力bytesを同じsnapshotで検証できない、または
projection後にpurposeを再確認できない場合はfail closedです。R30
`verification_status`は常に`NOT_VERIFIED`です。

R30 `retention`はR31の`policy_ref`、`policy_binding`、`retain_until`、
`deletion_trigger`、`deletion_receipt_ref`を個別に写し、
`enforcement_status`を常に`NOT_VERIFIED`にします。R30には
`covered_artifacts` fieldがないため、R31側が少なくとも
`source_record_serialized_bytes`と`source_content_bytes`の両方をcoverしない場合は
projectionをfail closedにします。

schemaはこのmapping、同一snapshot、cross-field一致、currentness、projectionの
losslessnessを検証しません。

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

## Claims and verifier boundary

57 claimはすべて`false`固定です。locator、kind、revision、record schema/
bytes/external binding、content bytes、authenticity/completeness/lineage/
media/encoding、acquisition、identity/attribution、各use authorization、
revocation、retention/deletion/redaction、uniqueness/replay、Human identity/
authority/confirmation/Intent、Decision、execution/Work Order authority、
Promotion、Current Truth、runtime、Voice、Discord、provider/external transfer、
Final Human GO、Public Beta GOのどれも成立しません。

schemaはunknown fieldやphysical locator、malformed media typeを拒否しますが、
bytesを読みません。R32 candidateはprojection-relevant subsetについてoutput
binding、time ordering、record/content revision、lineage、source/content/evidence
substitution、strict JSON/UTF-8/resource limits、観測できるsymlink/junction/
reparse point、identity/byte late drift、truncation、non-reflectionを追加検査します。
具体的には、schema単体が許すoutput binding mismatch、time ordering、
record/content revision mismatchをcandidate refusalへ変えます。

それでもresidual component race、cross-file atomic retrieval、post-return currentness、full R31 schema、
locator resolution、origin/authenticity/completeness、consent/revocation authority、
retention/deletion/redaction enforcement、ID uniqueness/replay、trusted timeは検証
しません。protected evidenceがこれらを閉じるまでR30 Intent builder/verifierを
追加しません。Public Betaは`NO_GO_UNPUBLISHED`です。
