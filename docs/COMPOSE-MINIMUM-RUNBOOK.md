# Compose Minimum Runbook

このrunbookは、Kotodama Company starterを1台の管理対象host上で試す場合の**導入ライフサイクル候補**です。公開repositoryには[Company DB / Evidence metadata Storeのdata-plane skeleton](../runtime/compose-minimum/README.md)がありますが、agent、gateway、n8n、Voice、provider、large evidence byte backend、secret、live receiptは含まれません。この文書だけでCompany OS全体のclean installはできません。

機械可読契約は[`compose-minimum.json`](../examples/installation-lifecycle/compose-minimum.json)です。

## 理想と現在の公開candidate

### 理想の導入ライフサイクル

理想的には、Company Templateと必要なBlock、Governed Record、MOCを選び、
`preflight -> stage_candidate -> apply -> verify -> rollback -> restore_rehearsal`
の6フェーズを同じcandidateへ束縛します。各material effectはexact Work Order、
fresh receipt、rollbackまたは停止判断まで揃って初めて検証対象になります。

### 現在の公開candidate

このrunbookに含まれるのは、local / syntheticなCompose契約、validator、data-plane
skeleton、コマンド導線だけです。target-bound receipt、image取得、install、deploy、
restart、restore、provider connection、Voice / Discord E2E、Promotion、Current Truth、
Final Human GOは含まれず、公開状態は`NO_GO_UNPUBLISHED`です。

## 想定する最小境界

- 専用のCompose project namespace
- 専用networkと明示した公開portだけ
- 永続volumeのinventory
- Company DBとEvidence Storeを論理的に分離
- secret値は公開fileへ書かず、実行環境のsecret mechanismから参照
- outbound providerは初期状態で無効。必要時は別Work Orderとprovider承認

## 0. 公開契約を検証する

```powershell
python tools\validate_installation_lifecycle.py examples\installation-lifecycle\compose-minimum.json
python tools\validate_compose_minimum_skeleton.py runtime\compose-minimum
```

```bash
python3 tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json
python3 tools/validate_compose_minimum_skeleton.py runtime/compose-minimum
```

ここでの`PASS`は契約構造だけです。

## 1. Preflight（read-only）

privateな作業領域で次を記録します。

- 対象hostのlocator、OS、Compose runtime version
- current revisionと稼働中projectの有無
- 使用予定port、network、volume名の衝突
- 利用可能容量とbackup先
- secret供給方法と、公開証拠へ値を出さないredaction方法

次のいずれかで停止します。

- targetや既存projectを一意に特定できない
- 必須runtime、容量、backup先がない
- 既存volumeを上書きする可能性がある
- secretや個人情報がpublic fileへ入る

## 2. Stage candidate（local / reversible）

公開data-plane skeletonを出発点にし、実行前にexact bytes、正規化した設定、image digestを資格情報非開示candidateへ保存します。

```powershell
python tools\resolve_compose_candidate.py <bounded-project-name> --output <private-candidate-output>
python tools\validate_resolved_compose_candidate.py <private-candidate-output>
```

`docker compose config`の生JSONには解決済みpasswordとhost絶対pathが含まれるため、fileやreceiptへ保存しません。resolverがprocess内で生JSONを検査し、安全なprojectionだけを出力します。

候補には少なくとも次を束縛します。

- source revision
- Compose config digest
- image digest（mutable tagだけに依存しない）
- project namespace
- network / port / volume inventory
- schema、lint、offline test結果
- last-known-good revisionとrollback手順

出力仕様とfailure boundaryは[Resolved Compose Candidate](RESOLVED-COMPOSE-CANDIDATE.md)を参照してください。

candidateのimageが既にlocalへ存在することは、作用を増やさず別snapshotへ固定できます。

```powershell
python tools\preflight_compose_image_availability.py <private-candidate-output> --output <private-image-preflight-output>
python tools\verify_compose_image_availability_preflight.py <private-image-preflight-output> <private-candidate-output>
```

このpreflightはdaemon info、image list、image inspectだけを使い、pull、tag、remove、container作成・起動を行いません。詳細は[Compose Image Availability Preflight](IMAGE-AVAILABILITY-PREFLIGHT.md)を参照してください。

`<...>`は説明用placeholderです。値をこの公開repositoryへcommitしません。

外部runnerがclean installとmigrationを実行したと報告する場合、raw outputやprivate locatorを公開せず、[Clean Install / Migration Evidence Candidate](CLEAN-INSTALL-MIGRATION-EVIDENCE-CANDIDATE.md)へhash bindingだけをまとめます。saved verifierはその構造を確認しますが、実行・attestation・freshness・current stateを証明しません。

## 3. Apply（exact Work Order必須）

Work Orderにはtarget locator、candidate revision/digest、project namespace、想定作用、rollback revision、実行window、stop conditionsを固定します。照合できない場合は実行しません。

実行コマンドはWork Orderへ束縛したmanifestとnamespaceだけを使います。

```powershell
docker compose --project-name <bounded-project-name> --file runtime\compose-minimum\compose.yaml up --detach
```

新規image取得、credential変更、public port公開、外部provider接続は、それぞれ作用をWork Orderに明記できない限り停止します。

## 4. Verify（positive + negative）

同じcandidate revisionに対して、最低限次を確認します。

- `docker compose ... ps`のservice状態
- service固有health endpointまたはlocal probe
- expected digestと観測config/image digestの一致
- 必要な内部通信が通る
- 宣言していないportやnetwork pathが通らない
- 再起動後も同じcandidateが立ち上がる
- Company DBとEvidence Storeのwrite/read smokeが分離したtest dataで通る
- logとreceiptにsecret値がない

一つでも失敗した場合、GOへ進まずrollbackを評価します。

## 5. Rollback（exact Work Order必須）

last-known-good revisionとdata互換性を先に確認します。volume削除をrollbackの既定動作にしません。

```powershell
docker compose --project-name <bounded-project-name> --file <last-known-good-compose-file> up --detach
```

戻した後に、revision、health、negative test、data readを再確認し、rollback receiptを残します。`down --volumes`のようなdata削除操作は、この一般runbookの範囲外です。

## 6. Isolated restore rehearsal（別Work Order必須）

- 本番と異なるproject namespace、network、port、volumeを使う
- backup digestを復元前に照合する
- 復元先が本番へwriteできないことをnegative testする
- schema/version、record countまたはdomain invariant、read smokeを確認する
- 演習用データの保持期限と後処理をWork Orderに含める

本番volumeへの上書きはrestore rehearsalではありません。

## 完了条件

このprofileのruntime導入を「検証済み」と呼べるのは、同じcandidateに対するpreflight、apply、restart、positive/negative check、rollbackまたはrollback不要判断、隔離restoreのfresh receiptが揃ったときだけです。それでもPromotion、Current Truth、Public Beta GOは別です。

## #158: 実施担当へ渡すWork Order草案

この節は未発行の計画候補です。実行許可、担当者の本人確認、target、
実施window、成功receiptはまだありません。既存の権限を持つ担当がprivateな
管理先で不足項目を固定し、exact Work Orderを発行するまでは適用しません。
この公開草案をそのまま実行コマンドへ置換しません。

### 6フェーズの分担と入力

公開契約の検査と返却要約の対応確認はagent、実hostの観測・実行・private入力の
保管とverifier実行は権限を持つ担当、独立検証と採否は別のreviewer/ownerが担当します。
下記のroleは担当割当の候補であり、実在の人や実行権限を発行した記録ではありません。

| phase | 実施担当とprivate入力の役割 | 保持するreceiptと検査の範囲 |
|---|---|---|
| preflight | host担当: target inventory、host capabilities、current revision、privacy scan | 観測時刻、namespace/volume/networkの衝突、容量、secret供給方法、before-stateをprivateに保存。公開profile validatorは構造だけを検査し、host能力を観測しない |
| stage_candidate | host担当: source revision、configuration digest、offline validation、resolved candidate、image preflight | 下記のcandidate/preflight verifierで保存bindingを検査。imageの存在は観測snapshotに限り、freshなcurrent stateではない |
| apply | host担当: bounded Work Order、before-state receipt、change journal | targetとcandidateの再照合、変更前後と実行時刻を保存。汎用のlive apply verifierは未提供。clean-install/migrationの保存候補検査は報告の構造だけ |
| verify | host担当と独立reviewer: candidate digest、service health、negative results、network boundary checks | health、restart、DB分離write/readとdeny pathをprivateで実測。保存候補のpositive/negative項目はreported checksであり実測の証明ではない |
| rollback | host担当: rollback Work Order、last-known-good revision、rollback verification | config/data互換性、戻したrevision、health、deny test、data readを再観測。汎用のlive rollback receipt verifierは未提供 |
| restore_rehearsal | host担当: 別のrestore Work Order、backup digest、isolated restore result、recovery verification | 本番と別namespace/network/port/volume、production write拒否、schema/domain invariant/read smoke。汎用のlive restore receipt verifierは未提供 |

`verify`のprofile effectはread-onlyですが、DB write/read smokeやrestartには作用が
あります。その試験のtest data、rollback、restart範囲も実行Work Orderに明記し、
profileのラベルだけでwrite/restartを許可しません。rollback不要の場合は判断と理由を
保存します。省略判断をrollback試験成功のreceiptとして数えません。

### private Work Orderに埋める項目

- 状態: 未発行候補。owner/実行担当/独立reviewerのprivate参照と現在の許可範囲を確認する。
- 対象: `<private-target-locator>`、限定project namespace、service、network/port/volume inventory。
- 固定入力: `<candidate-revision>`と各file SHA-256、resolved candidate、
  image preflight、before-state、backup、migration SQLのdigest。
- 作用: 2つのDB serviceのinstall/migration、明示されたtest dataによる
  write/readとtransaction rollback、restart、必要時のrollbackだけを列挙する。
- 復旧: `<last-known-good-revision-and-digest>`、data互換性、復旧を検査する
  private手順。restore演習には別のtarget、別Work Order、保持期限と後処理を固定する。
- 実施window: `<private-window>`。target不明、digest drift、backup不足、
  deny path許可、health不良、秘密情報混入、終了不明の場合は停止し再開を自動化しない。
- 範囲外: image pull、credential変更、public ingress、provider転送、volume削除、
  Promotion、Current Truth、Public Beta GO。この草案から許可を導かない。

private locatorの実値、SQL、raw command output、ID、署名入力、secretは既存管理先へ
保管します。公開repositoryやIssueに記入しません。

### 固定revisionでの検査

まず使うcheckoutのcommitを固定し、`git rev-parse HEAD`で得た値を
`verifier_revision`として記録します。source candidateのrevisionとは別fieldです。
次の公開入力の検査はhost/providerに触れません。

```text
python -S -B tools/validate_installation_lifecycle.py examples/installation-lifecycle/compose-minimum.json
python -S -B tools/validate_installation_lifecycle.py examples/installation-lifecycle/proxmox-segmented.json
python -S -B tools/validate_compose_minimum_skeleton.py runtime/compose-minimum
python -m unittest tests.test_validate_installation_lifecycle tests.test_validate_compose_minimum_skeleton tests.test_verify_compose_clean_install_migration_evidence_candidate -v
```

3つのCLIの成功は`PASS`、`errors: []`、exit 0です。claimsはすべてfalseのままです。
unit testsにはcandidate/preflight/migrationのdrift拒否と、古い自己整合snapshotが
historical bindingにしかならないことの検査を含みます。これらはlive receiptではありません。

次は権限を持つ担当が、入力実fileを保管しているprivate環境で行う照合です。
引数名は入力の役割であり、公開file作成の指示ではありません。

```text
python -B tools/validate_resolved_compose_candidate.py RESOLVED_CANDIDATE_JSON
python -B tools/verify_compose_image_availability_preflight.py IMAGE_PREFLIGHT_JSON RESOLVED_CANDIDATE_JSON
python -B tools/verify_compose_clean_install_migration_evidence_candidate.py EVIDENCE_JSON RESOLVED_CANDIDATE_JSON IMAGE_PREFLIGHT_JSON
```

生成時のresolverとimage preflightはこのrunbookのstage手順を使います。
保存候補3入力verifierのexit 0は`UNATTESTED_EVIDENCE_BINDING_ONLY`です。
exit 1は`INVALID`、exit 2はusage errorです。古い報告でも整合すれば通り得ます。
clean install、restart、rollback、restore、authenticity、freshnessはfalseのままです。

attestationを使う場合は[既存の9入力手順](PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)を
同じprivate境界内で実行します。署名・policyのpoint-in-time照合もreported checksの
真実性、canonical trust root、trusted clock、完全なreplay防止を証明しません。
nonce store/checkpointの手順は[対応表](SCHEMA-VALIDATOR-MATRIX.md)から選び、
そのtoolが要求する全入力とauthorityを固定します。PB-G7の受入は別です。

### 返却要約と再開条件

担当はphaseごとに、入力役割と各exact-file SHA-256、candidate revision、
verifier revision、終了code、structured status/claims、観測/検査時刻を結びます。
公開用にはrole、件数、digest、結果と公開可能なrevision/時刻だけを残し、
host/path/ID/credential、入力本文、署名、raw outputを除いて確認します。
該当verifierが無いphaseは`NO_VERIFIER / UNPROVEN`とし、実測のprivate証拠参照を
担当の管理先に保持します。必要入力や結果が欠ける場合は未検証です。

agentは受け取った要約と候補・検査手順の対応を確認できますが、digestしか
受け取っていない場合にprivate receipt本体や署名を検査したとは報告しません。
実施・freshness・同一candidate binding・独立確認の必要証拠が揃った範囲だけを
#158と#156へ反映します。schemaのPASSやreported booleanでPB-G6を閉じません。
`NO_GO_UNPUBLISHED`を維持し、この準備の完了で#158をcloseしません。

### Composeの後のProxmox segmented

[Proxmox runbook](PROXMOX-SEGMENTED-RUNBOOK.md)の同じ6フェーズへ上の分担を写します。
Composeの成功をProxmoxのreceiptへ流用しません。role→guest/serviceのprivate対応、
segmentation/identity matrix、config/firewall revisionとdigest、backup、
isolated guest/segment/storage targetを別candidateへ固定します。

host担当がrole別health/restart、許可通信と管理面/public ingress/cross-segmentの拒否、
DB分離、監視、rollback後のdeny matrix、restore後のproduction write拒否と
RTO/RPO観測を実施します。公開profile validatorはこれらの構造だけを検査します。
Compose専用saved verifierをProxmoxのlive verifierとして使いません。
Proxmox全phaseの汎用live receipt verifierは未提供なので、実行と独立確認の
private証拠を保持し、公開要約では未証明のphaseを明記します。Voiceを含める場合も
PB-G1/G2/G3/G5/G10の別scope E2Eをrole healthで代用しません。
