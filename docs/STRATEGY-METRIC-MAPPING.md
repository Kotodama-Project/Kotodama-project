# 製品KGIと補助指標の対応

製品の成果指標は既存の[KGI-INTENT](../knowledge/project/success-model.md)です。
[10の補助指標](../knowledge/metrics/index.md)はtype: KPI、measurement_role: supporting_kpiの
候補です。contextの品質、訂正・復旧、出典、権限、agent運用、人の負担を測る考え方を表し、
依頼した成果が受け入れられたことの代わりにはしません。kgi_refsで補助指標を指定すれば拒否します。

## 旧候補からの移し方

公開済み#49の[固定した候補](https://github.com/Kotodama-Project/Kotodama-project/blob/a20ebd336071d32d896a6391c7e01cb76ccadda9/governance/okf.json)から、
指標の意図だけを正本Conceptへ対応付けます。旧governance/okf.jsonは再導入しません。

| 旧ID | 現行の意味と行き先 |
|---|---|
| KGI-01 | [KGI-INTENT](../knowledge/project/success-model.md)。成果物やPromotion Candidateだけでは完了にせず、成果ownerの受入まで要求する |
| KGI-02 | [KPI-AUTHORITY-INTEGRITY](../knowledge/metrics/authority-integrity.md)。権限と根拠の連鎖を検査する補助指標 |
| KGI-03 | [KPI-DECISION-READINESS](../knowledge/metrics/decision-readiness.md)。目的と現在のscopeを含む知識のreadiness |
| KGI-04 | [KPI-AGENT-GOVERNANCE](../knowledge/metrics/agent-governance.md)。実Invocationの責任・eval・停止と復旧 |
| KGI-05 | [KPI-CLARIFICATION-LOAD](../knowledge/metrics/clarification-load.md)。重要な確認・訂正を隠さず扱う人の負担 |
| KGI-06 | [KPI-OWNER-RESPONSE](../knowledge/metrics/owner-response.md)。findingから既存ownerと次の作業への時間 |

旧候補の数値target、P0〜P6の予定・到達状態は取り込みません。[段階の意味だけ](../knowledge/phases/index.md)を
PHASE-P0〜PHASE-P6のConceptへ対応付けています。sequenced_afterは候補の能力依存であり、
現在地・期日・完了率・新しい実行許可を持ちません。baseline、target/threshold、
deadline、測定window、除外の採用はunknown/not_adoptedです。現在の稼働や達成の証拠にしません。

## 値を出す前に必要なもの

各Conceptは候補式、必要な証拠、整備owner、独立review、過大評価を防ぐ条件を持ちます。
required context、訂正/撤回、decision readiness、新session復旧、grounding、禁止情報、権限違反も
独立して扱い、hard violationを高い平均で打ち消しません。対象0や未確認を成功率100%にしません。

**補助指標の値は未報告です。** 採用する対象集合・window・式をownerが決め、専用の
Attested Computationと入力/codeの固定、外部receipt、attester、coverage/真正性の確認を揃えてから
報告します。KGI-INTENTのattesterを、これらの別の式を検証した証拠へ流用しません。
[8つのKey Factor](../knowledge/factors/index.md)は既存のKF-01〜KF-08を候補として維持し、
KGI-INTENTのenabled_by、KPIへのobserved_by、既存Initiativeへのadvanced_byを結んでいます。
寄与は仮説で、因果関係を実証したものではありません。Experiment/Outcome、Decision/Risk/
Measurement Policyとの残る型付き接続は#52で続けます。
