# Template Catalog

このディレクトリは、Kotodama Company OSを段階的に再利用するための公開starterです。

| Category | Purpose | Current status |
|---|---|---|
| [Company](company/README.md) | 会社・チーム全体の構造と導入順 | validated JSON governance starter available |
| [Blocks](blocks/README.md) | 小さな実行・判断・検証部品 | Markdown design example |
| [MOCs](mocs/company-operations-moc.md) | 目的別の入口と読み順 | Company / Public Release / Incident & Recovery examples |
| [Records](records/README.md) | Block出力を証拠鎖へ残す記録契約 | 9種のJSON schema-backed starter available |
| [Runtime profiles](company/README.md#runtime-profile-contracts) | Compose minimum / Proxmox segmentedの導入・検証・復旧境界 | sanitized lifecycle contracts and runbooks available |
| [Runtime candidates](../runtime/README.md) | profileをsecret-freeな実行候補へ接続する | Compose data-plane skeleton available; live receipt absent |

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

MOCの入口例:

- [Company Operations](mocs/company-operations-moc.md): governance chain全体
- [Public Release Review](mocs/public-release-moc.md): 公開候補のDecisionからPromotion Decisionまで
- [Incident / Recovery](mocs/incident-recovery-moc.md): bounded recovery candidateとreceipt

3つともnavigation-onlyです。別のSSOT、実行権限、公開GOを作りません。

最短の導入手順は[Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md)にあります。`tools/create_company_pack.py`を使うと、元exampleと既存targetを上書きせず、pack IDとMOC参照を再束縛し、22文書を`draft`にして検証できます。続く[`check_company_pack_customization.py`](../tools/check_company_pack_customization.py)は、placeholder置換、governed review、別途必要なevidenceを混同せず列挙します。placeholderを閉じた候補は[`build_company_pack_review_bundle.py`](../tools/build_company_pack_review_bundle.py)でexact SHA-256 / byte sizeへ固定し、[`verify_company_pack_review_bundle.py`](../tools/verify_company_pack_review_bundle.py)で再照合できますが、MATCH自体はapprovalではありません。
