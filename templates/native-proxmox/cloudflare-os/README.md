# 公式Cloudflare OSをProxmoxのLXCテンプレートにする

公式のCloudflare OSソースを固定し、`pct create → pct template → pct clone --full 1`で再現するための部品です。
独立した新規guestだけに適用します。利用中のアカウント入りguestをテンプレート元にしません。

このprofileはupstreamの`run-local`を使う評価用です。公式の自前サーバー向け本番deployment toolingは準備中であり、Proxmox本番サポートやCompany AGIの完了を示すものではありません。
[公式の自前サーバー向け説明](https://github.com/cloudflare/cloudflare-os#deploy-to-your-own-server-using-workerd)を確認してください。

## 含むもの

- 公式core `c0b6f3e52ff0ab8d44d290647e256936e88e6b57`
- Node `24.19.0`（公式SHA256確認）、pnpm `11.17.0`、frozen project lock
- 初回instance markerがないと起動しないsystemd service
- アカウント・会話データ・provider設定がないことを確認するseal check
- 新しいcloneにだけinstance IDを発行するactivation command

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
