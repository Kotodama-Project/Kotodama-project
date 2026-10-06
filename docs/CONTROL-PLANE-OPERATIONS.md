# 知識と責任索引の保守

監査のfindingから、担当role・根拠・次の確認を含む修正候補を作ります。
実際のIssue作成、Task割当、ファイル変更、agent起動は行いません。
公開面はread-only/candidate-only、`NO_GO_UNPUBLISHED`です。

| 関心事 | 正本・索引 | 説明 |
|---|---|---|
| Goal、KGIと候補の意味 | [公開知識](../knowledge/project/success-model.md) | 別の戦略OKFを作らない |
| 知識内容と配送条件 | [profile](../knowledge/profile.yaml) | [Knowledge base](KNOWLEDGE-BASE.md)のproducerが検査 |
| ファイルの分類 | [knowledge registry](../governance/knowledge-registry.json) | 内容やTask状態の正本ではない |
| 役割の担当 | [agent responsibility index](../governance/agent-registry.json) | [役割の境界](AGENT-FOUNDRY-OPERATIONS.md)。実行の登録ではない |
| 監査の条件 | [audit policy](../governance/audit-policy.json) | cadenceは候補で、自動実行を設定しない |

```sh
python -B tools/audit_control_plane.py --as-of 2026-10-06 --format json
python -B tools/plan_control_plane_maintenance.py --as-of 2026-10-06 --format markdown
python -m unittest tests.test_control_plane tests.test_control_plane_registry tests.test_control_plane_planner -v
```

監査は[有限の読取りと分類](CONTROL-PLANE-AUDIT.md)を検査します。planner v2は
findingをseverityと内容digestで安定して並べ、既存Conceptの参照を付けます。
古い日付、未知の参照、権限違反は候補の理由として残します。警告の処理はAI-LIBRARIAN、
権限境界はAI-AUDITOR、未分類の問題はAI-CHIEFへの検討候補です。role名は起動やgrantではありません。

運用者は原資料を確認し、既存Issue・Workと重複しない修正範囲を選びます。
根拠を更新して同じ監査を実行し、別の担当が変更を確認します。日付だけの更新や
分類閾値の引下げでfindingを消しません。未確認は未確認のまま残します。

任意のCIは関係pathの変更時だけ監査とfocused試験を行い、hash付き依存を使います。
必須チェックの全体unittestを重ねず、branch protectionも変更しません。
移植元は公開#64 `e0460b3`のplannerと運用文書です。旧KGI/KF routingを現行Conceptへ
向け直し、lifecycleや実行権限を担当索引へ移す記述は採用していません。
