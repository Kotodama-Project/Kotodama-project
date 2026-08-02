# Company Starter Example

このdirectoryは、外部依存なしのvalidatorで検証できる最小Company Template packです。

## Included chain

1. `source-intake.json`: 許可・保持条件付きの入力をSource Record候補へ正規化
2. `intent-candidate.json`: Sourceから確認待ちのIntent Candidateを抽出
3. `human-decision.json`: 人間が行ったDecisionを証拠付きで記録
4. `work-order.json`: Decisionを対象・期限・rollback付きの候補作業へ変換
5. `verification-receipt.json`: exact candidateの結果とnegative checksを束縛
6. `promotion-gate.json`: 自己昇格せずPromotion Candidateまで評価

読み順は[`mocs/company-operations.json`](mocs/company-operations.json)にも機械可読で記録されています。

`manifest.json`の`flow`は、外部入力、6 Block IDの実行順、対象MOCを束縛します。validatorはBlock入力が前段出力へ接続されていることまで検査します。

`records/`は7つのBlock出力を受け取るGoverned Record契約です。manifestの`records`と各Recordの`artifact`は一対一で検査されます。これらは実際のSource、Decision、Receiptではなく、実Recordが持つべきfieldとauthority/retention境界の例です。

```powershell
python tools/validate_template_pack.py examples/company-starter
```

成功時はJSONで`"status": "PASS"`を返し、終了codeは`0`です。

これはsyntheticな構造例です。provider接続、runtime deployment、権限付与、Promotion、Public Beta GOは行いません。

copyして編集する手順は[Starter Walkthrough](../../docs/STARTER-WALKTHROUGH.md)を参照してください。
