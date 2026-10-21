# Security

秘密値、個人情報、音声・会話本文、私有hostや絶対パスを公開Issue/PRへ載せないでください。検出したsecretは削除だけで済ませず、所有するサービスで失効・交換します。

脆弱性の報告はGitHubの **Security → Report a vulnerability** を使います。利用できない場合、詳細を含めず非公開連絡先の設定を求めてください。

現在のmainは文書と開発用検査だけを提供します。旧runtimeは[廃止済み](docs/RETIREMENT.md)で、archiveはセキュリティ保守を約束しません。稼働中の旧版の停止・移行は、その環境とデータの管理者が扱います。

push前とCIで固定版Gitleaksによる追跡sourceの検査を実行します。GitHubのsecret scanning/push protectionの代用でも、全履歴・未追跡データの安全保証でもありません。

情報の共有先、アクセス権、保持・削除条件は元のシステムで管理します。memory・要約・GitHubへの参照だけで権限は広がりません。OpenAI製品への移行時にも、既存データを一括コピーしないでください。
