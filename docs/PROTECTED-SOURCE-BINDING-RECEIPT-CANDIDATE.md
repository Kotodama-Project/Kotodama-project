# Protected Source Binding Receipt Candidate

R33は、将来の**protected runner**がR32のlocal point-in-time candidateから先へ
進むときに残すprivate receiptの、閉じた**schema-only**契約です。公開するのは
field、否定claim、Human runbook、contract testsだけです。実Source Record、Source
Content、audio、transcript、private R30 projection、consent evidence、deletion receipt、
署名、nonce、populated receiptは公開しません。

構造PASSは、runner、evidence、時刻、snapshot、署名、削除、replay防止の真正性を
検証しません。receiptは常に`CANDIDATE_ONLY`、
`PROTECTED_RECEIPT_RECORDED_UNVERIFIED`、`PRIVATE_GOVERNED_ONLY`です。参照された
evidenceは`RECORDED_UNVERIFIED`、各検証statusは`NOT_VERIFIED`、Public Betaは
`NO_GO_UNPUBLISHED`です。

## Ideal use

将来のprotected runnerは、同一transactional snapshotからR31 Source Record、Source
Content、aggregate access evidenceを取得し、次を一つのprivate evidence chainへ
束縛します。

1. exact runner policy、binary、configuration、execution environment
2. adopted trusted clock policy、evaluation time、skew evidence
3. atomic private snapshotのtransaction、isolation policy、3 artifact binding
4. governed locatorからimmutable versionへのresolution receipt
5. source authenticity、completeness、lineage、identity/attribution、
   access/consent/revocation、retention policy evidence
6. bound store内のatomic replay reservation
7. retention deadline、withdrawal、実削除後のdeletion receipt
8. R32 result、非公開R30 projection digest、detached attestation
9. receipt保存後に別工程で作るserialized receiptの外部binding

独立verifierはその後、raw evidenceをprivate trust boundary内で読み、cross-binding、
time ordering、signature/trust root、snapshot atomicity、nonce uniqueness、retentionと
deletion receiptを再検証します。そのverified resultとcandidate-bound Human
Decisionが揃うまで、Intent、Work Order、Promotion、Current Truthへ進めません。

## Current implementation

現在公開しているのは
[`company-pack-protected-source-binding-receipt-candidate.schema.json`](../schemas/company-pack-protected-source-binding-receipt-candidate.schema.json)、
このrunbook、実Draft 2020-12 contract tests、Company Packからの導線だけです。
builder、runner、retriever、signature verifier、trusted clock connector、nonce store、
deletion worker、protected evidence store、populated receiptはありません。

R32の[Source Binding Verification Candidate](SOURCE-BINDING-VERIFIER-CANDIDATE.md)は
local fileをstrictに読み、terminal rereadを二回行うread-only CLIです。R33 schemaは
R32 result bytesとverifier bytesを参照できますが、それらを再実行も検証もしません。
`r32_candidate_result_verified`は常に`false`です。

## Private receipt shape

### R32 contract

`public_revision`、verifier/result binding、reported result、非公開R30 projection
digest candidateを分離します。reported resultが`REFUSED`ならprojection digestは
必ず`null`です。`SOURCE_BINDING_MATCH_POINT_IN_TIME`でも`verification_status`は
`NOT_VERIFIED`です。

### Runner and trusted clock

runner identity/policy/binary/config/environmentはopaque `ref/...`とdigest/sizeだけを
保持します。evaluation clockもsource/policy/time/maximum skew/evidenceを分離します。
schemaはdate-timeとskewのshapeを検査しますが、clockをtrustedにしません。

### Atomic private snapshot

snapshot transaction、isolation policy、opened/sealed time、R31 record、Source
Content、access evidenceの3 binding、snapshot receiptを必須にします。これはatomic
snapshotを**報告するshape**であり、transaction実行や3 bindingの同一snapshot性を
検証しません。

### Locator resolution

`source_record`と`access_projection_evidence`を固定順序で別々に記録します。各要素は
governed locator、immutable version、resolved binding、resolver policy、resolution
receiptを持ちます。物理path、`file:` URI、credential、private hostnameはreceiptへ
入れず、protected store内のopaque refだけを使います。

### Evidence roles

次の6 roleを欠落なく分離します。

- source authenticity
- source completeness
- source lineage
- identity / attribution
- access / consent / revocation
- retention policy

各roleの`RECORDED_UNVERIFIED`は参照とbindingが記録されたという宣言だけです。
evidence body、participant identity、consent本文、audio、transcriptを公開schemaやtest
fixtureへ埋め込みません。

### Replay, retention, and deletion receipt

replay reservationはnonce digest、bound store、reservation receipt、reserved timeを
分離します。schema validationはatomic reservation、store continuity、nonce uniquenessを
証明しません。

retentionは4 artifactのcoverage、policy、deadline、`expiry_or_withdrawal` triggerを
固定します。`NOT_DUE_REPORTED_UNVERIFIED`または`DUE_REPORTED_UNVERIFIED`ではdeletion
receiptを`null`にし、`RECEIPT_RECORDED_UNVERIFIED`だけがreceipt refとbindingを必須に
します。どの状態でも削除実行、scope、deadline、receipt authenticityは未検証です。

### Detached attestation and post-save binding

detached attestationはpayload、signer identity/policy、signatureのbindingを分離します。
schemaはsignatureを検証しません。receipt自身のserialized bytesは自己digestを避ける
ため常に`EXTERNAL_BINDING_REQUIRED`です。保存後の別工程がlocatorとbindingを作り、
別verifierがこのcandidateへ束縛する必要があります。

## What contract tests reject

- authority/runtime/GO claimを一つでも`true`にするoverclaim
- `VERIFIED`、`approved`、`PUBLIC`等の昇格alias
- raw source、audio、transcript、private projectionの埋め込み
- invalid timestamp、boolean byte size、physical path形式のref
- snapshot artifact、evidence role、replay receiptの欠落
- locator roleの重複・reorder
- deletion statusとreceipt ref/bindingの不整合
- R32 refusalにprojection digestを残すshape
- review triggerの欠落・追加・reorder
- unknown fieldとself-binding attempt

schemaだけではopened/sealed/evaluation/recorded/expiryの時系列、重複ref、cross-binding、
runner/policy/evidence currentness、signature、transaction、deletionを検証できません。
future protected verifierはそれらをfail closedにし、入力値やprivate locatorをerrorへ
反射しない必要があります。

## Claims boundary

全33 claimは常に`false`です。protected execution、runner identity/binary/config、
detached attestation、trusted clock、atomic snapshot、locator resolution、immutable
version、authenticity/completeness/lineage、identity/attribution、consent/revocation、
retention/deletion、replay、R32 result、R30 projection、Human Intent/Decision、Work
Order authority、Voice/Discord/provider/external transfer、Promotion、Current Truth、
Final Human GO、Public Beta GOをschema PASSから導出しません。

## Rollback and next gate

このroundのrollbackはR33 commitのrevertです。schema/test/docsは外部状態を変更しません。
次段はprivate fixtureを公開することではなく、protected environmentで動くstrict
verifierのTDD契約です。exact runtime Work Order、trusted clock/trust root、atomic
snapshot implementation、nonce store、retention/deletion executor、independent receipt
verificationが揃うまで、populated receiptやreal sourceを生成・公開しません。
