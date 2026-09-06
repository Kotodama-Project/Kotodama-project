# READMEの実装状況

2026-09-06。**[クロージングと8領域の現在地](CLOSING-2026-09-06.md)** を現在の入口にする。
個別判定は [68項目](acceptance/README.md)、正負両受入と証拠上限は各詳細、運用/権利/費用の不足は [追加条件](acceptance/GAPS.md) と [25 Issue](acceptance/ISSUES.md)へ辿る。

実測済みの限定範囲は、Company Pack実生成・local review/CAS、公式OSの要件案往復、選択local Qwenの一般chatと文書保存/reload/restart、空native Proxmox templateと別clone、保存済みVoice記録の派生・引用検索・本文返却である。Task自動接続、自然な多人Voice、常時運用、全社ACL、事業成果は未受入。

手動でTask情報を渡した試験や合成入力のPASSを、既存Taskの自律実行、複数人の受入、本番提供としない。保存済み観測は[Evidence](acceptance/EVIDENCE.md)に時点・範囲を分けた。現在の作業後は、全体を照合して必要になった作業から継続する。

## 配置の選択

Proxmoxで動かせることが要件で、有料Workersも選択肢。公式core `c0b6f3e52ff0ab8d44d290647e256936e88e6b57` の評価と、別starter gitlinkの過去receiptを区別する。[公式local手順](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/README.md#run-locally)は評価用途。独立したproduction support、認証・常設保存・監視・復旧の受入は残る。

Workersのplan/予算とモデルの従量課金は別判断。local Qwenの今回選択は、全Taskのモデル固定やcloud fallbackを認可しない。Public Betaは`NO_GO_UNPUBLISHED`、公開candidateは`read-only/candidate-only`を維持する。
