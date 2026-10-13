# Task loop executorの有限local実行

Refs #375。会話から意図・仕事・成果へつなぐため、有限local fixtureの
Source宣言、実入力とprocess/rollout証拠を既存Taskの閉ループへ接続します。
`TaskBackend(..., loop_mode="local_executable_fixture")`を明示したAPIとCLIで
normal/repair・依存release・terminal/resume/replay・learning originを検証します。
hierarchyの新mode対応は後続です。`NO_GO_UNPUBLISHED`。

`runtime/task_swarm/loop_executor.py` のpolicy/request/schema関数はpureです。
既存Task v2とsupplied planをcallerが検証し、objective.constraintsの現在spanから
`task_loop_executor` version1 / `local_executable_fixture` を明示します。
policyはcandidateでありowner承認・dispatch権限ではありません。
原意・全文訂正・祖先/全体制約とSourceの元offsetを保持します。

policyは4KiB以下かつ既存constraintの1000文字以下。Sourceは10件・各12,000文字、
parent/view/requestは各256KiB以下。素材は0..2件、現在Source全文UTF-8 bytesと
owner-pinned path/hash/bytesに1:1対応させます。exeは宣言済みPython fixtureだけ。
未知mode/強制素材隔離/nativeルート/半version/bool整数は拒否します。
現在ownerの権限・取消・期限を純導出の自己申告で検証したとは扱いません。

`loop_request` のmaterials専用laneは実viewに全文を持つ素材だけです。
policy宣言そのものはmandatory constraintとして全workerのinput.spansへ残るため、
DocAの専用laneからDocBを外してもinput全体からdescriptorが消えるとは限りません。
元の制約を削らず、専用laneの限定をOSの資料隔離へ読み替えません。

`loop_schema` は動的job/criterion/reportの閉じた形を導出します。
固定3報告のreview schemaを任意frontierへ流用しません。
成果意味・担当条件の全証拠・Source-root完全性は既存validator/callerの責務です。

`verify_loop_response` はcallerが認証したdispatch/attemptとcurrent guardを必要とします。
新外receiptは9keys。nested runtimeは初回freezeの3keysから検証後5keysへ固定し、
再読は既存SHAを更新して成功化しません。process pid/created_atとthread/turnは別です。
writerは既存Codex transportの`on_process`でpid/created_atを既存DBへcommitし、
ownerを再確認してからstdinを渡します。実processをnative thread identityで上書きしません。

technical verifierはraw input、pipe-write marker、8 artifact digests、schema、command、
process、thread/turn、job固有sessionsのrollout/resultと最後のcurrent bytesを再読します。
入力は256KiB、1 invocationの証拠読取は2MiB以下。guardの元例外を維持します。
native permission/profile証明をtechnical receiptへ付けたものは拒否します。
fixtureのLuna/max labelは実model/providerの利用・品質を証明しません。
親input hashとOS pipe書込み完了は子のconsumption/model理解ではありません。

初期critic templateのdigestを既存DBのplanへ束縛し、executor policy digestと
owner原bytesのSHA-256、選択worker/criticと現在actor bindingのdigestを保持します。
metadataを持たないrepair inspectionもこの同じbindingを使います。
`loop_executor_runtime.py`は各保存readerでpolicy・実stdin・process・rolloutを再読し、
検証済みの保存文書と8 artifacts・raw receipt・rolloutのSHAを有限集合として保持します。
最後のpolicy検査後にそのbytesを再読し、actor epoch/invocationとowner原bytesを再照合します。
同じ確認をwriterの公開直前と保存readerで使い、policy callback中の証拠・actor変更を
旧proposalやlearningを返す前に拒否します。再読の中でpolicy検査を再帰実行しません。
finalizerが書くcandidate/learning/executionと公開前のstaged receiptもこの集合へ追加し、
既存receiptの再読はDBに固定したreceiptのbytesと照合します。
active inspectionはafter-policyのcurrent guardで現在deadlineも検査します。
read-only DB copyのlive cancellation/cut確認も、このguardから最終bytes確認の前に行えます。
historical replayのobjective期限許容は維持し、owner/actorの有効期限は引き続き検査します。
Source検査とguardは観測境界であり、外部writerの将来の変更を禁止するlockではありません。

既存native `verify_runtime` のdefault7/strict8とTaskBackend.synthetic=Falseは維持します。
明示local mode以外のnative backendをこのloopへ入れません。fixture receiptのsyntheticは
ローカル技術検証を表し、model/providerの品質・費用・本番受入を表しません。
取消は成果proofやexecutor-policy保存fileの存在を追加条件にせず、既存owner/Sourceから
受け付けます。元attempt/deadline・取消・未知ACKの再dispatch拒否も維持します。

実fixtureの2資料は(5, unknown)から(5, 13)/(5, 23)へ5 callsで改善し、DocBだけを修復します。
budget 4は3 callsでunresolved/no learning、正anchor再読とterminal resumeは追加child 0です。
独立criticは実資料を別processで再計算し、固定13を別datasetの正解として扱いません。
source知識CLIは`task-input execute --executor-mode local_executable_fixture`を明示し、
ownerに束縛済みのcandidate/inputとworker/criticを渡します。
normal/learning共通のguard wrapperは`TaskBackend.synthetic=False`と具体的なtransport型を
保持して`produce_loop`/`review_loop`を呼び、KB検証を各呼出しの前後に残します。
学習付き候補は現在のreuse decisionを別途必要とします。設定・compileだけでadmissionしません。

installed coreでは既存owner/input/planに対し次のmodule入口を使います。
これはsource知識CLIのKB compilerをwheelへ含めるものではありません。

```sh
python -I -m kotodama_core.task_swarm.closed_loop --owner OWNER_JSON --input V2_INPUT --plan PLAN_JSON --executor-mode local_executable_fixture --worker worker-a --worker worker-b
```

両入口のfactoryはownerに束縛された現在のpolicyからexeを選びます。
任意exe pathや暗黙modeを追加せず、元の期限・attempt予算・actor・素材検査を維持します。
`--receipt-sha256`による再読は子を増やさず、`--resume-finalization`は既存checkpointの
再開条件を使います。不合格receiptはexit3で、成功へ読み替えません。
hierarchyから同じmodeを再読する受入、実モデルと利用者成果は#375の残件です。
