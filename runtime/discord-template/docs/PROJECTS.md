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

controlのBearerはlocal operator用の資格情報です。`surface`は認証情報ではなく、
Dots adapterが追加制限を選ぶ固定値です。MCPの呼出引数からは変更できず、
GUI adapterは固定した`read`／`inspect`だけを送ります。本人確認の制限対象となる
clientにcontrol tokenやoperatorのconfig・stateへの直接アクセスを与えない構成が前提です。
loopbackと`0600`は同一OSユーザーのプロセスを隔離しません。computer／shell接続を
併用する場合のcredential・filesystem境界は配備先で別途検証が必要で、MCP経路の
合成テスト成功だけではその隔離を証明しません。

| operation | 入力 | 結果 |
|---|---|---|
| `create` | `request_id`, `name`, `source: {key, revision}`, `brief` | ownerが発行したProject ID、revision 1、digest |
| `read` | `project_id` | 保存済みbriefと現在のrevision/digest、出典参照 |
| `inspect` | `project_id`, `expected_revision`, `base_digest`, `source`, `reason`, `brief` | 変更箇所、削除される制約・受入条件。保存しない |
| `correct` | inspectの入力と`request_id` | 原依頼参照を保った新revisionと訂正event |
| `link_task` | `project_id`, `expected_revision`, `base_digest`, `source`, `reason`, `request_id`, `task_id`, `expected_task_revision` | 同じownerの既存Taskを版付きで関連付ける |
| `unlink_task` | link_taskの入力から`expected_task_revision`を除く | 参照を外す。Task自体は取消・削除しない |
| `read_task` | `project_id`, `task_id` | 関連付けたTaskの現在状態と照合結果、成果の報告済みメタデータ |

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

briefは[Project情報契約](../../../docs/PROJECT-HUB-VIEW.md)と同じ
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

## Dotsから同じProjectを扱う

[既存Dots plugin](../dots-plugin/README.md)には、`projects.operations`と
`dots.projectOperations`の両方に設定したProject toolsだけを追加します。
Dots側も既定は空配列です。端末用Project操作や既存のDots返信権限を、モデルへの
Project操作許可として流用しません。actorは設定から固定し、tool引数で変更できません。

Projectのread/inspectは、両方の操作設定とinstallationの設定済みtext/result channel・
voice room内で、そのactorが所有・閲覧できるSourceを使います。
作成・訂正はさらに、`dots.channelIds`内の現在pendingな相談のSource・版へ束縛します。
`project_prepare_change`で候補全文を提示し、依頼者本人がDiscordの確認buttonで
正確な内容を許可した後に、`approval_id`付きcreate/correctで同じownerへ保存します。
モデルが自分で許可するtoolはありません。候補にはrequest_id・Source・操作・対象版も含めます。
許可は5分で失効し、再送で期限を更新しません。相談の取消・訂正、候補の差替え、
いずれかの権限失効は、保存直前にも検査します。候補は依頼ごと8件、未expired全体128件までです。
確認の配達が不明なら自動再送せず、本人の`/kotodama project_review`で同じ候補を再確認できます。

Dotsから送った処理は`surface: "dots"`で接続元を固定し、Dotsの無効化・actor変更を
保存直前にも確認します。このmarkerはoperatorの権限に制約を加え、権限を増やしません。
MCP呼出しの取消はloopback接続から保存前の検査まで伝播します。保存後の応答紛失では
receiptを消さず、許可・相談が有効な間は同じID・同じ内容で照合します。取消・期限切れ後の
書込再送は拒否し、Project readまたはlocal operatorで照合します。新しいIDで自動再実行しません。

## 既存Taskとの関連付け

利用する場合だけ`projects.operations`へ`link_task`、`unlink_task`、`read_task`を加えます。
Dotsから扱う場合は同じ操作を`dots.projectOperations`にも加えます。
関連付け・解除は[Project候補の本人確認](../dots-plugin/README.md#projectの目的と条件を扱う)を通し、
正確なProject版・Task ID・理由・Sourceと`request_id`へ束縛した`approval_id`で保存します。
link_taskではTask版も固定し、unlink_taskでは保存済みProject参照を対象とします。
新規Projectはv1・空の参照で作成し、最初の関連付け時に新revisionをv2へ進めます。
v2のlocal参照は`{adapter: "discord_local_task_v1", task_id, revision}`です。
swarm入力の`context_digest`とは区別し、TaskのSQLite本文digestを代用しません。
参照はProject snapshot・digest・既存訂正履歴に保持し、別のTask台帳を作りません。
最大50参照、Task IDは重複不可です。再関連付けには現在のTask版を明示します。

TaskとProjectのactor・room・選択済みownerが一致し、Taskの元Sourceと現在の文脈Sourceも
閲覧可能である必要があります。元版・現在版の音声opt-outと、認可中のcontext変更も確認します。
Taskの同じrevision内で担当・context・結果が変わる場合があるため、状態照会ごとに再読します。
Projectの通常readは記録済み参照だけを返し、Task本文・現在状態をまとめて複製しません。

`read_task`は`current_task_revision`、`owner_state`、`resolution`を返します。
参照版が古ければ`revision_changed`、Sourceが変われば`source_changed`と表示し、
新しい成果を自動採用しません。成果メタデータは版とSourceが一致する`needs_review`に限り
件数・検査の報告状態を返します。本文・絶対パスは返さず、`artifact_readback: "not_run"`、
`completion: "not_observed"`を維持します。確認待ちを完了と呼びません。
再起動時のTask状態は既存Storeの回復処理に従い、Projectから再実行しません。

## 実装範囲と次の接続

既存[Requirements GadgetのProject表示と候補検査](../../codex-task-bridge/README.md)は
同じlocal ownerへ接続します。GUIは参照と変更候補の検査までで、保存やTask実行を行いません。
成果の内容readback・要件ごとの充足・完了集約、共有参加者、Projectの取消・削除、
動的役割生成、実Dotアカウントによる受入、provider実接続は後続です。

既存Requirements Gadgetの`objective`と`deliverable`は別の情報です。
Projectの`outcome`へ自動要約したり、件数・文字数を切り捨てて移したりしません。
[既存GUIのbridge](../../codex-task-bridge/README.md)は、明示されたprincipal・Source・
稼働source版に束縛して、この共通操作のread/inspectを呼びます。目的・条件を編集して
変更候補を検査できますが、保存やTask実行は行いません。別の保存先やTask ownerは作りません。

検証は`tests/project-owner.test.mjs`、`tests/project-control.test.mjs`、`tests/project-task.test.mjs`で、
合成Source、実SQLite、実loopback HTTP、再起動、再送、旧版、取消された権限を扱います。
実Discord・実モデル・Public Betaの受入とは別です。
