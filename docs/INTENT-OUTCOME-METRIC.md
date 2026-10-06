# KGI-INTENTの候補計算

[COMP-INTENT](../knowledge/computations/intent-outcome.md)は、既存KGI-INTENTを同じGoalへ
結び、宣言されたsnapshotから候補の件数と比を計算します。計算code、executor、schemaの
正確なbytesをConceptのsourcesでpinし、変わっていれば再読・見直しを要求します。

```sh
python -B tools/intent_metric.py compute examples/metrics/intent-outcome.snapshot.json
python -B tools/intent_metric.py attest examples/metrics/intent-outcome.snapshot.json --receipt RECEIPT.json
```

computeのstdoutを既存evidence ownerの領域へ保存し、attestへ同じ不変のsnapshotとreceiptを
渡してください。toolはファイル・KB・Task・ledgerを書き換えません。receiptをknowledgeへ
埋め込まないでください。例は全て合成で、実際の依頼・受入・測定を記録したものではありません。

## 分子・分母と反例

- 分母は、指定windowのstart以上/end未満に期限があり、endまでにadmittedだったcase。
- 除外方式は必須の明示parameterです。none、またはowner・理由・同じIntent版・時刻を持つ
  withdrawal/cancellation receiptだけを除外する方式を選べます。無記録の取消は分母に残します。
- 分子はcompleted caseのうち、SourceのID/版/hash、reviewed Intentと依頼scope、Work/grantの
  scope/有効期間、outcome、別reviewerのverification、同じownerの受入または明示policy採用receipt、
  learning/readbackが、版・digest・時系列で一致するものだけです。artifactの存在だけでは不足します。
- case/Intent/Intent版/outcomeの重複と、同じreceipt refの相反する内容を拒否します。
- failed/rejected/inconclusiveは分母と入力に残ります。境界違反は別のhard failureとし、
  高い平均で打ち消しません。KPIだけ改善してoutcome改善が不明ならREVIEW_REQUIREDです。
- 分母0はNOT_MEASURED/ratio:nullです。件数と比のどちらを採用するか、target、baseline、
  deadline、window・除外policyの運用上の採用は、このtoolから決めません。

一つのsnapshotはIntentごとの現在の版を一行ずつ持ちます。過去の失敗を消す指示ではなく、
各caseのhistory_refで既存の履歴に戻ります。入力は256KiB、depth32、最大1024caseで制限し、
重複JSONキー、不明field、本文やprivate locator、未知Goalを拒否します。

## Attestationの意味

receiptは定義revision、固定artifact digests、入力snapshot、唯一のdeclared parameterである
snapshotへのbinding、ID集合のdigest、件数、結果のdigestを持ちます。出力にcase本文やcase IDを
複製しません。attesterはtrustedな実装で再計算し、receipt全体のcanonical JSONを比較します。
falseと0の取り違え、余分なfield、除外集合、code/input/結果の変異を一致として扱いません。

PASSは **PINNED_ARTIFACT_AND_ARITHMETIC_ONLY** です。実際にそのプログラムが実行されたこと、
OS/imageやactorの同一性、coverageの完全性、Source/受入/policyの真正性を認証しません。
refが異なることも、物理的に独立したreviewerの証明にはなりません。これらは既存の証拠ownerが
別に確認する必要があります。doc-levelのverifiedと、一回の計算の一致は別です。

安全違反やREVIEW_REQUIREDという結果を、attesterの算術PASSで成功へ置き換えないでください。
返却するmeasurement adoption、authority、Current Truth、Public Beta、Human GOのclaimsはfalseです。
実測値・数値目標・運用policyの採用を、合成例から作りません。
