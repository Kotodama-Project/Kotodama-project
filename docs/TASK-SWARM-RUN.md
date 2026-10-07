# 既存Taskに束縛するswarm run（実装中）

#160の採用判断と#286の実装を、既存local Task ownerへ接続するための契約です。
入力・出力契約に加え、既存ownerへ束縛したPOSIXのtask-run入口を備えます。
Taskとgrantは作成・変更しません。Discord接続と実利用の受入は後続です。

実行時の[Task workerの読取範囲](TASK-SWARM-ISOLATION.md)は別helperで制限します。

## Task入力と固定plan

入力はversion、Task ID/revision、依頼、最大20件のacceptance、最大10件のSourceです。
Sourceはkey/revision、正確なUTF-8本文とそのSHA-256を持ちます。依頼4,000文字、
Source各12,000文字、全JSON256 KiBまでです。上限超過を切捨てて成功扱いしません。
公開fixtureは合成本文だけです。実運用のpayloadはprivate領域に置きます。

既存ownerが返す9項目のTask bindingを検査し、Task ID/revisionと全入力の
context digest、期限、active/validating状態を照合します。capabilityは
ref/capability/swarm_researchに限定します。この文字列や入力だけで権限が発行される
わけではありません。Node側で本人・現在grant・Sourceアクセスを照合する接続は後続です。

planはfacts、counterpoints、optionsの3 workerと、3報告を依存先に持つ独立review
の4 jobです。N=6、C=3、V=1、depth 1、期限は既存bindingの時刻を固定し、
残り1,260秒より長ければ拒否します。再試行で期限を延ばしません。同じTask ID/revision
は同じrun IDとなり、planの不変性とclaim排他は既存SwarmStateが所有します。

## 報告と独立レビュー

workerの報告はsummary、claims、conflictsを持ち、各claimはsupported/inference/unknown
を区別します。supportedにはTask入力中のSource key/revision、Unicode code point単位の
start/end、完全一致するquoteが必要です。別の版や本文・範囲違いを拒否します。
引用が一致しても意味の正しさやSource本人性を証明したとは扱いません。

独立verifierは依頼・acceptance・資料を含む全Task入力のcontext_digestと、正確な3報告の
digestに束縛され、C1〜C4とすべてのユーザー条件について
passed/failed/blocked/not_runと証拠位置を返します。証拠は実在するjob/claim番号です。
passedには証拠が必要で、C4は3報告すべてを参照します。未検査・拒否にはgap_reasonを
残します。古い報告のreview、条件抜け、重複、無いclaimへの参照は拒否します。

C1は依頼への回答、C2は主張の根拠、C3は推測と事実の区別、C4は3報告の食い違いの明示です。
validatorはverifierの身元や独立した実行を証明しません。controllerが別の実行receipt、
current binding、全criteria passed、各jobの受入を照合して初めて同じTaskへneeds_reviewを
返します。構造が正しいだけ、報告件数だけ、quiescentだけでTask完了にしません。

## POSIX Task runner

runtime側ownerがprivateなowner JSONと入力JSONを用意します。owner JSONは既存
OwnerFile形式（Task binding、actors、source_checks、storage、allowed_actions）です。
active_homeとstorage.rootは同じ既存directoryにし、actorはworker-facts、
worker-counterpoints、worker-options、verifierを指定します。owner_refをworkerと同じに
しません。Task入力のbytesをsource_checksへ固定します。これらの参照は実際のTask/grantを
代替しません。runtimeは本人と現在権限を先に検査し、取消時にはbindingを無効化します。

    python tools/task_swarm.py task-run --owner PRIVATE_OWNER_JSON --input PRIVATE_TASK_INPUT --backend codex --codex-executable CODEX_EXECUTABLE --allow-codex

親は専用のstdin pipeを生存中だけ開いておき、取消時に閉じます。通常の対話terminalのstdinや
既に閉じたpipeを生存証拠にしません。SIGTERM/SIGINT/pipe EOFと現在ownerの変化は
cancel_eventへ返します。WindowsのTask-run CLIは実行前に拒否します。
POSIX pipeにはFIFOとNode/libuvの接続済みUnix stream socketを認めます。
internet socket、datagram、未接続socket、通常fileは生存証拠にしません。

3 workerを最大同時3件で実行し、それぞれ別の報告を保存・読戻し、別invocationのverifierへ
渡します。固定モデルはgpt-5.6-luna/max、sandboxはread-only、子agentは無効です。
CodexBackendが実process→thread→completed rollout→出力を照合し、controllerは4つの
異なるthread IDを要求します。verifierは報告の書き手になりません。

同じTask ID/revisionのrun directoryは一度だけ作り、入力・plan・報告・review・結果の
exact bytesをreceiptへ束縛します。各acceptの前とfinal receiptの前に再読します。
runtimeのreceipt・process・イベント・完了rolloutも再読し、元のbytesと実出力を照合します。
同一入力・現在bindingでの再実行には、呼出し元が保持する最初のreceipt SHA-256を
expected-receipt-sha256として要求し、一致した時だけ読み戻します。同じdirectoryの
receipt自身から期待値を作りません。未完directoryは復旧確認が必要として
拒否し、processを増やしたり既存候補を上書きしたりしません。

stdoutはstate/run ID/合成かどうか/duplicate/receipt SHA-256だけを返します。実本文はprivateな結果JSONに
残ります。全criteriaがpassedの時だけjobをownerとしてacceptし、結果はneeds_reviewです。
一つでもfailed/blocked/not_runならfailedで、Taskの完了やHuman GOを宣言しません。
Taskのfinishと依頼者への返却はNode接続側が担当します。

### 合成backend

    python tools/task_swarm.py task-run --owner SYNTHETIC_OWNER_JSON --input SYNTHETIC_TASK_INPUT --backend synthetic --allow-local-fixture

合成backendは保存・引用・review構造を試す決定的fixtureです。モデルを呼ばず、
synthetic=true、model_runtime_verified=falseを返します。4つの論理roleを分けた試験であり、
実モデルの独立受入に数えません。allow-local-fixtureを必須にし、通常のCodex実行へ
黙って切り替わりません。

## 残る接続

入力契約の合成試験は、Source改変・古い版・別Task・期限・権限参照・上限・証拠位置・
古いreview・条件抜けを検査します。owner取消・未完run・artifact改変・同じreviewer identity
による受入を拒否する合成runner試験もあります。Discordの実Task/grantからowner入力を
作る接続、日次枠、Task取消とprocess groupの終了確認、依頼者への結果返却は後続です。
日次枠の既定は0、live利用枠・有効化・本人ログインは別のowner判断です。
