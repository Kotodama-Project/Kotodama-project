# Template Catalog

このディレクトリは、Kotodama Company OSを段階的に再利用するための公開starterです。

| Category | Purpose | Current status |
|---|---|---|
| [Company](company/README.md) | 会社・チーム全体の構造と導入順 | design starter |
| [Blocks](blocks/README.md) | 小さな実行・判断・検証部品 | Markdown design example |
| [MOCs](mocs/company-operations-moc.md) | 目的別の入口と読み順 | Markdown navigation example |

## Planned catalog

```text
templates/
  human-intent/
  decision/
  work-order/
  capability-grant/
  verification-receipt/
  promotion/
  discord/
  voice/
  clone-birth/
  agent-foundry/
  venture/
  proxmox/
  n8n/
```

上記のplanned directoryは、schema、validator、test、runbookが揃ってから順次追加します。現在存在しないdirectoryを実装済みとは扱いません。

詳しい考え方は[テンプレート利用ガイド](../docs/TEMPLATE-GUIDE.md)を参照してください。

実際にvalidatorへ通せるJSON packは[Company starter example](../examples/company-starter/README.md)にあります。上記Markdown例そのものをvalidator済みと読み替えないでください。
