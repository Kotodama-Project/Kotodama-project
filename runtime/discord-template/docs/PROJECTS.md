# Projectの保存と訂正

選択済みlocal ownerのSQLiteに、継続するProject briefを保存します。
既存のTask、Source、eventsと同じinstallationを使い、Projectだけの作成・訂正では
Taskを作成・更新・実行しません。作業の入口は[Project hub #385](https://github.com/Kotodama-Project/Kotodama-project/issues/385)です。

## 設定と共通操作

既定は全操作が無効です。利用する操作だけを設定し、runtimeを再起動します。

```json
{"projects":{"operations":["read","create","inspect","correct"]}}
```

認証済みloopback controlの`action: "project"`を使います。actorは既存operatorで、
Projectの所有者と一致する必要があります。公開HTTP endpointを追加しません。
選択済みownerがremoteの場合は未対応として拒否し、localへの代替保存は行いません。

| operation | 入力 | 結果 |
|---|---|---|
| `create` | `request_id`, `name`, `source: {key, revision}`, `brief` | ownerが発行したProject ID、revision 1、digest |
| `read` | `project_id` | 保存済みbriefと現在のrevision/digest、出典参照 |
| `inspect` | `project_id`, `expected_revision`, `base_digest`, `source`, `reason`, `brief` | 変更箇所、削除される制約・受入条件。保存しない |
| `correct` | inspectの入力と`request_id` | 原依頼参照を保った新revisionと訂正event |

すべてに`actor`を含めます。`source`はそのinstallationに既に保存されたDiscord Sourceの参照です。
現在の確定版と閲覧権限を確認し、未登録の本文や任意ファイルパスから自動取込しません。
対象は設定済みtext/result channelとvoice room（voice poolを含む）です。音声Sourceは
元版と現在版の発話者の明示opt-outを毎回確認し、途中の取消も保存前に拒否します。
同じactor・roomのDiscord閲覧権限は操作ごとに一度照合し、各Sourceの版と閲覧範囲は個別に検査します。
`controlCommand`は認証済みloopbackの`/v1/project`へProject操作を送り、入力を1,500,000 bytesまでとします。
既存`/v1/command`は引き続き200,000 bytesまでで、本文受信前にも上限を検査します。
契約内のUnicode・JSON escapeを切り捨てず扱います。
書込みの`request_id`は呼出側で保持します。応答が不明なときも同じ内容・同じIDで照会し、
新しいIDによる重複作成を避けます。同一IDの異内容は拒否します。

Nodeからは既存の`controlCommand`を使えます。

```js
import {loadConfig} from '../src/config.mjs';
import {controlCommand} from '../src/runtime.mjs';
const config = await loadConfig(process.env.KOTODAMA_CONFIG);
const result = await controlCommand(config, {
  action: 'project', actor: config.discord.operators[0],
  operation: 'read', project_id: 'ref/project/SELECTED_PROJECT_ID'
});
```

## 情報と履歴

briefは[Project v1](../../../docs/PROJECT-HUB-VIEW.md)と同じ
`outcome`, `in_scope`, `out_of_scope`, `constraints`, `acceptance`, `unknowns`です。
文字数はUnicode code pointで検査し、上限超過を切り捨てません。
空配列は記録がない状態で、実行可能や該当なしを意味しません。

Project ID、owner参照、原依頼参照はownerが発行します。訂正はbrief全体を置換し、
旧版を保持して理由・訂正Source・前後digestを既存eventsへ記録します。
最初の版は一つのProjectにつき32 revision、継承するSource参照32件までです。
上限に達した際は明示拒否し、古い履歴の削除や自動圧縮は行いません。
版の保存、現在版の変更、再送記録、eventは一つのSQLite transactionです。
同じrevisionでもdigestが違う入力、古い版への新規訂正、別actorの操作は拒否します。
再送結果は保存時の版と現在版を区別します。再送でも現在の認可を省略しません。

原Sourceが後に訂正されても原依頼の参照は変えません。現在の閲覧権限・withdrawalと
元版の閲覧範囲を照合し、以前のSourceへの権限失効を新しいSourceで迂回できません。
設定・owner・installation・保存場所の変更は再確認します。
認可待ちが期限を超えた操作は、その後応答が戻っても保存へ進みません。

## 実装範囲と次の接続

この版はactor所有のProject briefだけを扱い、`task_refs`は空です。
Task参照の追加、成果・担当・完了の集約、共有参加者、Projectの取消・削除、
動的役割生成、GUI操作、provider実接続は後続です。
既存TaskのSQLite本文digestを、swarm入力の`context_digest`へ流用しません。

既存Requirements Gadgetの`objective`と`deliverable`は別の情報です。
Projectの`outcome`へ自動要約したり、件数・文字数を切り捨てて移したりしません。
GUIとagentのadapterはこの共通操作を呼び、別の保存先やTask ownerを作らない方針です。

検証は`tests/project-owner.test.mjs`と`tests/project-control.test.mjs`で、
合成Source、実SQLite、実loopback HTTP、再起動、再送、旧版、取消された権限を扱います。
実Discord・実モデル・Public Betaの受入とは別です。
