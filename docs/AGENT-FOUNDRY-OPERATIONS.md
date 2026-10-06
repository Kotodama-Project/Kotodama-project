# agentの担当と実行の境界

新しいagentの数を増やす前に、既存の能力で利用者の未解決の仕事を完了できるかを確認します。
[責任索引](../governance/agent-registry.json)は、どの役割がどの知識領域を調べるかを示します。
索引の行はagentの起動、実行中のinstance、本人性や権限の証拠にはなりません。

| 対象 | 担当する契約 |
|---|---|
| 知識を扱う論理role | [agent responsibilities](../knowledge/governance/agent-responsibilities.md) |
| 担当領域と評価・rollbackの候補 | [責任索引の監査](CONTROL-PLANE-AUDIT.md) |
| 実行instanceの登録・lease・停止・再開の記録 | [既存lifecycle契約](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md) |
| 分担と独立検証の計画 | [既存swarm契約](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md) |
| Taskとrevisionの状態 | [既存Task owner](../runtime/discord-template/docs/TASK-OWNER.md) |

索引v2の`planned`・`candidate`・`disabled`・`retired`は設計上の区分です。
`active`、`bounded_execute`、runtime evidence、promotedの宣言は拒否します。
各行は既存ID、canonical role、Concept参照、読取領域、禁止操作、評価gate、
rollback候補を持ちます。出力はread_onlyまたはproposal_onlyで、実行のgrantではありません。

具体的な不足が確認されたら、入力と受入条件を限定して実装・否定試験・独立reviewを行います。
実行を有効化する判断は既存ownerが、対象revision・grant・lease・停止経路に束縛して行います。
索引へ行を追加したことや静的なPASSで、その判断を代替しません。

改善・統合・退役の提案も[保守planner](CONTROL-PLANE-OPERATIONS.md)から得られますが、
Taskを作成・実行しません。既存のデータ、履歴、rollbackを保ち、未確認の実状態を
`healthy`や`authorized`として表示しません。公開面は`NO_GO_UNPUBLISHED`です。
