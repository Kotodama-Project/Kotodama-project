# Template Pack Validation

`tools/validate_template_pack.py`はPython標準ライブラリだけで動く、fail-closedな最小validatorです。

## Run

```powershell
python tools/validate_template_pack.py examples/company-starter
```

```bash
python3 tools/validate_template_pack.py examples/company-starter
```

成功時は終了code `0`、失敗時は`1`、使い方の誤りは`2`を返します。標準出力は機械可読JSONです。

新しい作業copyを作る場合は、先にinitializerを使えます。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
```

initializerはshipped starterをpreflightし、既存targetを拒否し、manifest IDと全該当MOCを再束縛し、生成後にこのvalidatorを実行します。任意の既存packを更新・migrationするツールではありません。

3つのguided optionをall-or-noneで渡すと、19静的placeholderも新規Pack内で一括反映し、validatorに加えてcustomization checkerの`READY_FOR_GOVERNED_REVIEW`をpost-checkします。入力、期限、非上書き、失敗reportの境界は[Guided Company Pack Initialization](GUIDED-COMPANY-PACK-INITIALIZATION.md)、出力contractは[`company-pack-creation-report.schema.json`](../schemas/company-pack-creation-report.schema.json)を参照してください。

生成したpackのexample placeholderとgoverned review項目は別のcheckerで確認します。

```powershell
python tools/check_company_pack_customization.py work/my-company
```

このcheckerは構造validatorを先に実行し、構造PASS後だけcustomizationを評価します。`READY_FOR_GOVERNED_REVIEW`でもHuman Intent、authority、retention、Promotion、Current Truthを証明しません。詳しくは[Company Pack Customization Checklist](CUSTOMIZATION-CHECKLIST.md)を参照してください。

`replacement_required`が0になった候補は、次のbuilderでexact bytesへ固定できます。

```powershell
python tools/build_company_pack_review_bundle.py work/my-company
```

builderはmanifestと全参照JSONをSHA-256 / byte sizeへ束縛し、前後再checkでdriftを検出した場合はbindingなしで拒否します。詳しくは[Company Pack Review Bundle](REVIEW-BUNDLE.md)を参照してください。

保存したbundleを現在のPackへ再照合するには次を使います。

```powershell
python tools/verify_company_pack_review_bundle.py work/my-company-review-bundle.json work/my-company
```

verifierはbundle構造・metadata・digestを信頼せず再検査し、Packからfresh bundleを再構築して比較します。`MATCH`はbytes同一性だけで、reviewer identity、Human Decision、Promotionを証明しません。運用手順は[Candidate-bound Review Workflow](REVIEW-WORKFLOW.md)を参照してください。

MATCH済みbundle/Packからpending requestを保存した後、46件のoutcomeをID/path/reasonの再入力なしで編集・再照合するには次を使います。

```powershell
python tools\build_company_pack_review_response.py work\my-company-review-request.json
python tools\verify_company_pack_review_response.py work\my-company-review-request.json work\my-company-review-response.json
```

response schemaとverifierはrequest file SHA-256/size、Pack candidate binding、46 immutable item、5 unresolved evidence、全outcome入力をfail closedで確認します。成功reportは個別item/noteを反射しません。`ITEM_RESPONSES_MATCH_REQUEST`はidentity、authority、Human approval、selected overall outcome、Decision Record、evidence解決、Promotionを証明しません。詳細は[Company Pack Review Response Candidate](REVIEW-RESPONSE.md)を参照してください。

Compose / Proxmoxのinstallation lifecycle契約は、別のstdlib validatorで確認します。

```powershell
python tools\validate_installation_lifecycle.py examples\installation-lifecycle\compose-minimum.json
python tools\validate_installation_lifecycle.py examples\installation-lifecycle\proxmox-segmented.json
```

このvalidatorは6フェーズ順序、material phaseのWork Order、apply-to-rollback binding、profile固有evidence、秘密値・private infrastructure literal、live claim拒否を検査します。詳細は[Installation Lifecycle Profiles](INSTALLATION-LIFECYCLE.md)を参照してください。PASSはlive install / deploy / restart / restore receiptではありません。

Compose minimum data-plane skeletonのexact bytesと安全契約は次で検査します。

```powershell
python tools\validate_compose_minimum_skeleton.py runtime\compose-minimum
```

このvalidatorはmanifestの4 file binding、追加file、path containment、2 service/network/volume分離、host port、digest-required image、private password environment、internal network、NOLOGIN roles、Company/Evidence core tables、destructive SQL、全live claimを検査します。stdlib validator自体はcontainerを起動しません。Compose構文はprocess-only synthetic値による`docker compose config --quiet` testを別に持ち、daemon、pull、起動を必要としません。

private environmentから解決したCompose設定を、credential非開示candidateへ固定する場合は次を使います。

```powershell
python tools\resolve_compose_candidate.py <bounded-project-name> --output work\resolved-compose-candidate.json
python tools\validate_resolved_compose_candidate.py work\resolved-compose-candidate.json
```

resolverは生のCompose JSONを保存せず、passwordとhost絶対pathを除外したrole-bound projectionだけを出力します。passwordを別値へ変えてもcandidateとdigestが同一であることをnegative testで固定しています。validator PASSは設定解決済みcandidateのcurrent shipped revisionへのbindingであり、daemon、image availability、pull、起動、migration、healthの証明ではありません。

既にlocalへ存在するimageのavailability snapshotは次で作成・再束縛します。

```powershell
python tools\preflight_compose_image_availability.py work\resolved-compose-candidate.json --output work\compose-image-availability.json
python tools\verify_compose_image_availability_preflight.py work\compose-image-availability.json work\resolved-compose-candidate.json
```

preflightだけが観測時刻と匿名化daemonに限定してavailabilityをtrueにできます。saved verifierの`HISTORICAL_BINDING_ONLY`はsnapshotの自己digestとcandidate bindingだけを確認します。自己digestは署名・attestationではなく、saved verifierはauthenticity、freshness、複数Docker queryのatomicity、current daemon/image stateをすべてfalseにします。どちらもpull、container、migration、health、Public Beta GOを証明しません。

外部runnerがreportedしたclean-install/migration evidence candidateを保存後に再束縛する場合は次を使います。

```powershell
python tools\verify_compose_clean_install_migration_evidence_candidate.py work\private-evidence-candidate.json work\resolved-compose-candidate.json work\compose-image-availability.json
```

`UNATTESTED_EVIDENCE_BINDING_ONLY`はcandidate/preflight/file digests、Work Order/target/before-stateのhash、異なるexecutor/reviewer hash、2 serviceのmigration binding、reported positive/negative check completenessだけを示します。自己digestもidentity hashの相違もattestationではありません。verifierはDocker/DBへ接続せず、authenticity、freshness、current state、clean install、migrationをtrueにしません。

protected runnerが作ったOpenSSH署名と、評価時刻・nonce-use snapshotをpoint-in-timeで検査する場合は次を使います。

```powershell
python tools\verify_protected_compose_evidence_attestation.py <attestation.json> <attestation.json.sig> <evidence-candidate.json> <resolved-candidate.json> <image-preflight.json> <allowed-signers> <nonce-snapshot.json> <signer-identity-file> <evaluated-at>
```

`SIGNATURE_AND_POLICY_MATCH_POINT_IN_TIME`はexact attestation bytesの署名、supplied trust root内のallowed signer、独立reviewer role、signed evidence hash、最大15分のsigned window、最大60秒のnonce snapshot上の未使用だけを示します。canonical trust-root pin、trusted clock source、authoritative nonce source、原子的nonce予約は証明しないためreplay prevention完了ではなく、reported executionの真実性・current state・Public Beta GOも証明しません。詳細は[Protected Compose Evidence Attestation](PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)を参照してください。

同一bound SQLite store内でnonceを一度だけ原子的に予約する場合は、まず新規storeを初期化し、Work Orderからexact policy digestを渡します。

```powershell
python tools\initialize_attestation_nonce_store.py <nonce-store.sqlite3> <store-id-sha256>
python tools\evaluate_compose_attestation_once.py <policy.json> <expected-policy-sha256> <attestation.json> <attestation.json.sig> <evidence-candidate.json> <resolved-candidate.json> <image-preflight.json> <allowed-signers> <signer-identity-file> <nonce-store.sqlite3>
```

`ONE_USE_SIGNATURE_AND_POLICY_MATCH`はsignature/policy/evidence検査とnonce予約が一つのSQLite transactionでcommitされたことを示します。並行する同じnonceは一件だけ成功します。ただしpolicy digestのcanonical adoption、local clockの信頼性、store削除・差替えに対するcontinuity、reported runtime truthは証明しません。詳細は[One-Use Compose Attestation Evaluation](ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)を参照してください。

private nonce storeのpoint-in-time snapshotと直前checkpointへの1リンクを署名検証する場合は、次を使います。生成済みcheckpointと署名はprivate boundaryに保持し、repositoryへcommitしません。

```powershell
python tools\create_attestation_nonce_store_checkpoint.py <nonce-store.sqlite3> <parent-checkpoint-or-GENESIS> <allowed-signers> <signer-identity-file> --output <private-checkpoint.json>
ssh-keygen -Y sign -f <private-reviewer-key> -n kotodama-nonce-store-checkpoint <private-checkpoint.json>
python tools\verify_attestation_nonce_store_checkpoint.py <checkpoint.json> <checkpoint.json.sig> <nonce-store.sqlite3> <allowed-signers> <signer-identity-file> <expected-current-sha256> <parent-or-GENESIS> <parent-signature-or-GENESIS> <expected-parent-sha256-or-GENESIS>
```

Genesis successはcurrent checkpoint署名とstore exact match、successor successはさらにimmediate-parent digest/signatureとreservation集合のsubsetを示します。store verifierは最初に開いたdescriptorのstable copyと通常SQLite snapshotを相互照合し、成功reportを出すまでsource transactionを保持します。ただし外部pinの権威、trusted clock、branch不存在、chain全体、key rotation、store continuity、restoreは証明しません。詳細は[Attestation Nonce Store Checkpoint](ATTESTATION-NONCE-STORE-CHECKPOINT.md)を参照してください。

Genesisからcurrentまでの提示されたchain path全体とsupplied storeを検証する場合は、連番checkpoint/signature pairだけを含むprivate directoryからself-contained bundleを作り、そのbundleの独立protected pinをverifierへ渡します。bundle outputはchain directory外の新規fileにしてください。

```powershell
python tools\create_attestation_nonce_store_checkpoint_chain_bundle.py <private-chain-directory> --output <private-chain-bundle.json>
python tools\verify_attestation_nonce_store_checkpoint_chain.py <private-chain-bundle.json> <expected-bundle-sha256> <supplied-store.sqlite3> <allowed-signers> <signer-identity-file> <expected-ssh-keygen-sha256>
```

`SIGNED_RECURSIVE_CHAIN_AND_STORE_EQUIVALENCE`はself-contained bundle digest、全embedded bytes digest、独立pinと一致する`ssh-keygen` exact bytesでの全OpenSSH signature、Genesis、全immediate-parent link、append-only reservation path、単一store ID、stable opened-object copyとSQLite snapshotの一致、supplied store logical equivalenceだけを示します。最大1,024 checkpoint、raw aggregate 16 MiB、encoded bundle 24 MiB、nonce store 64 MiB、store query 30秒、signature検証全体120秒です。verifierは全signature検証中もsource SQLite read transactionと最初に開いたdescriptorを保持するため、長いchainはmaintenance windowで実行します。成功しても`ssh-keygen`のvendor authority、external pinの権威、complete history、parallel branch不存在、key rotation、actual store continuity、backup作成、restore実行は証明しません。詳細は[Attestation Nonce Store Checkpoint Chain](ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)を参照してください。

独立pinされたR20 bundle headを短時間の署名済みcandidateへ束縛し、続いてsource/restored reportとprivate operation receiptをreported restore-drill evidenceへ束縛する場合は、次を使います。populated inputと署名はprivate boundaryに保持し、repositoryやtest corpusへ置きません。

```powershell
ssh-keygen -Y sign -f <private-anchor-reviewer-key> -n kotodama-nonce-store-checkpoint-head <private-head-anchor.json>
python tools\verify_attestation_nonce_store_checkpoint_head_anchor.py <private-head-anchor.json> <private-head-anchor.json.sig> <expected-anchor-sha256> <private-r20-bundle.json> <expected-bundle-sha256> <allowed-signers> <signer-identity-file> <expected-ssh-keygen-sha256> <evaluated-at>

ssh-keygen -Y sign -f <private-restore-reviewer-key> -n kotodama-nonce-store-restore-drill <private-restore-drill-evidence.json>
python tools\verify_attestation_nonce_store_restore_drill_evidence.py <private-restore-drill-evidence.json> <private-restore-drill-evidence.json.sig> <expected-evidence-sha256> <anchor-report.json> <source-chain-report.json> <restored-chain-report.json> <backup-receipt> <restore-receipt> <allowed-signers> <signer-identity-file> <expected-ssh-keygen-sha256> <evaluated-at>
```

`SIGNED_CHECKPOINT_HEAD_ANCHOR_MATCH`はexact anchor/bundle pin、bundle structureとhead/store/count、署名policy、最大900秒window、pin一致した`ssh-keygen` copyでの署名を示します。`SIGNED_RESTORE_DRILL_REPORT_BINDING`は成功shapeを持つ3 report、source/restoredの同一checkpoint state、distinctなreport/receipt digest、7 reported check、runner/reviewer hashの構造的不一致、最大900秒window、署名を示します。reportとreceipt本文の真正性・実行事実を再検査しないため、canonical anchor authority、trusted clock、complete history、branch不存在、actual backup/restore、physical lineage、protected runner、人物としてのrole分離、Promotion、Current Truth、Final Human GO、Public Beta GOは証明しません。詳細は[Checkpoint Head Anchor and Restore Drill](ATTESTATION-NONCE-STORE-HEAD-ANCHOR-AND-RESTORE-DRILL.md)を参照してください。

提示されたR20 bundle headから1つのsuccessor checkpointへsegmentを移し、同一policyまたはkey-rotation policyを署名済みcandidateへ束縛する場合は次を使います。populated inputとsignatureはprivate boundaryに保持し、repositoryやtest corpusへ置きません。

```powershell
python tools\create_attestation_nonce_store_checkpoint_segment_transition.py <private-prior-r20-bundle.json> <expected-prior-bundle-sha256> <private-successor-checkpoint.json> <private-successor-checkpoint.json.sig> <expected-successor-checkpoint-sha256> <prior-allowed-signers> <prior-identity-file> <successor-allowed-signers> <successor-identity-file> <transition-reviewer-allowed-signers> <transition-reviewer-identity-file> <KEY_ROTATION_SEGMENT-or-SAME_POLICY_SEGMENT> <transition-id-sha256> <issued-at> <expires-at> --output <new-private-transition.json>
ssh-keygen -Y sign -f <private-transition-reviewer-key> -n kotodama-nonce-store-checkpoint-segment-transition <private-transition.json>
python tools\verify_attestation_nonce_store_checkpoint_segment_transition.py <private-transition.json> <private-transition.json.sig> <expected-transition-sha256> <private-prior-r20-bundle.json> <expected-prior-bundle-sha256> <private-successor-checkpoint.json> <private-successor-checkpoint.json.sig> <expected-successor-checkpoint-sha256> <supplied-current-store.sqlite3> <prior-allowed-signers> <prior-identity-file> <successor-allowed-signers> <successor-identity-file> <transition-reviewer-allowed-signers> <transition-reviewer-identity-file> <expected-ssh-keygen-sha256> <evaluated-at>
```

builder成功statusは`SEGMENT_TRANSITION_CANDIDATE_CREATED`です。同じ入力、mode、ID、時刻から同じbytesを新規作成し、既存outputを上書きしません。builderはsource structure、digest、parent/store/policy/mode/windowを検査しますが、署名作成・signature verification・実key rotationは行いません。詳細は[Checkpoint Segment Transition Candidate Builder](ATTESTATION-NONCE-STORE-CHECKPOINT-SEGMENT-TRANSITION-CREATION.md)を参照してください。

R22 verifier成功statusは`SIGNED_KEY_ROTATION_SEGMENT_TRANSITION`または`SIGNED_SAME_POLICY_SEGMENT_TRANSITION`です。prior path全署名、prior headへのsuccessor parent link、detached successor signature digest、store ID、append-only reservation、supplied store exact match、mode別signer policyとOpenSSH key-blob集合、distinct reviewer policy、最大900秒window、pinned `ssh-keygen` exact bytesを検証し、検証したtransition/successor signature digestをreportへ返します。成功してもcanonical anchor authority、trusted clock、complete history、parallel branch不存在、旧鍵失効、鍵侵害不存在、segmentation policy採用、actual store continuity、backup/restore、protected runner、人物分離、Promotion、Current Truth、Final Human GO、Public Beta GOは証明しません。詳細は[Checkpoint Segment Transition](ATTESTATION-NONCE-STORE-CHECKPOINT-SEGMENT-TRANSITION.md)を参照してください。

## What it validates

- `manifest.json`と必須governance fields
- ID形式、manifest collectionの重複、参照path形式のJSON Schema整合
- 参照されたBlockとMOCの存在とJSON形式
- pack外へ出る絶対pathまたは`..`参照の拒否
- 解決後pathのpack-root containment（symlink escapeを含む）
- manifest、参照JSON、未参照JSONを含むpack内全JSONのsecretらしいkey表記揺れと代表的token/private-key値の拒否
- templateによる`promoted`やPublic GOの自己申告拒否
- Human IntentからCurrent Truthまでのcanonical ownerとmandatory denied actions
- 対応profile（`compose_minimum` / `proxmox_segmented`）の非空allowlist
- Blockのnested authority、限定allowed actions、有効期限、verification、receipt、rollback、stop contract
- MOCの必須field、string refs、`navigation_only` authority
- ID型・重複と、MOCから未知IDへの参照拒否
- `flow`宣言時のentry inputs、全Blockの一度ずつのcoverage、前段出力、primary MOC完全一致
- `projection: flow_subsequence`を明示したsecondary MOCがmanifest IDから始まり、canonical flowと同順序の非空部分列であること
- Block出力名を外部entry inputとして再注入するdependency shadowingの拒否
- Governed Recordのschema相当契約、authority、retention参照、mandatory denied claims
- Governed Recordのcreator roleとverifier roleの分離
- 全Block出力とmanifest内Record artifactの一対一coverage
- templateからのactual Capability Grant、Promotion/`promoted`、Current Truth、Public GO/Final Human GO artifact出力の拒否

JSON Schemaは`schemas/`にあります。stdlib validatorは、portable schemaだけでは表現しにくいcross-file参照と公開安全境界も検査します。

JSON Schema単体のPASSはpackの検証完了を意味しません。作成roleと検証roleの分離、Block出力とRecordの一対一対応、pack全体のsecret scanなどのcross-field/cross-file境界を含め、公開前は必ずこのCLI validatorを実行してください。

validatorは汎用packの構造と安全境界を検査するため、`flow`や`records`を持たない既存packへ同じBlock構成や順序を強制しません。`flow`を宣言したpackでは、そのpack自身が列挙したentry inputs、sequence、MOC bindingを検査します。`records`を宣言したpackでは、全Block出力との一対一対応を検査します。公開Company starter固有の9 Block ID、9 Record artifact、Capability-before-Change、Human-evidence-before-Promotion-Decisionの順序はrepository testでも固定しています。

### Secondary MOC migration note

`flow`を宣言するpackでは、`projection: flow_subsequence`を明示したMOCだけをsecondary flow projectionとして扱います。各secondary flow projectionはmanifest IDから始まり、`flow.sequence`と同じ順序のBlockを1つ以上参照する必要があります。projectionを明示しない既存0.1 MOCにはこの追加制約を遡及適用しません。

- 実行・判断の目的別入口は、`projection: flow_subsequence`を付けて同順序のBlock部分列へ移行する。
- Recordや一般文書の横断リンクはMarkdownのnavigation documentへ分ける。
- そもそもcanonical execution orderを宣言しない汎用packでは、`flow`を省略する。

これは既存データを自動変換する処理ではありません。一般navigation MOCをflow projectionへ移行する場合だけ、作業copyで差分を確認し、validatorのPASS後に採用してください。

## Tests

```powershell
python -m unittest discover -s tests -v
```

正常packに加え、path traversal、未参照JSONを含むsecret key表記揺れ、自己昇格、Public GO、未知profile、Block action越権、無効な期限、MOC authority/shape、参照切れ、flow順序・coverage・primary MOC drift、secondary MOCのreorder、Record role分離、nested rollback/receipt欠落、governance owner欠落、重複ID、型不一致をnegative caseで検査します。installation lifecycleではphase reorder、Work Order/rollback binding欠落、profile evidence欠落、unknown field、duplicate key、non-finite number、secret/private value、live claimを検査します。Compose skeletonではbyte drift、unbound file、hardcoded password、host port、mutable image、共有network/volume、LOGIN role化、core table欠落、Windows checkoutでのLF固定を検査します。resolved candidateではpassword非開示、password非依存digest、同一password、mutable image、unsafe project name、tamper、unknown field、live claimを検査します。image availabilityではread-only command境界、private identity非開示、candidate/snapshot drift、自己再計算digestがauthenticity/freshness/atomicityを付与しないことを検査します。clean-install/migration evidence candidateではcandidate/preflight/migration drift、同一actor、service evidence再利用、reported check欠落、危険なeffect、live claim、unknown/duplicate/self-digest tamper、古い時刻がfreshnessを得ないことを検査します。protected attestationではattestation/evidence byte drift、wrong identity/trust root/role、expired/future/過大window、used nonce、stale/future snapshot、duplicate nonce/key、unknown field、秘密marker非漏洩を検査します。one-use evaluatorでは同時二重評価、同時初期化、invalid input非消費、policy/trust-root/store drift、local-clock overclaim、policy expiry/limit、store schema/constraint弱体化、missing store非作成を検査します。nonce-store checkpointではGenesis/successor、巻き戻し、同件数差替え、parent欠落、digest/signature/chain/strict-JSON改ざん、output overwrite、SQLite read-leaseを検査します。recursive chainでは3-checkpoint success、bundle signer-policy rebinding、rollback/same-count replacement、determinism、overwrite、extra entry、欠番、boolean sequenceのinteger alias、bundle digest/strict JSON/overclaim、middle signature、wrong parent、aggregate byte limit、pinned `ssh-keygen` mismatch/PATH stub、malformed policy type、schema authority境界を検査します。head-anchor/restore-drillではsigned hostile candidate、private marker非漏洩、authority/実行overclaim、同一report再利用、unsigned report overclaim、独立pin不一致、期限外評価、runner/reviewer hash衝突を検査します。Windowsでsymlink作成権限がない場合、symlink E2Eだけはskipされますが、resolved-path containment自体はvalidatorで常時有効です。

checkpoint segment transitionではkey-rotation/same-policy success、signed overclaim、fake rotation、transition/bundle/successor/store/policy/`ssh-keygen` pin drift、期限外、同一reviewer hash、prior/successor/transition署名改ざん、wrong parent、duplicate key、non-finite number、過深JSON、private marker非反映、schema authority境界を検査します。

segment transition builderではkey-rotation/same-policyのR22 round-trip、deterministic bytes、existing output refusal、bundle/successor digest pin、mode/ID/window、同一鍵fake rotation、reviewer hash衝突、wrong parent、duplicate key、non-finite number、過深JSON、private marker非反映、creation schema authority境界、usage/structured refusal分離を検査します。

## Boundary

PASSはtemplate packの構造と限定された公開安全条件だけを示します。`human_intent_ref`は非空文字列であることだけを検査し、locator形式、参照先の存在・真正性・承認状態は証明しません。実際のgoverned recordとは別途reconciliationが必要です。runtime deployment、provider E2E、実データ安全性、Human approval、Promotion、Current Truth、Public Beta GOの証明でもありません。

initializerのPASSも同じ境界です。copy、ID/MOC再束縛、`draft`化、構造検証を示すだけで、組織固有のHuman Intent、owner、保持方針、実行権限を確定しません。
