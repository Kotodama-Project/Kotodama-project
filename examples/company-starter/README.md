# Company Starter Example

このdirectoryは、外部依存なしのvalidatorで検証できる最小Company Template packです。

## Included chain

1. `source-intake.json`: 許可・保持条件付きの入力をSource Record候補へ正規化
2. `intent-candidate.json`: Sourceから確認待ちのIntent Candidateを抽出
3. `human-decision.json`: 人間が行ったDecisionを証拠付きで記録
4. `work-order.json`: Decisionを対象・期限・rollback付きの候補作業へ変換（実行権限は付与しない）
5. `capability-grant.json`: exact Work Orderへsubjectと最小actionの権限候補を束縛
6. `change-execution.json`: Work OrderとGrantの一致後だけChange Candidateを生成
7. `verification-receipt.json`: exact candidateの結果とnegative checksを束縛
8. `promotion-gate.json`: 自己昇格せずPromotion Candidateまで評価
9. `promotion-decision.json`: 人間の判断証拠をPromotion Decision Recordへ束縛（Promotionは実行しない）

読み順は[`mocs/company-operations.json`](mocs/company-operations.json)にも機械可読で記録されています。目的別の入口として、[`mocs/public-release.json`](mocs/public-release.json)と[`mocs/incident-recovery.json`](mocs/incident-recovery.json)もあります。

後者2つは同じ9 Block鎖の順序を保った部分列です。Public Release MOCは公開を承認せず、Incident / Recovery MOCはmonitorや復旧runtimeを実装しません。どちらもnavigation-onlyで、別のSSOTを持ちません。

`manifest.json`の`flow`は、外部入力、9 Block IDの実行順、対象MOCを束縛します。validatorはCapability GrantなしのChangeやHuman evidenceなしのPromotion Decisionを含め、Block入力が前段出力または明示entry inputへ接続されていることを検査します。

`records/`は9つのBlock出力を受け取るGoverned Record契約です。manifestの`records`と各Recordの`artifact`は一対一で検査されます。これらは実際のSource、Decision、Grant、Receiptではなく、実Recordが持つべきfieldとauthority/retention境界の例です。

```powershell
python tools/validate_template_pack.py examples/company-starter
```

成功時はJSONで`"status": "PASS"`を返し、終了codeは`0`です。

これはsyntheticな構造例です。provider接続、runtime deployment、incident monitoring、recovery execution、権限付与、Promotion、Public Beta GOは行いません。

元exampleを変更せず、IDを再束縛した作業copyを作るには次を使います。既存targetは上書きしません。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
python tools/plan_company_pack_next_steps.py work/my-company --format markdown
```

initializerは生成した22文書を`draft`にします。続くcheckerは通常19件の組織固有placeholderを返し、owner/role reviewとHuman evidenceを別categoryに保ちます。guided plannerはcategory countを保ちながら、人間向けの現在地・理想flow・分類別件数・次コマンドへまとめます。詳しい編集手順は[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)、plannerの契約は[Company Pack Guided Next Steps](../../docs/COMPANY-PACK-NEXT-STEPS.md)を参照してください。

19件の値が決まっている場合は[Guided Company Pack Initialization](../../docs/GUIDED-COMPANY-PACK-INITIALIZATION.md)のall-or-none optionを使うと、同じ新規作成内で安全に一括反映できます。これはowner/role review、Human approval、retention enforcement、Promotion、GOを自動化しません。

19件を置き換えてcheckerが`READY_FOR_GOVERNED_REVIEW`になった後は、`python tools/build_company_pack_review_bundle.py work/my-company`でreview対象の22ファイルをexact bytesへ固定できます。詳細は[Company Pack Review Bundle](../../docs/REVIEW-BUNDLE.md)を参照してください。

保存したbundleと候補bytesの独立再照合は[Candidate-bound Review Workflow](../../docs/REVIEW-WORKFLOW.md)を参照してください。

bundleが`MATCH`した後、46件のreview itemを手転記せずexact candidateへ束縛するには[Company Pack Review Request](../../docs/REVIEW-REQUEST.md)を使います。5件のevidence gapは別配列に残り、requestはoutcomeやapprovalを作りません。

46件のoutcomeだけを編集し、ID/path/reasonと元requestのbindingを再照合する次stepは[Company Pack Review Response Candidate](../../docs/REVIEW-RESPONSE.md)です。構造MATCHはreviewer identity、authority、Human approval、全体Decision、evidence解決を作りません。

completeな5成果物を別Human Decision stepへ渡す非承認candidateは[Review Evidence to Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)で作れます。handoffはgeneric Decision Record templateを変更せず、後続Recordの`evidence_ref`候補になります。

Source ItemからIntent抽出へ渡す前のprivate schema-only instance形は[Company Pack Source Record Instance Contract](../../docs/SOURCE-RECORD-INSTANCE.md)です。source bodyやpopulated recordはこの公開exampleへ含めず、locator/hashをauthenticityへ昇格しません。

保存済みR31 bytesと別保存contentのlocal照合は[Source Binding Verification Candidate](../../docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md)を参照してください。populated inputやprivate projectionはこのexampleへ追加せず、candidate matchをatomicity、consent、authenticityへ昇格しません。

SourceからHuman確認前までのprivate schema-only instance形は[Company Pack Intent Candidate Instance Contract](../../docs/INTENT-CANDIDATE-INSTANCE.md)です。source bodyやpopulated candidateはこの公開exampleへ含めず、schema PASSをHuman Intentへ昇格しません。

実Decision前のschema-only field/claim契約は[Company Pack Decision Record Candidate Contract](../../docs/DECISION-RECORD-CANDIDATE.md)です。これはDecision、承認、権限、Promotion、GOを生成せず、既存のgeneric Decision Record templateも変更しません。
