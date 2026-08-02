# Company Template Starter

Company Templateは、会社やチームを運営するための文書・契約・runtime profileを一つの導入単位としてまとめるものです。

## Ideal package

```text
company/
  manifest.yaml
  human-intent/
  decisions/
  work-orders/
  capability-grants/
  receipts/
  promotions/
  mocs/
  profiles/
    compose/
    proxmox/
  adapters/
    discord/
    voice/
    n8n/
```

## Recommended order

1. Human Intentと停止条件を記録する。
2. fact familyごとの正本ownerを一つにする。
3. MinimumまたはSegmented runtime profileを選ぶ。
4. 必要なBlockだけを追加する。
5. synthetic dataで一つのvertical sliceを実行する。
6. stop、replay、rollback、restoreを検証する。
7. MOCを作り、人間が現在状態とreceiptへ到達できるようにする。

## Current status

これは構成を説明するdesign starterです。上記package全体はまだこの公開リポジトリへ実装されていません。
