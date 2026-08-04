# MOCs

MOC（Map of Content）は、同じ Company governance chain を目的別に読み始めるための
navigation mapです。MOCは新しいSSOT、実行権限、承認、Promotion、Current Truthを
作りません。公開starterでは、すべてのMOCが `navigation-only`、`candidate-only`、
`NO_GO_UNPUBLISHED` の境界にあります。

## Ideal use and current public preview

理想的には、Company Templateで組織のHuman Intentとfact ownerを定め、必要な
BlocksとGoverned Recordsを選んだ後、MOCを目的別の入口として使います。

```text
Company Template
  -> Blocks / Governed Records
  -> MOCで目的に合う読み順を選ぶ
  -> validator / customization checker
  -> Review Bundle
  -> candidate-bound review
```

現在のPublic Previewでは、次の3つのMarkdown MOCと対応するJSON starterを
read-onlyで確認できます。MOCの順序やvalidatorのPASSは、runtime起動、
Discord/Voice接続、Human approval、Promotion、Current Truth、Public Beta GOを
意味しません。

## Read next: ideal -> current -> smoke

- **Ideal:** [Company Template](../company/README.md)で組織の境界を定め、
  [Blocks](../blocks/README.md)と[Governed Records](../records/README.md)で
  仕事と証拠の形を選んだ後、目的に合うMOCを選びます。
- **Current:** [Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)と
  [Company Pack Guided Next Steps](../../docs/COMPANY-PACK-NEXT-STEPS.md)で
  現在地と次の一手、公開starterに同梱された3つのMOCと対応するBlock・
  Record・flow位置をread-onlyで一覧します。
- **Smoke:** [Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)の
  外部接続なしRunbook smokeと
  [MOC entry regression](../../tests/test_mocs_entry_navigation.py)で、
  この導線と境界を確認します。repository rootから、追加依存なしで次を
  実行できます。

  PowerShell:

  ```powershell
  python -m unittest tests.test_mocs_entry_navigation -v
  ```

  POSIX shell:

  ```bash
  python3 -m unittest tests.test_mocs_entry_navigation -v
  ```

この入口は`navigation-only`、`read-only/candidate-only`、
`NO_GO_UNPUBLISHED`です。Catalog、validator、smokeのPASSは、runtime起動、
Human approval、Promotion、Current Truth、Public Beta GOを作りません。

## Current shipped MOCs

公開starter currently ships exactly three navigation-only MOCs:

| MOC | 使うとき | Markdown | JSON starter |
|---|---|---|---|
| Company Operations | Source IntakeからPromotion Decisionまで、canonical flow全体を読む | [Company Operations MOC](company-operations-moc.md) | [company-operations.json](../../examples/company-starter/mocs/company-operations.json) |
| Public Release Review | 公開候補のDecision、Work、検証、Promotion候補を確認する | [Public Release Review MOC](public-release-moc.md) | [public-release.json](../../examples/company-starter/mocs/public-release.json) |
| Incident / Recovery | boundedな停止・変更・検証・復旧の部分列を読む | [Incident / Recovery MOC](incident-recovery-moc.md) | [incident-recovery.json](../../examples/company-starter/mocs/incident-recovery.json) |

3つとも同じcanonical flowを参照し、Company Operationsが全体、他の2つが目的別の
ordered subsequenceです。JSON側の `authority: navigation_only`、manifest IDからの
開始、flow順序は `tools/validate_template_pack.py` が検査します。

## 選び方

1. 会社全体の仕事の流れを初めて読むなら **Company Operations** を選ぶ。
2. 公開候補の検証やreview対象を辿るなら **Public Release Review** を選ぶ。
3. 停止・復旧候補の根拠とreceiptを確認するなら **Incident / Recovery** を選ぶ。
4. どのMOCから始めても、対応するBlock、Record、exact candidate bytesへ戻る。

MOCを編集した候補は、[Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)で
全体対応を確認し、[Template Guide](../../docs/TEMPLATE-GUIDE.md)と
[Template Pack Validation](../../docs/VALIDATION.md)の順に読みます。既存のexampleを
直接書き換えず、[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)の作業copy
手順を使ってください。

## Ideal / future candidates

次の名前は設計上の候補であり、現在の公開starterには含まれません。

- Voice Operations MOC
- Venture / Customer Discovery MOC

将来MOCを追加する場合も、既存canonical ownerを複製せず、対象Blockのordered
subsequence、`navigation_only` authority、参照先、保持境界、validator回帰を
candidateとして先に固定します。MOCの追加だけで実行権限や公開GOを得ることはありません。

## Read next

- [Company Template](../company/README.md)
- [Blocks](../blocks/README.md)
- [Governed Records](../records/README.md)
- [Company Pack Catalog](../../docs/COMPANY-PACK-CATALOG.md)
- [Public Preview Self-check](../../docs/PUBLIC-PREVIEW-SELF-CHECK.md)
