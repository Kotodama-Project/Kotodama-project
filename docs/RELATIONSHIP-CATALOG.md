# 人・組織・関係・活動の共通catalog候補

Issue #77の最初の対象は、公開できる架空データだけを使う読み取り専用のcatalogです。
外部CRMなしの利用と、選択されたSalesforce recordのmappingを同じmodelへ接続します。
実顧客、NDA対象、credential、実orgへの接続はこの候補に含めません。

```text
python -B tools/relationship_catalog.py examples/relationship-catalog/synthetic.json --tenant example --actor example-reader --purpose planning --format json
python -B tools/relationship_catalog.py examples/relationship-catalog/synthetic.json --tenant example --actor example-reader --purpose planning --format html
```

同じ表示時刻で比較する場合は`--at 2026-10-08T00:00:00Z`を付けます。既定は現在時刻です。
CLIは入力を読み、JSONまたはHTMLを標準出力へ返すだけです。保存や外部通信を行いません。
`map_salesforce_fixture`は明示profileのobject／fieldだけを架空recordから対応づけます。
profileの`connection`は対象orgに相当するfixture境界で、orgの実在を証明しません。

## 元情報と表示

接続先、object、record IDをidentityとし、表示名やemailで人物を統合しません。
各revisionにtenant、owner、reader、purpose、保持期限を付けます。最大revisionを選んでから
権限を検査し、削除・取消後に古いrevisionへ戻りません。同一revisionの内容が異なるときは
競合として隠し、根拠を持つ明示的な次revisionでのみ解決します。

人向け一覧とagent向けContextは同じprojectionを使います。現行権限で読めない資料や
期限切れ、削除、競合したrecordの説明文は渡しません。人物同士の関係も、両端を同じ権限で
読める場合にだけ表示します。監査用の元revisionと配信するContextを分けます。

## Salesforce APIの選択肢（2026-10-08確認）

[REST API](https://developer.salesforce.com/docs/platform/api-rest/guide/intro-rest.html)は
record・query・metadataをresourceとして扱えます。最初の限定readとobject／fieldの
明示mappingに向く候補として選びます。実利用には対象orgのAPI権限とOAuthの設定が必要です。

[GraphQL API](https://developer.salesforce.com/docs/platform/graphql/guide/graphql-about.html)は
一つのendpointで必要なデータをまとめて取得できます。関係を含む画面に必要なfieldを
一度に読む候補です。全REST objectの対応や対象orgでの利用可能性を仮定しません。

[Pub/Sub API](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/intro.html)は
gRPC／HTTP2とAvroでplatform eventやChange Data Capture eventを配送します。
継続同期が必要と確認できた段階で、schema、replay、順序、欠落後の再取得を別途実証します。
最初のread-only mappingにイベント配送やwrite権限を混ぜません。

manual fixtureは候補、REST／GraphQL／Pub/Sub実接続は未確認、writeと双方向同期は未対応です。
本catalogのidentityやACLは入力契約であり、OAuth本人確認や実orgの権限確認を代替しません。
実接続は用途・org・最小object／field・閲覧者・保持・外部処理先・rollbackを確定した後です。
