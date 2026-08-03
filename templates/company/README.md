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

理想では、この順序をCompany Templateのcanonical flowとして組織の
Human Intent、正本owner、runtime profileへ合わせます。現在の公開starterで
できるのは、構造を作業copyへ複製し、synthetic/local候補をvalidatorと
review bundleへ通すところまでです。review request、response、decision
handoffは保存済みcandidateを再照合するread-only後段で、実行権限や承認を
追加しません。

## Current status

Company governanceのJSON starterと、runtime profileのplanning/evidence contractを公開しています。上記package全体、実service installer、live deployment receiptはまだ実装・公開されていません。Company Packのreview chainは[Template Guide](../../docs/TEMPLATE-GUIDE.md)、[Review Workflow](../../docs/REVIEW-WORKFLOW.md)、[Review Request](../../docs/REVIEW-REQUEST.md)、[Review Response](../../docs/REVIEW-RESPONSE.md)、[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)で確認できます。

## Runtime profile contracts

| Profile | 選ぶ目安 | Contract / runbook |
|---|---|---|
| Compose minimum | 1台の管理対象hostで小さく試す | [Profile](profiles/compose-minimum/README.md) |
| Proxmox segmented | service、network、identity、storageをrole別に分離する | [Profile](profiles/proxmox-segmented/README.md) |

どちらも`preflight -> stage_candidate -> apply -> verify -> rollback -> restore_rehearsal`の6フェーズを使います。公開例にsecretや実環境識別子を書かず、material phaseはexact Work Order、結果はcandidate-bound receiptへ分けます。schema/validator PASSはlive install、restart、restore、Promotion、Public Beta GOではありません。
