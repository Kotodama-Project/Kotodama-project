# Project Status

Updated: 2026-08-04

| Surface | Status |
|---|---|
| Public repository | Published preview |
| Product direction and roadmap | Public |
| Company governance starter | Published and locally validated |
| Compose / Proxmox lifecycle contract | Published and locally validated |
| Compose minimum data-plane skeleton | Published candidate; offline config only |
| Resolved Compose candidate | Published credential-free configuration candidate |
| Local image availability preflight | Published read-only tool; saved verification is historical binding only |
| Clean-install / migration evidence candidate | Published unattested saved-binding contract; no live receipt |
| Protected one-use attestation evaluation | Published local candidate; atomic only within one bound SQLite store |
| Signed nonce-store checkpoint | Published protected-local tool; point-in-time and immediate-parent only |
| Recursive nonce-store checkpoint chain | Published protected-local candidate; supplied path/store equivalence only |
| Checkpoint-head anchor / restore-drill evidence | Published protected-local contract; signed reported binding only |
| Checkpoint segment transition / key rotation | Published protected-local contract; one presented boundary only |
| Segment transition candidate builder | Published protected-local CLI; deterministic new-file creation only, unsigned and unverified |
| [Source binding verification candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) | Included in this revision as a read-only local candidate; stable postcheck and R30 projection digest only |
| [Protected Source binding receipt candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md) | Included as an unpopulated schema-only private receipt contract; no protected runner or verified receipt |
| [Protected execution request / handoff candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) | Included as an opaque schema-only request shape; no execution accepted, executed, or private handoff |
| [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) | Included as a read-only aggregate of starter validator, Catalog, customization, and false-claim checks |
| [Compose candidate runbooks](docs/RESOLVED-COMPOSE-CANDIDATE.md) | Published read-only candidate guidance with PowerShell/POSIX parity; no live image or runtime receipt |
| [Image availability preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md) | Published read-only historical-binding guidance with PowerShell/POSIX parity; current-host availability remains unverified |
| [Company Pack review bundle](docs/REVIEW-BUNDLE.md) | Published candidate-only exact-byte binding and drift verifier; no approval or Promotion |
| [Company Pack Review Request](docs/REVIEW-REQUEST.md) | Published read-only request candidate; counts follow the saved Pack report |
| [Company Pack Review Response](docs/REVIEW-RESPONSE.md) | Published read-only response candidate; saved-request binding and item counts are dynamic |
| [Company Pack Decision Handoff](docs/REVIEW-DECISION-HANDOFF.md) | Published read-only handoff candidate; decision and selected outcome remain null |
| [Template Guide / Starter Walkthrough](docs/TEMPLATE-GUIDE.md) | Published ideal/current usage docs; starter counts are examples, not universal Pack invariants |
| Live Compose / Proxmox installation | Not verified |
| Public Beta access | Not open |
| Public Discord invite | Not published |
| Public Voice Bot | Inactive |
| Raw audio or transcript corpus | Not published |
| Final Human GO | Not completed |

## Latest runtime result

最新の CT200 Voice cutover attempt は、read-only reconciliation 後に `BLOCKED_NO_EFFECT` と判定されました。候補ファイルの deploy は 0、外部 provider API の作用も 0 でした。

これは安全に停止したことの証拠であり、Voice runtime が公開稼働していることの証明ではありません。

## Latest public template result

R130 is the current public Company Pack Next Steps entry-navigation revision
and the latest Template/Company/Blocks/Records/MOCs/starter navigation surface
at public `main` commit `1667007004f92ac65e0124355fda9b71d81d7e6b`, tree
`aebd38c2012b745333e66348232dc88804181b65`. R130 adds a stable
ideal/current/smoke first-stop in
[`docs/COMPANY-PACK-NEXT-STEPS.md`](docs/COMPANY-PACK-NEXT-STEPS.md), covered by
[`test_company_pack_next_steps_entry_navigation.py`](tests/test_company_pack_next_steps_entry_navigation.py),
linking the ideal Company Template, Blocks, Governed Records, and MOCs layers
to the current Company Pack Catalog / Starter Walkthrough and the planner
schema/regression smoke path. R130 is documentation/static-regression evidence
only; the published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`. R129 remains historical as the STATUS/ROADMAP provenance
synchronization to R128 at public `main` commit
`4d29fca3f8005c9758b78889adab04b2f9614512`, tree
`a178210e7356108a020edd7b9784e24735250105`. R128 remains historical as the
Company Pack Catalog entry-navigation revision at public `main` commit
`752fa4b46246110757f01294b559c39412a0b4be`, tree
`60ee3062bcd472562e01f03708cb1fd58c32f7f7`. R128 adds a stable
ideal/current/smoke first-stop in
[`docs/COMPANY-PACK-CATALOG.md`](docs/COMPANY-PACK-CATALOG.md), covered by
[`test_company_pack_catalog_entry_navigation.py`](tests/test_company_pack_catalog_entry_navigation.py),
linking the ideal Company Template, Blocks, Governed Records, and MOCs layers
to the current Company starter/Catalog and the Matrix/Walkthrough/regression
smoke path. R128 is documentation/static-regression evidence only; the
published surface remains read-only/candidate-only and `NO_GO_UNPUBLISHED`.
R127 remains historical as the MOC entry-navigation revision at public `main`
commit `b05db80ec979129d176408870a4f4e4857e43ded`, tree
`ac02e58afb505e8ae4be15c5ad5eda80ae57f318`, with
[`templates/mocs/README.md`](templates/mocs/README.md) and
[`test_mocs_entry_navigation.py`](tests/test_mocs_entry_navigation.py).
R126 remains historical as the STATUS/ROADMAP synchronization to R125.
R125 remains historical as the Company Starter entry-navigation revision at
public `main` commit `a5d052d425c9236a5cdb118a796b936ba74232aa`, tree
`bca093039d31b3b0f7c595ec91d8224f7419bd7c`. R125 adds a stable
ideal/current/smoke first-stop in
[`examples/company-starter/README.md`](examples/company-starter/README.md),
covered by [`test_company_starter_entry_navigation.py`](tests/test_company_starter_entry_navigation.py),
linking the Company Template layers, Company Pack Catalog, Schema / Validator /
Test Matrix, Starter Walkthrough, and Public Preview Self-check. R124 remains
historical as the root Template Catalog entry-navigation revision at public
`main` commit `26946de5655835dfdff75a6aef2b8f344d7b7e78`, tree
`2778816782efb41029657a9788463fbe1569f681`; R123 remains historical as the
STATUS/ROADMAP synchronization to R122. R122 remains historical as the
Blocks/Records navigation revision at public `main` commit
`677bd15bec0fdfd22410b237916d05be0d1ca02c`, tree
`299a0248734daec3974b80ff174b4540995f4c47`. R122 added ideal/current/smoke
guidance and a stable Read next path in
[`templates/blocks/README.md`](templates/blocks/README.md) and
[`templates/records/README.md`](templates/records/README.md), with the
[`test_blocks_records_navigation.py`](tests/test_blocks_records_navigation.py)
regression. The [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) still
links the [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)
Runbook smoke, the [`test_public_starter_runbook_smoke.py`](tests/test_public_starter_runbook_smoke.py)
path, and the [`test_company_pack_catalog_runbook_smoke_entry.py`](tests/test_company_pack_catalog_runbook_smoke_entry.py)
entry, while the README Quick Start and [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)
retain the same executable smoke. The guided path reaches bundle at
`CANDIDATE_FOR_GOVERNED_REVIEW` -> `MATCH`, while
the plain path remains `CUSTOMIZATION_REQUIRED` and fail-closed with
`BUNDLE_REFUSED`. The published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`; R121 remains historical as the Matrix-to-Catalog smoke
entry, R120 remains historical as the STATUS/ROADMAP provenance
synchronization to R119, and R119 remains historical as the Company Pack
Catalog Runbook smoke entry at public `main` commit
`b878464eca0571fe293222d372cf417c9e9e1573`, tree
`f5aa3a3fa405c0e5fed4d984921d6ad44dca0bd3`. R118 remains historical as the
Template Guide first-read smoke entry, R117 remains historical as the
STATUS/ROADMAP provenance synchronization, R116 remains historical as the
README Runbook smoke entry at public `main` commit `2a5a65cdbefc0e1fc33c88771a95443ed52d5960`, tree
`456d5a990ae030699246959e12daf0a4a9cbb6d1`,
R115 remains historical as the Starter Walkthrough smoke entry, R114 remains
historical as the STATUS/ROADMAP provenance synchronization, R113 remains
historical as the starter smoke matrix revision, R112 remains historical as the
STATUS/ROADMAP provenance synchronization, R111 remains historical as the
schema/validator test matrix revision, and R110 remains historical as the stable
MOC index revision, R109 remains historical as the STATUS/ROADMAP label cleanup,
R108 remains historical provenance, and R107 remains historical provenance.
R37 introduced
the read-only [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) with a deterministic `--format markdown`
summary. R45 added the saved-bundle to Review Request boundary, R46
added the dynamic Review Response boundary, R47 added the dynamic Decision
Handoff boundary, and R48 clarified that the starter's `19/46/5` values are
examples; another Pack follows its actual checker, saved report, and
review-chain counts. R50 added the eight-entry-point navigation
synchronization: each entry point explains ideal/current usage and links the
read-only Review Request, Review Response, and Decision Handoff path. R52
added the explicit ideal/current Company Template usage flow to README. R54
added the practical ideal/current Template Catalog usage sequence and links.
R55 hardened standard unittest discovery for that Catalog regression. R56 added
the first-read order and bounded runtime profile selection for
`compose_minimum` and `proxmox_segmented`. R58 added the README first-stop guide
that sends readers through Catalog, Starter Walkthrough, and Installation
Lifecycle only when a runtime profile is needed. R62 added the Company Pack
Catalog first-stop sequence with the same bounded order and no-runtime
boundary. R64 added template-pack path canonicalization, R65 added
installation-lifecycle purpose schema/validator parity, and R66 added Compose
binding integer schema/validator parity. These surfaces do not add runtime
authority or access, and
activation, Promotion, Current Truth, and Public Beta remain outside the
published preview.

R68 added the README Voice rotation ideal/current contract for the 900-second
boundary, speaker/timestamp private-channel post, listener/rejoin continuity,
and retention/delete receipt. This is documentation only; real Voice rotation
remains unproven, and no capture, ASR, Discord post, deletion receipt, runtime
authority, Promotion, Current Truth, or Public Beta access was added.
R70 aligned the resolved Compose candidate's bytes semantics with Draft 2020-12:
finite non-negative integer-valued JSON numbers are accepted while booleans,
fractions, negatives, and non-finite values remain rejected. A Docker-free
synthetic candidate passes both validators. This is validator/test hardening
only; it does not add Compose runtime, image, provider, deployment, restart,
credential/permission, Promotion, Current Truth, or Public Beta access.

R72 added installation-lifecycle fixed-boolean schema/validator parity, and R73
added Compose security fixed-boolean schema/validator parity. R74 added
resolved Compose nested boolean schema/validator parity: numeric 0/1 aliases
are rejected by both schema and stdlib validator while integer-valued binding
bytes remain accepted. These are validator/test hardening changes only; they do
not add Compose runtime, installation, deployment, Voice runtime, Discord post,
provider, authority, Promotion, Current Truth, or Public Beta access.

R76 clarified the ideal/current MOC boundary: Voice Operations and Venture /
Customer Discovery are conceptual future candidates, while the public starter
ships exactly three navigation-only MOCs. This is documentation/test hardening
only; no runtime, authority, Promotion, Current Truth, or Public Beta access
was added.

R78 clarified the ideal six-phase installation lifecycle versus the current
sanitized public candidate. The published profile examples, schema, validator,
runbooks, and synthetic examples expose no target-bound runtime receipt,
image acquisition, start/restart, migration, restore, or provider connection.
The command/path regression binds the documented Windows/POSIX validator and
Compose/Proxmox runbook references to shipped files. This is documentation/test
hardening only; no runtime, Voice, provider, authority, Promotion, Current
Truth, Final Human GO, or Public Beta access was added.

R80 clarified the ideal Company Template -> Blocks -> Governed Records -> MOCs
-> validator -> review -> runtime candidate flow and separated it from the
current local/synthetic, read-only/candidate-only starter path. Installation
Lifecycle remains profile guidance only; the starter does not claim install,
deploy, restart, restore, Voice/Discord E2E, provider connection, Promotion,
Current Truth, Final Human GO, or Public Beta access. This is documentation/test
hardening only; `NO_GO_UNPUBLISHED` remains unchanged.

R82 clarified the ideal six-phase installation lifecycle against the current
sanitized public candidate and added PowerShell/POSIX runbook and validator
command parity. R83 aligned the Validation Guide ideal/current boundary and its
lifecycle command paths. R84 added README PowerShell/POSIX command parity for
Quick Start, Review Bundle, and runtime-candidate validation. R85 added
onboarding PowerShell/POSIX command parity for customization, planning,
Catalog/self-check, validator, and review-bundle preparation. These are
documentation/test hardening only; they do not add runtime, Voice, Discord,
provider, authority, Promotion, Current Truth, Final Human GO, or Public Beta
access, and `NO_GO_UNPUBLISHED` remains unchanged.

R86 synchronized STATUS and ROADMAP provenance through the R85 onboarding
surface. R87 added Template Guide and Catalog POSIX parity, R88 added guided
onboarding POSIX parity, R89 added Validation Guide core POSIX parity, R90
added Public Preview Self-check POSIX parity, and R91 added Compose candidate
runbook POSIX parity. Each revision was published with focused regression
coverage and exact remote readback; each remains documentation/test hardening
only and does not add runtime, Voice, Discord, provider, authority, Promotion,
Current Truth, Final Human GO, or Public Beta access.

R92 synchronizes the public STATUS/ROADMAP provenance to the R91 public
candidate (`b071ce9b2fd4167c8ac199bcd1983b64224fba43`, tree
`c6c7bafebd9cca6bdc37365af560b2f11f9fc7e8`). This synchronization is itself
documentation-only; `NO_GO_UNPUBLISHED` remains unchanged.

R100 added the standalone Public Preview Self-check cross-navigation from the
ideal Company Template layers through the current Catalog, Starter Walkthrough,
and Installation Lifecycle path. R101 added the standalone Installation
Lifecycle reading entry from Template Guide -> Company Template -> Blocks ->
Governed Records -> MOCs, then Catalog -> Starter Walkthrough before profile
selection. R102 synchronized STATUS/ROADMAP provenance to that surface. R103
added the README ideal/current layer map: Template Guide -> Company Template ->
Blocks -> Governed Records -> MOCs before Catalog -> Starter Walkthrough ->
Public Preview Self-check -> Installation Lifecycle. R103 remains the
historical README/documentation layer-map candidate at commit
`92a67b1bd0b450b549590d915b24dd983bb3eb7a`, tree
`a8437da05a2688e64129458eb604a6f604deb59c`. R104 synchronized
STATUS/ROADMAP provenance to R103, which remains historical. R105 added the
direct Installation Lifecycle link in the Template Catalog Runtime profiles
row and was the historical public Template Catalog/Installation Lifecycle
candidate at commit `615fdbab66ed1ad3fa779fb762dc8a27eca857d1`, tree
`3b881f999704e1c3e3c3f4c0929fd019c6f163ed`. These are documentation/test
changes only; `read-only/candidate-only` and `NO_GO_UNPUBLISHED` remain in
force, and real Voice rotation remains unproven.

R106 synchronized STATUS/ROADMAP provenance to R105; R105 remains historical.
R107 aligned the Company Template ideal order to Human Intent -> Blocks ->
Governed Records -> MOCs -> validator/review before optional runtime profile
selection. Its historical public candidate was commit
`de163c060006d50545229fd8ef092f97c583074d`, tree
`a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc`. This is
documentation/test hardening only; the public path remains
read-only/candidate-only and `NO_GO_UNPUBLISHED`, with no runtime, Voice,
provider, Promotion, Current Truth, or Final Human GO claim.

公開Company starterは、Source IntakeからPromotion Decision Recordまでの9 Block、全出力を受ける9種のGoverned Record契約、Company Operations / Public Release Review / Incident & Recoveryの3 MOC、manifestを含みます。目的別MOCは同じcanonical flowの順序を保ったnavigation projectionです。依存なしinitializerは元exampleや既存targetを上書きせず、pack IDとMOC参照を再束縛し、22文書を`draft`にして生成packを検証します。customization checkerはplaceholder 0でも`READY_FOR_GOVERNED_REVIEW`までに限定し、review/evidenceを残します。review bundle builderは、その状態だけをmanifest・Blocks・MOCs・Recordsのexact SHA-256 / byte sizeへ束縛し、途中driftを拒否します。saved-bundle verifierはbundle metadata/digestと現在bytesを再照合し、duplicate keyや1-byte driftをfail closedで`MISMATCH`にします。Review Request、Response、Decision Handoffは保存済みchainを再入力なしで運びますが、すべてread-only/candidate-onlyです。Work Order、Capability Grant、Change Executionを分離し、Promotion Candidateと人間のPromotion Decisionも分離しています。標準ライブラリvalidatorでflow、MOC、Record coverageを検査できますが、実権限付与、Human approval、incident runtime、recovery execution、runtime deployment、Promotion、Current Truthを作るものではありません。

Source binding verification candidateは、privateなR31 record、Source Content、aggregate access evidenceをbounded no-link readerで照合し、strict parse、exact raw-byte binding、lossless R30 source-binding projection digest、二回のterminal rereadを報告します。reportは常に`CANDIDATE_ONLY`で、成功しても`STABLE_POSTCHECK_UNVERIFIED` / `ELIGIBLE_UNVERIFIED`です。full R31 schema、cross-file atomic snapshot、locator resolution、origin、authenticity、consent authority、retention enforcement、trusted time、Intent builder、runtime、GOは未証明です。populated inputとprivate projectionはrepositoryへ含めていません。

Protected Source binding receipt candidateは、将来のprotected runnerがprivate snapshot、trusted clock、immutable locator resolution、6種のevidence、replay reservation、retention/deletion、detached attestationを束縛するためのclosed schemaです。現在はschema/test/runbookだけで、populated receipt、runner、evidence body、trust-root/signature verification、nonce reservation、削除実行はありません。全claimはfalseで、Public Betaは`NO_GO_UNPUBLISHED`です。

Compose minimum / Proxmox segmentedには、preflight、candidate作成、Work Order付きapply、positive/negative verification、rollback、隔離restore演習の6フェーズ契約、schema、標準ライブラリvalidator、公開runbookを追加しています。実環境識別子やsecretを含まないplanning/evidence contractであり、実installer、deploy、restart、restore、provider E2Eのreceiptではありません。

Compose minimumにはさらに、Company DBとEvidence metadata Storeを別service、別internal network、別volumeに置くdata-plane skeletonを追加しています。host port、hardcoded password、mutable image、共有network/volume、unbound file、SQL role/table driftをvalidatorが拒否します。credential非開示resolverはCompose configの生JSONを保存せず、password、image repository、host絶対pathを除いたproject namespace、image digest、network、volume、migration、healthcheckのcandidateを作り、保存後validatorがcurrent shipped revisionとdigestを再照合します。Docker daemonでのimage取得・container起動・migration・health・restart・backup/restoreは未実行です。

local image availability preflightは、匿名化したdaemonと候補digestへ、既存imageのlist/inspect結果を時刻付きsnapshotとして束縛します。read-only queryだけで、image pull/tag/removeやcontainer作成・起動へfallbackしません。saved verifierのPASSはhistorical self-digest/candidate bindingだけで、真正性、freshness、複数queryのatomicity、current stateは証明しません。公開repositoryには実hostのavailability snapshotを含めておらず、現行hostでのlive PASSは未証明です。

clean-install/migration evidence candidateは、external runnerのreported effects、Work Order/target/before-state hash、別executor/reviewer hash、2 serviceのmigrationとpositive/negative DB checksをcandidate/preflightへ束縛します。saved verifierはDocker/DBへ接続せず、`UNATTESTED_EVIDENCE_BINDING_ONLY`までしか返しません。真正性、freshness、atomicity、current state、実行済みclean install/migrationは未証明です。

protected attestation verifierはOpenSSH署名、allowed signer、signed window、nonce snapshotをpoint-in-timeで検査します。one-use evaluatorはさらに外部入力policy digest、allowed-signers hash、nonce-store IDを束縛し、同一SQLite transactionで署名評価とnonce一意予約をcommitします。同時二重評価は一件だけ成功します。ただしcanonical policy adoption、trusted clock、store continuity、reported runtime truth、live installは未証明です。

nonce-store checkpointはreservation rowのdigest集合、store ID、exact schema contractを署名可能なprivate checkpointへ固定します。successor検証ではcurrent store exact match、immediate-parent digest/signature、parent集合のsubsetを確認するため、1リンク内の巻き戻しと同件数差替えを拒否できます。ただし外部pinの権威、trusted clock、branch不存在、全履歴continuity、backup/restoreは未証明です。

recursive checkpoint-chain verifierは、最大1,024 checkpointをself-contained private bundleへ固定し、全embedded digest、独立pinと一致する`ssh-keygen` exact bytesでの全OpenSSH signature、直前parent link、同一store ID、append-only reservation集合を検査します。supplied SQLite storeは最初のopened-object copyと通常SQLite snapshotを相互照合してからcurrent checkpointとのlogical equivalenceを確認します。これはbundleに含まれる提示された1 pathの検証であり、pinned binaryのvendor authority、external anchorの権威、authoritative complete history、parallel branch不存在、actual store continuity、backup作成、restore実行、key rotationは未証明です。

checkpoint-head anchor verifierは、独立pinされたanchor/bundle bytes、bundle内のhead/store/count、短時間window、reviewer policy、OpenSSH署名を束縛します。restore-drill verifierは、成功shapeを持つanchor/source/restored report、distinctなreport/receipt digest、同一checkpoint state、全reported check、runner/reviewer identity hashの不一致を一つの署名済みcandidateへ束縛します。これらはunsigned reportやopaque receipt本文の真正性を再実行せず、external anchorのcanonical authority、trusted clock、complete history、branch不存在、actual backup/restore、physical lineage、protected runner、人物分離、Promotion、Current Truth、Public Beta GOは未証明です。

checkpoint segment-transition verifierは、独立pinされたR20 bundle、prior head、1つのsuccessor checkpointとdetached signature、supplied store、旧/new signer policyとOpenSSH key-blob集合、distinct reviewer policy、最大900秒window、pinned `ssh-keygen` exact bytesを検証します。key-rotationとsame-policyのmodeを分離し、検証したtransition/successor signature bytesのdigestをreportへ残しますが、検証範囲は提示された1境界だけです。canonical anchor authority、trusted clock、complete history、parallel branch不存在、旧鍵失効、鍵侵害不存在、segmentation policy採用、actual store continuity、backup/restore、protected runner、人物分離、Promotion、Current Truth、Public Beta GOは未証明です。

segment transition candidate builderは、prior bundleとsuccessor checkpoint/signatureのexpected digest、旧/new/reviewer policy、mode、ID、最大900秒windowからR22 candidateをdeterministicに新規作成します。strict JSON、R20/R19 structure、immediate parent、store ID、append-only reservation、modeごとのOpenSSH key-blob集合、reviewer hash衝突を署名前に検査し、existing outputを上書きしません。creation reportはsource bindingの構造検査だけを示し、transition/successor signature validity、実key rotation、旧鍵失効、protected execution、人物分離、Promotion、Current Truth、Final Human GO、Public Beta GOを示しません。

## Current boundary

このリポジトリは情報公開面です。Discord や外部 provider の Current Truth、Human Decision、production runtime の代替ではありません。
