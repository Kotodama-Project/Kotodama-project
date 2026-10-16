# Projectの最小情報契約とread-only view

[Project hubの設計](AGENT-HUB-DESIGN.md)の最初の実装。
`tools/project_hub.py` は、operatorが選んだProject briefと既存Task ownerを照合する
ローカルCLI。Task作成・更新・取消・dispatch・Project永続serviceは持たない。
作業の継続入口は[Issue #385](https://github.com/Kotodama-Project/Kotodama-project/issues/385)。

保存と訂正の限定経路は[Discord templateのProject owner](../runtime/discord-template/docs/PROJECTS.md)へ
追加しました。同じbriefを既存installationのSQLiteへ保存します。このPython CLI自体は
引き続きread-onlyで、NodeのTask本文とswarm入力digestは別の契約です。

## 最小情報契約 v1 / v2

Project JSONはownerから得たsnapshotまたは候補入力であり、このファイルを置くだけでは
正本や権限にならない。Project IDは選択済みownerが発行した安定IDを使う。

| field | 制約・既存情報との対応 |
|---|---|
| `version` | 整数1または2。Project契約の版 |
| `project_id`, `revision` | 安定参照、1以上の整数。名前やchat IDから再生成しない |
| `owner_ref` | Projectの責任主体への参照。Task ownerとは独立 |
| `name` | 表示名、200文字以内 |
| `original_ref` | 原依頼の版付き参照。本文を要約で置き換えない |
| `brief.outcome` | 欲しい成果。project templateのOutcome |
| `brief.in_scope`, `brief.out_of_scope` | templateのBoundary |
| `brief.constraints`, `brief.acceptance` | 必須条件と受入条件。各20件以内 |
| `brief.unknowns` | 不明点。推測で埋めず文字列として明示する |
| `task_refs` | 最大50件、Task ID重複不可。v1は`task_id`, `owner_ref`, `revision`, `context_digest`。v2は以下のadapterを明示 |

v2は`discord_local_task_v1`（`adapter`, `task_id`, `revision`）と、
`swarm_execution_v1`（`adapter`とv1の4項目）を区別します。
localのTask本文digestをswarmのcontext digestへ変換しません。
Node ownerは初回Task関連付け時にv2へ進め、元のv1履歴を保持します。
このPython CLIはlocal参照を認識しますが、状態は未観測として返します。
local参照に`--task`で任意ファイルを与えてもOwnerFileへ渡さず拒否します。
v1とv2のswarm参照だけが、既存OwnerFileの照合対象です。

各brief配列は必須だが空でも候補を表示できる。空配列は「記録なし」であり、
「該当なし」や実行準備完了を意味しない。この版では該当なしの確定操作を扱わない。
participant、phase、artifact、資源、profile、学習は後続契約で扱う。
既存templateとTaskのbytesは変更せず、参照で結ぶ。

## 操作

入力はoperatorが既に閲覧可能なローカルファイルを指定する。
Project文書内の参照からファイルパス、URL、実行先を自動探索しない。
`--task` は既存Taskごとに繰り返せる。

```text
python -B tools/project_hub.py view --project project.json \
  --task task-00000000-0000-4000-8000-000000000001 owner.json task-input.json
python -B tools/project_hub.py inspect-change --project project.json --proposal change.json
```

Taskは既存`OwnerFile.read_task`と`validate_input`を通す。Task v1/v2が対象で、
任意のTask owner adapterではない。v2の原意・訂正・制約・未知・受入条件はobjectiveを
そのまま返す。Sourceはkey/revision/digestを返し、本文は再複製しない。
ProjectとTaskのowner参照、revision、context digestが一致しないTaskは解決しない。
ownerと入力を再読して観測中の変更も検出する。ただし複数ownerにまたがる原子的snapshotや
表示後の鮮度は保証せず、実行側はその境界で再確認する。

取消・停止済みTaskは既存ownerの`INACTIVE_TASK`として表示され、完了扱いにしない。
このowner APIでは取消と完了を区別して読めないため、履歴・成果・担当者は未観測とする。
失効は`EXPIRED_BINDING`、未選択は`PROJECT_OWNER_UNSELECTED`。
失敗したTaskの依頼本文は返さず、他のTaskは引き続き照会できる。
`unresolved_count`で不足を確認する。CLI終了0はview生成成功であり、Task解決や完了ではない。

## 訂正候補

change JSONのfieldは`version: 1`, `project_id`, `expected_revision`, `base_digest`,
`reason`, `source_ref`, `brief`。`base_digest`はviewが返す`project_digest`を使う。
変更対象はbrief全体だけ。原依頼参照・Project owner・Task所属・grantは変更できない。

同じrevisionでも内容digestが変わったbaseは拒否する。出力は変更field、削除された
constraints/acceptance、影響する全Task参照、理由と訂正sourceを含む候補。
文意が同じか、条件が弱まったかの意味判定は行わない。文字列の削除だけを明示する。
既存ownerが原意との対応・認可・現行版を再確認して訂正eventを記録する必要がある。
このCLIはrevisionを進めず、適用・承認・再計画を実行しない。

## 検証と次の境界

`python -B -m unittest discover -s tests -p test_project_hub.py -v` は実ownerファイルの
読取、取消、失効、旧版、owner違い、観測中の変更、条件削除の明示、書込なしを検査する。
このCLI単体では外部認証・tenant isolation・履歴台帳・provider実接続を検証しません。
ネットワーク公開には認証とアクセス制御を持つ既存入口への接続が必要。
local ownerの保存・訂正・既存Task関連付けは上記Node経路、GUIの表示・候補検査は
[既存bridge](../runtime/codex-task-bridge/README.md)で扱います。いずれも実サービスの受入は別途必要です。
