# 残す仕事

独自Company OSのPublic Betaへ向かうロードマップは終了しました。
[2026-10-21の方針](docs/DECISIONS.md)に従い、今後は次の二つだけを扱います。

1. **実際の仕事をOpenAI製品で終わらせる。** 対象repoに目的・完了条件を置き、訂正を反映し、成果を実際に確認する。余分な手順が減ったかを利用者が判断する。
2. **旧利用者が誤って新mainへ更新しないようにする。** 稼働service・consumer・未処理Task・保存データの所在とsource pinを非公開に確認する。必要な移行・停止は結果を読戻してから完了とする。

進捗は[GitHubのopen Issues](https://github.com/Kotodama-Project/Kotodama-project/issues?q=is%3Aissue+is%3Aopen)で扱い、この文書に別のチェック台帳を作りません。

## 開発しないもの

独自swarm/実行loop、agent registry、Task/Project DB、Company Pack審査エンジン、OKF検索・階層・学習基盤、Cloudflare OS/edge、Proxmox/Compose配備、独自GUI、Discord音声常駐Bot、Luma専用bridge、多provider抽象化、汎用性能最適化、Python package/Public Beta。

これらの旧Issueを閉じる理由は方針変更です。旧機能の完成や実環境での成功を意味しません。
不足が実際の仕事で再現された場合に限り、既存OpenAI製品・接続済みplugin・公式APIの順で最小の解決を選びます。
