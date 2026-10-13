# 現在Sourceと保存済みPlanを有限に辿る

[#372](https://github.com/Kotodama-Project/Kotodama-project/issues/372)のreader sliceです。
既存Task ownerに束縛されたSourceから、Project・任意Phase・Requirementの候補祖先を
辿り、元の制約・行・Unicode spanと逆参照を返します。実ownerのTaskと、anchorを指定した
保存済みruntime executionPlanは別の型として検査します。従来のnormal一roundに加え、
明示local executorの完了記録は共通runtime verifierで修復・依存releaseまで読み戻します。
組織Plan、組織Task台帳、全8階層の対応や実行認可を作りません。

## 独立CLI

Python 3.12と既存のknowledge/Task runtime用依存を入れたsource checkoutで使います。
wheelの`kotodama-core`入口への追加はこのsliceに含みません。

```sh
python -B tools/hierarchy_trace.py --root KNOWLEDGE_ROOT --owner OWNER_JSON --input CURRENT_INPUT_JSON --request TRACE_REQUEST_JSON
```

`--root`は取得済みの知識とSourceのcheckout、`--owner`はoperatorが明示した実Task ownerです。
CLIはTask登録・Source取込・owner変更・coordinator実行をしません。既存knowledge CLIのparserも
変更しません。結果は一つのUTF-8 JSONと末尾LF、拒否はstderrへJSONを返しstdoutを空にします。
終了値は`TRACED_CANDIDATE`が0、必須未解決による`BLOCKED`が3、入力や現在束縛の拒否が2です。
0はreaderの候補照合結果であり、実行・採用のGOではありません。
module APIは`trace_current_refs(bundle, input_payload, owner_path, request, clock=...)`です。
CLIは`with_bytes=True`で最終frameを検査前に準備し、検査後に再serializeせずそのbytesをstdoutへ返します。

requestの全fieldは`version`、`root_id`、`nodes`、`references`です。次は形の説明で、Source keyや
receipt hashは実owner・実artifactから別途指定します。名前から取得先を探しません。

```json
{
  "version": 1,
  "root_id": "REQ-EXAMPLE",
  "nodes": [
    {"path": "work/project.md", "source_key": "CURRENT_SOURCE_KEY", "source_revision": 1},
    {"path": "work/requirement.md", "source_key": "ANOTHER_CURRENT_SOURCE_KEY", "source_revision": 1}
  ],
  "references": [
    {"kind": "owner_task", "id": "EXISTING_TASK_ID", "revision": 1, "mandatory": true}
  ]
}
```

Source keyは64桁の小文字hexで、入力内の最新revisionが必要です。nodeのpathはroot内の
明示した通常fileに限ります。全file bytesはSource本文と一致し、全KB入力とnodeの現在hashが
既存ownerの`source_checks`にも含まれる必要があります。未宣言Sourceを自動追加しません。

## Sourceに明示した複数親

既存テンプレートの単数`parent_ref`を維持し、具体的な候補Sourceにはreader opt-inとして
`parent_refs`も使えます。既存schema・テンプレートやowner入力のfieldは変更しません。

```yaml
template_kind: requirement
id: REQ-EXAMPLE
status: draft
parent_refs: [PHASE-A, PHASE-B]
task_context:
  constraints: [本文に一度だけ記載した制約]
  need: 本文に一度だけ記載した必要事項
  acceptance: [本文に一度だけ記載した受入条件]
```

同じSourceに`parent_ref`と`parent_refs`を併記すると拒否します。親は現在入力内の安定IDで
指定し、title、slug、file名、depends_on、all_ofや本文の類似から推定しません。
Projectは親なし、Phaseの親はProject、Requirementの親はProjectまたはPhaseです。
各辺は元のYAML scalarの行/spanに、制約・need・acceptanceは同じ本文の一意な箇所に束縛します。
このopt-in宣言ではYAML aliasを受け付けません。
同文でも別Source/spanの条件は残します。文書は`draft`候補のままです。

根からの全必須祖先が列挙されていなければ拒否します。未使用node、重複ID、未知親、循環、
kind alias、withdrawal、上限超過も全体拒否です。到達した共有祖先を短い経路で見た場合も
別の長い経路の深さを省略しません。構造の閉包と逆参照は、仕事の分解・実行依存の辺ではありません。
`task_context.frontier`は別の既存planner責務なので、このreaderは未解決としてcontextを止めます。

結果の`nodes`・`edges`・`closure`・`reverse_refs`は再生成可能な候補投影です。
`context_candidate`は原意・訂正・既存typed目的参照・未知・期限を元Task objectiveから保持します。
`dispatch_ready=false`と`producer_bridge=not_connected`を返します。既存producerはまだ単数親を
再導出するため、この投影を無検証でその入力に差し込みません。複数親を実配布へ接続する差分は次の単位です。

## Taskとruntime Planの別扱い

`owner_task`は既存`OwnerFile.read_task`と`validate_input`でTask ID/revision・全context digest・
現在Source・期限を照合します。文書Taskテンプレートやopaque参照を実Taskへ昇格しません。
`organization_plan`、`Plan`、`Task`等の未実装kindは理由付き`unresolved`です。
必須ならcontext全体をnullにします。任意未解決でも実行認可を与えません。

保存済みPlanには次の明示参照を追加します。

```json
{"kind":"runtime_plan","id":"EXISTING_TASK_RUN_ID","revision":1,"mandatory":true,"receipt_sha256":"SAVED_RECEIPT_SHA256"}
```

run IDは実Task ID/revisionから既存の計算式で検査します。ownerが指定するstorageとactive_home内の
そのrunだけを読み、globや履歴の自動探索はしません。`receipt.json`の外部anchor、全artifact manifest、
元owner JSONのbytes、現在payload、specification、scheduler Plan、保存execution、実workerとcriticの
入力・結果・dispatch digestを照合します。`owner_input_sha256`はowner JSONのfile hashです。
入力オブジェクトのcanonical digestやSource hashとは分けます。

`initial_plan_digest`は仕様Planのdigestです。runtime scheduler Planのdigestは別に計算し、
`specification_digest`と`execution_plan_digest`で両方を返します。criticのtemplate digestと
reportsを追加した実入力digestも区別します。既存all-assigned evidence validatorを使い、実Source spanの
reportとcriticを検査します。根の必要事項・受入・祖先制約が保存worker入力の和集合とcritic入力にあることも
検査します。caller Planだけ、staged receiptだけ、別Task/revision、入力・結果の差替えはpositiveになりません。

従来のsynthetic receiptはversion 2・repair profile 1のnormal一roundをfileだけで検査します。
`revision_scope=task_run`、`status=saved_artifact_consistency`を返し、DBは開きません。
この旧経路のrepair extension、live model証拠、current learning decisionが必要なreuse runは未解決/拒否です。
旧経路のlive取消・進捗・finalization checkpointのDB状態は`not_observed`です。
外部anchorと保存fileの一致は、独立署名・改竄不能storeや実成果の意味的正しさを証明しません。

### local executorのnormal・repair・dependency履歴

初期critic templateと実scheduler Planに束縛された`local_executable_fixture`では、
保存receiptの外部anchorに加え、既存DBのfinalization checkpoint・最終receipt・execution snapshotを
照合します。元の`execution.sqlite`・WAL・SHMはbounded binary readだけで読み、専用の一時copyで
schemaを検査してから`SwarmState`を開きます。元DBの新規作成、schema追加、journal更新は行いません。
DB欠落、途中変更、保存取消、未完了checkpoint、別receiptは拒否です。復旧や追加dispatchはしません。

`terminal_evidence`と`saved_executor`が、初期worker・critic、round 2の追加worker・critic、
依存releaseとprerequisite reviewを検証します。typed receiptを旧4-key receiptへ変換せず、
実stdin、schema、process identity、runtime receipt、rollout、現在のmaterial/owner policyを
既存の共通verifierで照合します。根の必要事項・受入・祖先制約が保存worker入力と各critic入力へ
届いていることも確認します。

この経路は`status=saved_artifact_and_execution_consistency`、`execution_mode`、`rounds`、
`finalization_checkpoint_digest`を返します。各`dispatches`に入力/結果とruntime receipt/rolloutのhash、
実attempt/epochを残し、`repair.retained`と`repair.new_dispatches`で保持した元結果と追加実行を示します。
`dependency`は検査したrelease certificateと既存preaccepted jobの対応です。
`live_execution_state=completed_cut_checked`と`current_cancellation=not_cancelled_at_read`は
読取区間の完了記録を確認した意味で、将来の取消や稼働中processの継続監視ではありません。

最終frameをserializeしてから、現在Sourceと新しいDB cut・取消を再確認します。そのcallbackの後に
共有executorが保存proof・actor・owner bytesを最後に照合し、検査後の再serializeはしません。
完了履歴は実行budgetのdeadline後にも読めます。新しい実行枠は作らず、現在owner/Sourceの失効、
Conceptの期限、readerのquery deadlineは引き続き拒否条件です。

どちらの経路もorganization Plan revision、実provider/model、Task完了や成果採用の証明ではありません。
normal runに保存された`learning.json`は`candidate_only`です。readerはcurrent decision storeを開きません。
ownerにlearning reuse grantがある場合やSourceがreuse proposalを宣言する場合は
`CURRENT_DECISION_NOT_OBSERVED`でcontextを止め、保存済みの許可を
現在の許可に読み替えません。成果採用、human判断、Task完了は元のownerへ返す別責務です。

## 検査・上限・未受入

入力・応答は各256 KiB、既存Sourceは10件/各12,000文字、選択statementは32 spans以内です。
この構造sliceは最大8nodes、深さ2辺、一nodeの親2件、全16edges、typed参照8件です。
保存artifactは32files、合計2 MiB以内です。上限超過を切り詰めて部分成功にしません。
local executorのJSON manifestにもこの上限を適用します。別の内部process proofは既存executorの
最大8jobs・各2 MiB・最大80のpin対象fileに制限し、共通verifierの範囲を広げません。
DB/WAL/SHMの一回の物理cutは合計8 MiB以内です。一時copyは応答または拒否の後に削除します。
queryは10秒のlogical deadlineを各境界で検査します。blocking OS readのhard timeout保証ではありません。

Bundleの全現在bytes/構造とownerの全Source checksを開始・応答直前に再照合します。node/artifact bytesと
保存proofで使ったactorも再照合し、Conceptの期限はBundle作成時のboolではなく毎回の実clockで評価します。
同size/mtime復元、knowledge入力への追加・選択Sourceの削除/rename、途中変更、ownerやactor取消をcacheで免除しません。
別の未宣言文書を親へ自動発見する機能はありません。複数fileとownerの検査は観測区間であり、
filesystem全体の原子的snapshotや、最後の検査の後に起きる変更を保証しません。

```sh
python -B -m unittest discover -s tests -p test_knowledge_hierarchy_reader.py -v
python -B -m pytest tests/test_task_swarm_hierarchy_executor.py -q
```

専用fixtureは実既存coordinatorに同owner NとN+1の保存worker・critic・receiptを作らせ、readerの前後で
file bytesとdirectory entriesを比較します。fixtureの明示owner受入・coordinator書込みと、readerの0 writesを分けます。
source checkoutでの局所試験は、Windows、installed wheel CLI、公開current CI/main、実service・人の受入の代わりではありません。
local executor fixtureではnormal、DocBだけのround 2修復、依存releaseを実processで作り、readerでは
新規process 0・元DB/WAL/SHM不変・失効/改変/途中取消の拒否・実行deadline後の履歴読取を確認します。
本readerだけで#372/#347の全体受入や全8階層の実行経路の完成を認定しません。
