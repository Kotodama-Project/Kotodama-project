# Project Status

Updated: 2026-08-03

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
| [Source binding verification candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) | Published read-only local CLI; stable postcheck and R30 projection digest only |
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

公開Company starterは、Source IntakeからPromotion Decision Recordまでの9 Block、全出力を受ける9種のGoverned Record契約、Company Operations / Public Release Review / Incident & Recoveryの3 MOC、manifestを含みます。目的別MOCは同じcanonical flowの順序を保ったnavigation projectionです。依存なしinitializerは元exampleや既存targetを上書きせず、pack IDとMOC参照を再束縛し、22文書を`draft`にして生成packを検証します。customization checkerはplaceholder 0でも`READY_FOR_GOVERNED_REVIEW`までに限定し、review/evidenceを残します。review bundle builderは、その状態だけをmanifest・Blocks・MOCs・Recordsのexact SHA-256 / byte sizeへ束縛し、途中driftを拒否します。saved-bundle verifierはbundle metadata/digestと現在bytesを再照合し、duplicate keyや1-byte driftをfail closedで`MISMATCH`にします。Work Order、Capability Grant、Change Executionを分離し、Promotion Candidateと人間のPromotion Decisionも分離しています。標準ライブラリvalidatorでflow、MOC、Record coverageを検査できますが、実権限付与、Human approval、incident runtime、recovery execution、runtime deployment、Promotion、Current Truthを作るものではありません。

Source binding verification candidateは、privateなR31 record、Source Content、aggregate access evidenceをbounded no-link readerで照合し、strict parse、exact raw-byte binding、lossless R30 source-binding projection digest、二回のterminal rereadを報告します。reportは常に`CANDIDATE_ONLY`で、成功しても`STABLE_POSTCHECK_UNVERIFIED` / `ELIGIBLE_UNVERIFIED`です。full R31 schema、cross-file atomic snapshot、locator resolution、origin、authenticity、consent authority、retention enforcement、trusted time、Intent builder、runtime、GOは未証明です。populated inputとprivate projectionはrepositoryへ含めていません。

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
