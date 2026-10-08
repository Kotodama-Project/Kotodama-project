# Cloudflare OS の Linux／WSL 開発

Issue #14で2026-10-08に選択された正式なローカル実行経路はLinuxです。
WindowsではWSL内のLinux Node／pnpmを使います。Windowsのブラウザは利用できますが、
固定SHAのC# shimは過去の評価用資料として保持し、正式launcherには使いません。

## 実行する候補

新しい専用checkoutで、[固定security候補](../runtime/cloudflare-os/security-2026-10-08/README.md)
を適用します。既存のruntimeやprovider設定があるcheckoutでは実行しません。
Node 24.19.0のLinux binary、pnpm 11.9.0の検証済みarchiveを明示します。
Python 3.12とhash-locked `requirements-task-swarm-ci.txt` のpsutilが必要です。

依存の生成・frozen install（どちらも`--ignore-scripts`）は準備工程です。
launcher自身はinstallを行いません。Git sourceのraw bytes、4つの候補ファイルと
lockのSHA-256を実行前後に照合し、CRLF変換や対象外の変更を拒否します。
Windows評価とLinux評価が同じmanifestに一致したことと、同じ挙動を示すことは別です。

```text
python -B tools/run_cloudflare_linux_evaluation.py build --core /absolute/core --node /absolute/node --pnpm /absolute/pnpm.cjs --output /absolute/new-build-receipt
python -B tools/run_cloudflare_linux_evaluation.py test --core /absolute/core --node /absolute/node --pnpm /absolute/pnpm.cjs --output /absolute/new-test-receipt
```

許可commandは`build`、`test`、`types`、固定scheduler試験の`scheduler`と
下記の`runtime-smoke`だけです。
引数の追加、install、run-local、deploy、remote Wranglerは受け付けません。
上流の`run-local`はinstallも行うため、この評価経路では使いません。
`PATH`は専用Node／pnpmとOSの`/usr/bin:/bin`で構築し、利用者の環境やprovider key、
Node loader設定、npm設定を継承しません。専用homeで実行し、既定20分で停止します。

## 停止と検証の範囲

launcherは子processのPIDと作成時刻を追跡し、失敗・timeout・SIGINT／SIGTERM時も
自分の子だけを停止します。終了receiptの`owned_processes_remaining`がゼロでなければ
PASSにはしません。無関係なprocessを残す負例をLinux CIで検査します。
receiptはcommand、固定source／lock、終了理由、log digestを記録します。
実行中の記録や古いreceiptを成功へ読み替えません。

これは固定された公開sourceを実行する開発runnerであり、任意の不信コードを封じるsandbox
ではありません。依存内部の通信やhost全体のlistenerゼロを証明しません。
専用GitHub-hosted Linux jobの[workflow](../.github/workflows/cloudflare-linux-runtime.yml)
でbuild、上流全suite、HTTP smokeを確認します。Windowsのscheduler失敗記録は保持します。

## HTTPとlistenerの受入

`runtime-smoke`はbuild済みの専用checkoutへ固定したテストharnessを一つ追加し、そのdigest
をreceiptへ記録します。上流の公式integration harnessで実backendと実frontend assetsを
起動し、HEADのHTTP 200を3回確認してbodyは読みません。選択したportへの接続が終了後に
拒否されることと、上流のworker向けnetwork interceptorに未処理の外部要求がないことを
検査します。実gatekeeper、worker loader、ログイン、provider機能はこのsmokeの対象外です。

runnerは自分のprocessのTCP listenerを観測し、loopback以外、listener未観測、終了後に
残るowned listenerのいずれもPASSにしません。wildcard bindをloopback成功として扱わない
負例も含みます。任意コードの通信遮断やhost全体の監査を代替する機能ではありません。
新しいcheckoutとoutputで次を実行します。同じcheckoutへのharness上書きは拒否します。

```text
python -B tools/run_cloudflare_linux_evaluation.py runtime-smoke --core /absolute/core --node /absolute/node --pnpm /absolute/pnpm.cjs --output /absolute/new-runtime-receipt
```

rollbackは新しい評価checkoutと専用outputの利用を止め、以前の採用pinを使い続けることです。
launcherは既存pin、本番、provider、Windows shimを変更しません。
Public Betaは`NO_GO_UNPUBLISHED`です。
