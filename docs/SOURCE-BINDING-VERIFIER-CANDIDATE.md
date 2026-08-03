# Source Binding Verification Candidate

R32は、保存済みR31 Source Record、別保存のSource Content、R30 access
projection用evidenceを一回の限定evaluationで照合する、標準ライブラリだけの
read-only CLIです。

これはprotected verifierでもVerification Receiptでもありません。`status`は常に
`CANDIDATE_ONLY`で、成功`result`だけが
`SOURCE_BINDING_MATCH_POINT_IN_TIME`です。strict parse、宣言digest/size、
lossless mapping、二回のcomplete terminal rereadが一致したことだけを示します。
Source authenticity、consent/access authority、retention enforcement、Human Intent、
runtime、Promotion、Current Truth、Final Human GO、Public Beta GOは証明しません。

## Ideal use

将来のprotected runnerは、transactionalなprivate Evidence StoreからR31 record、
Source Content、aggregate access evidenceを同じsnapshotで取得し、trusted clock、
署名/trust root、replay control、retention/deletion controlと合わせて検証します。
その後にだけ、privateなR30 source binding artifactを保存し、独立した
Verification Receiptへ束縛します。

## Current implementation

現在のCLIはlocal filesをno-link bounded readerで読み、exact terminal rereadを
二回行います。これは`Stable Source Read Set`であり、storage transactionによる
atomic snapshotではありません。したがって成功時も
`atomic_multi_file_snapshot_verified`と`full_r31_schema_verified`は`false`です。
成功時も`read_set_status: STABLE_POSTCHECK_UNVERIFIED`、
`r30_projection_eligibility: ELIGIBLE_UNVERIFIED`であり、`VERIFIED`、`CURRENT`、
`ATOMIC`とは表現しません。

full R31 Draft 2020-12 schemaはtest suiteが実validatorで検証します。CLIは
projectionに必要なclosed shapeとcross-fieldだけを標準ライブラリで検査し、
`source_record_schema_status: NOT_VERIFIED`のままmemory内projectionを作ります。

## Inputs

1. R31 Source Record JSON。最大1 MiB。
2. 別保存のSource Content file。最大16 MiB。
3. `company_pack_source_access_projection_evidence` JSON。最大1 MiB。
4. serialized R31 bytesを指すgoverned `ref/...` locator。
5. access projection evidenceを指すgoverned `ref/...` locator。

二つのlocatorはsyntaxだけを確認します。private file pathからlocatorを生成せず、
locatorのresolution/currentness/authorityも検証しません。

実Source Record、Source Content、物理path、credential、Discord dataをpublic repo、
Issue、PR、test fixture、review promptへ置かないでください。

access projection evidenceは、R31 record/contentのexact file binding、record IDの
digest、共通purpose、permitted-use集合、subject、expiry、revocation view、basis、
各use evidence bindingを束縛します。これはlossless mapping用のcandidateであり、
宣言した人物のidentityやauthority、consentの有効性を証明しません。

## Run

```powershell
python tools/verify_company_pack_source_binding_candidate.py `
  <private-record.json> `
  <private-content.bin> `
  <private-access-evidence.json> `
  ref/source-record/serialized `
  ref/access-consent/aggregate
```

CLIはfileを作成・更新しません。stdoutへdeterministic JSONを一行だけ出します。
matchはexit `0`、evaluated refusalはexit `1`、usage errorはexit `2`です。

## Strict input contract

- UTF-8のみ。BOM、invalid UTF-8、surrogateを拒否します。
- duplicate key、non-finite JSON、top-level non-object、depth 32超、20,000 node超を
  拒否します。
- booleanをinteger binding sizeとして受け入れません。
- symlink、junction、reparse component、non-regular file、size/identity change、
  truncation、over-limit、TOCTOU、late driftをfail closedにします。
- R31 reference-only、root/per-use withdrawal、contentなし、permitted useなし、
  purpose/subject/expiry/revocation不一致、revision不一致、retention coverage不足、
  lineage矛盾をR30 projection不適格として拒否します。
- evidenceのrecord/content binding、record-ID digest、use集合、common scope、basis、
  per-use evidence bindingが一つでも不一致なら拒否します。

## Non-reflective refusal

invalid inputは固定`reason_codes`と固定check名だけで説明します。入力本文、Source
Content、物理path、locator、record ID、unknown key、例外文をstdout/stderrへ返しません。
安全に読み終えた三入力はSHA-256/byte sizeだけを返します。

成功時もprivateなR30 projection自体は出力しません。memory内でcanonical化した
projectionのSHA-256/byte sizeだけを`r30_projection_digest_candidate`へ返します。
このdigestはR30 artifact、adoption、access permission、Intent verificationでは
ありません。

## R30 mapping

memory内projectionはR30 `source_binding`のrequired fieldsをすべて使います。
record/content locatorとbinding、media type、revision、observed time、lineage、
aggregate access evidence、retentionを明示的に組み立てます。status fieldはすべて
`NOT_VERIFIED`です。R31 objectの再利用や、basis bindingの無条件copyはしません。

## Claims boundary

成功時にtrueになり得るのは、strict parsing、projection-relevant R31 contract、
record/content/evidence binding、R30 projection digest計算、terminal rereadだけです。

full R31 schema、atomic snapshot、source authenticity/completeness/lineage、identity/
attribution、access/consent authority、revocation authority、retention/deletion/redaction、
trusted time、replay、Human Intent/Decision/Work Order authority、Voice/Discord/provider/
external transfer/runtime、Promotion、Current Truth、Final Human GO、Public Beta GOは
常にfalseです。Public Betaは`NO_GO_UNPUBLISHED`です。

## Rollback and next gate

このroundのrollbackはR32 commitのrevertです。CLIは外部状態を変更しません。
次段のprotected runnerにはprivate transactional snapshot、trusted clock、signed
trust root、replay reservation、retention/deletion receipt、rollback drill、real
owner-scoped evidenceが必要です。それらをlocal candidate matchで代用しません。
