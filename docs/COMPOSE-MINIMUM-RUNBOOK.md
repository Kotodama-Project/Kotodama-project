# Compose Minimum Runbook

このrunbookは、Kotodama Company starterを1台の管理対象host上で試す場合の**導入ライフサイクル候補**です。公開repositoryには[Company DB / Evidence metadata Storeのdata-plane skeleton](../runtime/compose-minimum/README.md)がありますが、agent、gateway、n8n、Voice、provider、large evidence byte backend、secret、live receiptは含まれません。この文書だけでCompany OS全体のclean installはできません。

機械可読契約は[`compose-minimum.json`](../examples/installation-lifecycle/compose-minimum.json)です。

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
