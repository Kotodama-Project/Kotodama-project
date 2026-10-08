# TunnelとAccessの限定ingress候補

Issue #5の方針を[閉じたschema](../schemas/cloudflare-ingress-policy.schema.json)で検査します。
これはCloudflare APIへ送る設定ではなく、担当者が実設定と照合する提案です。
providerへの接続や設定変更は行いません。

## 提案を検査する

```text
python -B tools/validate_cloudflare_ingress_policy.py examples/cloudflare-ingress/synthetic-policy.json --at 2026-10-08T00:30:00Z
```

`--at`は保存済み候補の時点検証用です。実運用の期限確認では省略して現在時刻を使います。
合成fixtureは期限が過ぎれば拒否されます。raw account、zone、hostname、origin、tokenを
入力せず、private照合表へのSHA-256 locatorを使います。

許すoriginはContext GatewayのHTTPサービス一つです。loopback以外の平文HTTP、
複数origin、直接ingress、AccessのBypass、管理・DB・検索portを拒否します。
frontendは人のidentity、GatewayはService Authを用い、二つのpolicy digestを分けます。
tokenは未失効・未撤回で、提案上の有効期間を24時間以内に制限します。
この24時間は候補の上限であり、Cloudflareがその期限を実設定したという意味ではありません。

## apply前の準備と読み戻し

1. #3の対象・plan・費用上限、#4の固定preview、#10の保護された実行担当を確認する。
2. private Work Orderに一つのhostname、origin、port、audience、Allow対象、Service Auth対象、
   policy、期限、rollback手順を束縛する。既存resourceとの衝突を確認する。
3. 設定担当者がoutbound-only Tunnel、明示Allow/Service Auth、既定拒否、最終catch-all拒否を
   適用する。検索・DB・SSH・hypervisorのlistenerや別のoriginは公開しない。
4. originのfirewallとlisten addressを読み戻す。Tunnelが動いた事実だけで直接接続が閉じたとしない。
5. 下の拒否確認と許可確認を、承認された対象に限定して担当者が実行する。
6. policyとDNSの読み戻し、token撤回、Tunnel停止、旧設定への復元手順をprivate receiptへ残す。
   rollback実行は対象Work Orderの許可に従う。receiptには本文・認証header・個人IDを保存しない。

## 拒否と復旧の受入

| 条件 | 期待する観測 |
|---|---|
| 許可された人、正しいhost・audience・path | 想定HTTP成功、metadataだけの応答 |
| anonymous、誤ったaudience、期限切れ・撤回済みtoken | 拒否。Gateway処理を実行しない |
| 許可されていないhostまたはpath | 拒否。別originへ転送しない |
| 内部appへのBypass混入 | 提案検査で拒否し、applyを止める |
| インターネットからoriginへ直接接続 | 到達不可。Accessの画面表示だけでは代用しない |
| Tunnel停止・token撤回 | 対象経路が閉じる。既存の無関係な経路を変更しない |
| rollback後の固定候補 | 対象版・policy・DNSを再読し、拒否確認をもう一度行う |

結果は時刻・固定revision・status・digest・件数だけのprivate receiptにします。
実設定、認証、直接origin閉鎖、token撤回、rollbackを未実行のままPASSとはしません。
validatorの成功は`PROPOSED_INGRESS_POLICY_VALID`で、configuration、identity、token、
direct origin closure、deployment authorityはすべてfalseです。
edge側の既存のhost/JWT境界は[Worker runbook](../runtime/cloudflare-edge/README.md)を参照します。
Public Betaは`NO_GO_UNPUBLISHED`です。
