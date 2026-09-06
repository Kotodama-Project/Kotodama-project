# 公式Cloudflare OSをProxmoxのLXCテンプレートにする

公式のCloudflare OSソースを固定し、`pct create → pct template → pct clone --full 1`で再現するための部品です。
独立した新規guestだけに適用します。利用中のアカウント入りguestをテンプレート元にしません。

このprofileはupstreamの`run-local`を使う評価用です。公式の自前サーバー向け本番deployment toolingは準備中であり、Proxmox本番サポートやCompany AGIの完了を示すものではありません。
[公式の自前サーバー向け説明](https://github.com/cloudflare/cloudflare-os#deploy-to-your-own-server-using-workerd)を確認してください。

## 含むもの

- 公式core `c0b6f3e52ff0ab8d44d290647e256936e88e6b57`
- Node `24.19.0` と pnpm `11.17.0` のarchive digestを固定し、展開・実行前に検査する。project lockも固定
- 初回instance markerがないと起動しないsystemd service
- fresh install時の保護inventoryと現在のtemplate-owned filesを照合し、未知・追加・変更されたdataを拒否するseal check
- 新しいcloneにだけinstance IDを発行するactivation command

## 保存と検証の境界

`install.sh` は固定Node/pnpm archivesをダウンロードし、`verify-toolchain.py`で
SHA-256/SHA-512を確認してから展開する。pnpmは検証済みのlocal tarballから
offline/ignore-scriptsで導入する。pinの出典は同helper内の公式HTTPS metadata URLと
観測hash。registry signature / provenanceの独立したtrust採用を証明するものではない。
system packagesはUbuntu repositoryのinstall時点に依存し、OS全体のbit-reproducible imageを主張しない。

fresh installの最後、instance activationより前に一度だけ
`kotodama-os-seal-check --record-install` を実行して、root-ownedの
`/var/lib/kotodama-template/install-inventory.json`へinventoryを作る。
通常のsealはその保護inventoryと、`/opt/kotodama-os`、`/home/os-runtime`、
空の`/etc/kotodama`を照合する。Gitの変更、未知file、追加・変更・削除、外向きlink、
既知のinstance stateや実行中runtimeを拒否する。既存baselineの上書きや再生成で
汚れたimageをcleanにしてはいけない。過去に作ったtemplateへ後からinventoryを作って
この新しいproofを遡及させない。

この照合はguest全体のsecret scanや、最初から含まれるdependency/cache内容の
意味的な分類ではない。template化前に新規guestのSSH identity、operator access、
network境界などを別途確認する。rendererの状態値も設計上の必要条件であり実guestの検証ではない。

9月6日のnative clone観測は旧asset固定点`6bc0dae…`の限定評価である。
その後のinventory/toolchain検査の修正はlocal regressionで検証し、今回のクロージングでは
既存templateやguestへ再配備していない。新しいassetを採用する際にはfresh installと
同じseal/clone/restore受入を別途通す。

Discord token、モデル認証、利用者、録音、Task記録、Cloudflare account、既存`.wrangler/state`は含めません。必要な接続はcloneごとに導入します。

## 使用手順

1. private profileを作り、`python tools/render_native_proxmox_template.py PROFILE.json --output NEW_DIRECTORY`でplanとassetsを生成します。
2. 新しい2つのVMID、template/clone storage、RAM/disk、公式Ubuntu templateのhashを確認します。各storageのnative template/full-copy対応も現在のProxmoxで確認します。
3. planのcreateを実行し、guest firewallを有効化してから起動します。private/admin宛egressと不要なingressを拒否します。
4. assetsを新guestの`/root/kotodama-template-assets`へ置き、`install.sh`を実行します。既存インストールへの上書きは拒否します。
5. seal checkを通し、新guestだけのmachine-idとSSH host keysを空にして、停止後にplanのsealを実行します。既存guestのidentityは変更しません。
6. planのcloneでfull cloneします。cloneのfirewall、source revisionと空のinstance stateを確認してから`kotodama-os-activate --instance-id UNIQUE_ID`を実行します。
7. 実画面、文書保存、再起動後readback、認証拒否、network isolationをそれぞれ確認します。service activeやHTTP200だけで文書や業務の成功とはしません。

## Profileの値

`template_vmid`、`smoke_vmid`、`storage`、`clone_storage`、`bridge`、`hostname`、`base_image`、`base_sha256`、`rootfs_gib`、`memory_mib`、`cores`を指定します。provider secretsをprofileに入れると拒否されます。
plain LVMは環境によってnative template機能を提供しません。templateはZFSまたは機能確認済みstorageに置き、full cloneは別storageにも配置できます。

## 記録と更新

private実行receiptへVMID、source/lock/hash、image manifest、firewall、service、cloneとrestoreの証拠を保存します。公開candidateへ実環境の識別値やprivateデータを持ち込みません。
新しいcoreは別templateとして構築します。既存templateと稼働instanceを無言で更新しません。
rollbackは新規cloneの停止と保存が基本です。データやvolumeを自動削除しません。
