# Goalと測定の型付きConcept

#52の実装は、Conceptの契約、既存IDの定義、計算とattestationを分けて統合します。
既存のOUT-INTENT/OUT-LOCAL、KGI-INTENTと8つのINIT IDを個別Conceptへ束縛し、
load_bundleの既定profile検査と生成graphへ接続しています。未定義の参照を持つbundleは
context生成前に拒否します。計算のreceipt、補助型の全定義、採用した測定値は後続です。

## 一つのConceptが一つの定義を持つ

OKFのConcept IDは引き続きMarkdownの相対pathです。その`kotodama.strategy.id`に、
`KGI-INTENT`などの既存の意味上のIDを対応付けます。別のregistryを手書きの正本にしません。
Goal、Outcome、Metric、Key Factor、KPI、Initiative、Experiment、Decision、Risk、
Measurement Policy、Attested Computation、Evidenceを扱います。

```yaml
type: Metric
kotodama:
  # 他の必須producer fieldsは既存Conceptと同じ
  strategy:
    id: KGI-INTENT
    adoption_status: candidate
    measurement_role: product_outcome
    baseline: unknown
    target: not_adopted
    deadline: not_adopted
    measurement_window: not_adopted
    exclusion_policy: not_adopted
    relationships: []
```

これは必須共通fieldを省いた形の説明例です。完成したConceptとして検査を通すものではありません。
`strategy_template(type, id)`はこの拡張だけを作ります。InitiativeのhypothesisはTODOを
埋める必要があり、介入・期待する変化・反証条件が無い定義はsemantic検査で拒否します。

## 参照・関係・採用の分離

`strategy_model(concepts)`は同じbundleの定義から一時的な索引を組み立て、既存goal_refs、
kgi_refs、initiative_refsとfactor_refsを検査します。Goal refsはGoal/Outcome、KGI refsは
product_outcomeのMetricだけです。control_sloやsupporting_kpiを製品成果のKGIとして受理しません。
Task ownerから取り出した参照だけも`strategy_reference_issues(record, index, path=...)`で検査できます。
Taskの状態、grant、成果の採否はコピーせず、ownerに残します。

catalogのstrategyとgraphのdefinition_conceptで、意味上のIDから同じMarkdownへ戻れます。
新しく独立した重要Goalがリンクされている場合も、任意の文脈より先に場所を確保します。
必須文脈が収まらなければneeds_resolutionとなり、既定の12 Concept上限は広げません。

型付き関係はmeasured_by、computed_by、enabled_by、observed_by、advanced_by、tested_by、
produces、governed_by、Decisionのadopts/revises/pauses/rejects、Riskのmitigatesです。
型の違う結び方、未定義ID、重複定義/関係、循環を拒否します。関係の相手は通常のMarkdown link
でも結び、専用toolがなくても辿れるようにします。エラー時は使用可能に見えるgraphを返しません。

数値のbaseline、target、deadline、measurement window、exclusion policyはこのcontractでは
採用しません。候補の構造が正しいことは、定義の独立検証・実測・per-run attestation・人の受入を
代替しません。仮説の欄があることも、因果関係を実証したことにはなりません。

標準の根拠は[固定したOKF v0.2仕様の§10](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/82a483de8a381f1ed25b9dfe1dc5622622afff55/okf/SPEC.md#10-attested-computations-concept)です。
Attested Computationは別Conceptにし、runtime/typed parameters、executor/receipt、deterministic
attesterを持たせる後続部分へ接続します。receiptは実行証拠のownerに置き、KBのCompany truthにしません。
