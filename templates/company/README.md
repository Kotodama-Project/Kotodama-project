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
3. 必要なBlockとGoverned Recordを選ぶ。
4. MOCで目的別の読み順を作る。
5. validator、customization checker、Review Bundleで候補を検証する。
6. runtime profileは必要な場合だけ選び、Installation Lifecycleを読む。
7. synthetic dataでvertical sliceを実行し、stop、replay、rollback、restoreを検証する。

理想では、この順序をCompany Templateのcanonical flowとして、組織の
Human Intent、Blocks、Governed Records、MOCs、validator/reviewを先に
確定し、必要な場合だけruntime profileへ進みます。現在の公開starterで
できるのは、構造を作業copyへ複製し、synthetic/local候補をvalidatorと
review bundleへ通すところまでです。現在の公開経路は
read-only/candidate-onlyで、状態は常に`NO_GO_UNPUBLISHED`です。review
request、response、decision handoffは保存済みcandidateを再照合する
read-only後段で、実行権限や承認を追加しません。

## 最初に読む: Company Templateからstarterへ

Company Templateの設計を読むときは、理想のpackage構造と現在の公開candidateを分けて確認します。

| 観点 | 理想の使い方 | 現在の公開previewでできること |
|---|---|---|
| 境界 | Vision、Mission、Human Intent、owner、privacy、stop条件を会社ごとに定義する | [公開starter](../../examples/company-starter/README.md)を別の作業copyへ複製し、候補値を編集する |
| 仕事の流れ | 必要なBlocksとGoverned Recordsを選び、MOCで目的別の読み順を作る | [Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)で9 Blocks・9 Records・3 MOCsを一覧する |
| 検証 | profileを選び、Work Order、verification、rollback、restoreの証拠を束ねる | [Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)と[Public Preview Self-check](../../docs/PUBLIC-PREVIEW-SELF-CHECK.md)でlocal / synthetic候補を確認する |
| 導入 | candidate-bound Decisionの後にexact targetへbounded applyし、失敗時に戻す | 必要な場合だけ[Installation Lifecycle](../../docs/INSTALLATION-LIFECYCLE.md)でsecret-freeなprofile契約を読む。live install、restart、deployは含まない |

初めて試す場合はrepository rootから、次の順に実行します。すべて既存の公開exampleを変更せず、新しいtargetへ候補を作る操作です。既存のtargetを上書きしません。

~~~powershell
python tools\catalog_company_pack.py examples\company-starter --format markdown
New-Item -ItemType Directory -Force work | Out-Null
python tools\create_company_pack.py my-company work\my-company
python tools\check_company_pack_customization.py work\my-company
python tools\validate_template_pack.py work\my-company
python tools\check_company_pack_public_preview.py work\my-company --format markdown
~~~

~~~bash
python3 tools/catalog_company_pack.py examples/company-starter --format markdown
mkdir -p work
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/check_company_pack_customization.py work/my-company
python3 tools/validate_template_pack.py work/my-company
python3 tools/check_company_pack_public_preview.py work/my-company --format markdown
~~~

この手順はread-only/candidate-onlyの確認です。validator、Catalog、customization checker、self-checkの`PASS`は、Human Decision、capability grant、Promotion、Current Truth、runtime activation、Voice/Discord E2E、Public Beta GOを意味しません。公開状態は`NO_GO_UNPUBLISHED`のままです。

## Current status

Company governanceのJSON starterと、runtime profileのplanning/evidence contractを公開しています。上記package全体、実service installer、live deployment receiptはまだ実装・公開されていません。Company Packのreview chainは[Template Guide](../../docs/TEMPLATE-GUIDE.md)、[Review Workflow](../../docs/REVIEW-WORKFLOW.md)、[Review Request](../../docs/REVIEW-REQUEST.md)、[Review Response](../../docs/REVIEW-RESPONSE.md)、[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)で確認できます。

## Runtime profile contracts

| Profile | 選ぶ目安 | Contract / runbook |
|---|---|---|
| Compose minimum | 1台の管理対象hostで小さく試す | [Profile](profiles/compose-minimum/README.md) |
| Proxmox segmented | service、network、identity、storageをrole別に分離する | [Profile](profiles/proxmox-segmented/README.md) |

どちらも`preflight -> stage_candidate -> apply -> verify -> rollback -> restore_rehearsal`の6フェーズを使います。公開例にsecretや実環境識別子を書かず、material phaseはexact Work Order、結果はcandidate-bound receiptへ分けます。schema/validator PASSはlive install、restart、restore、Promotion、Public Beta GOではありません。
