# Task loop executorのdormant primitive

Refs #375。会話から意図・仕事・成果へつなぐため、有限local fixtureの
Source宣言、実入力とprocess/rollout証拠の共通型を用意します。
現在のloop admission、TaskBackend、CLI、stateは変更しません。
`NO_GO_UNPUBLISHED`。このprimitiveだけで新executorを実行できません。

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
DBにstdin前のprocess identityをcommitするwriterはまだ接続していません。

technical verifierはraw input、pipe-write marker、8 artifact digests、schema、command、
process、thread/turn、job固有sessionsのrollout/resultと最後のcurrent bytesを再読します。
入力は256KiB、1 invocationの証拠読取は2MiB以下。guardの元例外を維持します。
native permission/profile証明をtechnical receiptへ付けたものは拒否します。
fixtureのLuna/max labelは実model/providerの利用・品質を証明しません。
親input hashとOS pipe書込み完了は子のconsumption/model理解ではありません。

既存native `verify_runtime` のdefault7/strict8とTaskBackend.synthetic=Falseは不変です。
現在loopのnon-synthetic拒否も維持します。B1のwriter/全saved readersへのatomic接続、
hierarchy saved-only認証、Cの製品CLI・資料取得/独立critic/有限repair・予算不足の受入は未完。
取消に成果proof不足を新たな受付条件として足す接続も、このprimitiveでは行いません。
既存owner/Source認証の拒否境界は変更しません。
