# Cloudflare providerの内容を含まない棚卸し

Issue #3の公開receipt契約です。対象account／zoneの確認、GETの応答、plan／費用の判断は
認証された担当者が行い、元receiptを非公開に保存します。公開する候補には件数、状態、
時刻、SHA-256 locatorだけを入れます。account ID、zone名、hostname、origin、
メール、token、API本文は入れられない閉じたschemaです。

## 担当者が用意するもの

1. 対象accountとzoneを一つずつ選び、既存の対象と一致するか確認する。
2. 必要なread scopeだけを持つ短期tokenを安全な保管先へ用意する。値をIssueへ貼らない。
3. private作業領域で下記のGETだけを実行する。全pageを読めなければ件数を確定しない。
4. 認証拒否、identityの曖昧さ、予期しない請求、既存resourceの衝突を記録して停止する。
5. 元responseとlocatorの対応はprivate receiptへ保持し、そのdigestと集計を公開候補へ写す。
6. planのentitlementと費用上限のowner decisionを別の証拠へ結ぶ。unknownをFreeや0としない。

API rootはCloudflare公式APIです。pathの識別子は担当者のprivate領域だけで展開します。

| 対象 | GETの確認先 | 読み取りの限界 |
|---|---|---|
| account／zone | accounts、選択したzonesの詳細 | 名前やIDは公開せず、対象照合をprivateで行う |
| Workers／Pages | accountsのworkers/scripts、pages/projects | 一覧は稼働・配備bytes・健康の証明ではない |
| Tunnel／Access／DNS | accountsのcfd_tunnel、access/apps、zonesのdns_records | origin、audience、policy、hostnameは公開しない |
| R2 | 選択accountのr2/bucketsとsubscription証拠 | bucket一覧だけで有効subscriptionや課金を証明しない |
| AI Gateway | [gateways一覧](https://developers.cloudflare.com/api/resources/ai_gateway/methods/list/) | Read scopeで取得。設定変更や推論はしない |
| plan／billing | [subscriptions](https://developers.cloudflare.com/api/resources/accounts/subresources/subscriptions/methods/get/)と必要な公式entitlementのreadback | 403はDENIED、プランや料金はUNKNOWNのまま |

この手順は実行済みという記録ではありません。対象が未確定ならAPIを呼びません。
install、POST／PUT／PATCH／DELETE、token変更、paid plan有効化、deployを行いません。

## 公開契約の検査

```text
python -B tools/validate_cloudflare_provider_inventory.py examples/cloudflare-provider-inventory/synthetic.json
```

validatorはlocal JSONだけを読み、schemaと報告内容の整合を検査します。OBSERVEDは
HTTP 200・件数・digestを要求し、DENIED／UNKNOWNを件数0へ変換すると拒否します。
planと予算の報告にはそれぞれ証拠digestを要求します。hostname／origin／audience／
Access policy／rollbackの未決事項を残せます。

INVENTORY_RECORD_VALIDは記録の構造が正しいという意味です。本人性、署名、
providerの現在状態、費用の承認を検証せず、private receiptも読みません。
すべて記入されていてもCOMPLETE_REPORTEDに留め、deployment authorityはfalseです。
別のdeploy preflightへ渡すときは元receipt、現行scope、owner判断を独立に検証します。
Public BetaはNO_GO_UNPUBLISHEDです。
