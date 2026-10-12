# 知識と要件を同じTask入力へ渡す

`tools/kotodama_kb/task_input.py` は、[#327](https://github.com/Kotodama-Project/Kotodama-project/issues/327)・[#347](https://github.com/Kotodama-Project/Kotodama-project/issues/347)の限定producerです。
既存ownerに束縛されたversion 1入力から、[Task v2](TASK-OBJECTIVE-CONTRACT.md)候補と
[既存closed loop](TASK-SWARM-CLOSED-LOOP.md)の有限planを作ります。source checkoutの知識CLIからも使えます。
Task作成・owner更新・Node接続は含みません。
[#361](https://github.com/Kotodama-Project/Kotodama-project/issues/361)の初期plannerは、
明示した根Requirementから必要な仕事を導く追加のopt-inです。

## 候補生成とownerによる受入

`compile_task_input(bundle, seed_payload, owner_path, clock=...)` は実ownerを再読し、seedの
Task ID/revision、全入力digest、現在Sourceを検査します。seedの通常のSource本文に、次の
マーカーで囲まれたJSON宣言を一つ置きます。v1 schemaの追加fieldではありません。

~~~text
<!-- kotodama-task-context-request -->
```json
{ "kind": "kotodama.task-context-request", "version": 1 }
```
~~~

これはマーカーの説明だけで、そのまま使える宣言ではありません。完成例と既存ownerへの
束縛は `tests/test_knowledge_task_input.py` の `setup` にあります。宣言の必須fieldは
`owner_ref`、`intent`、`references`、`max_concepts`、`catalog_bindings`、`hierarchy`、
`jobs`、`constraints`、`unknowns`、`budget`です。参照・span・予算の形はTask v2を再利用します。
宣言version 2では`jobs`を受け付けず、代わりに一つの`root_requirement_id`を必須とします。
宣言の版とruntime Taskの版は別です。従来の宣言version 1とTask schemaは変更しません。

返り値は`payload`、`supplied_plan`、`seed_digest`、`source_checks`、`context_projection`、
`diagnostics`です。ownerが**明示的に**新しい全payload digestとsource_checksを受け入れるまでは
実行できません。producerは既存bindingのdigestを差し替えず、ownerファイルへ書き込みません。
`verify_task_input` は候補を再導出して比較し、現在ownerがそのv2入力を束縛していることを要求します。

`execute_task_input` は明示的な合成backendだけを扱う既存coordinatorへ接続します。
各backend呼出しの前後に、catalog/schema/profile・階層文書の現在bytesと実ownerを再検査します。
選択Conceptの期限は古い`as_of`でなく実clockで再確認し、完成receiptの再読でも免除しません。
ownerが宣言するTask期限は、期限を持つ選択Conceptの最短期限以下である必要があります。
超える候補は自動短縮せず拒否し、既存coordinatorの受入・receipt公開直前の期限検査にも含めます。
既存ownerのsource_checksにも全入力ファイルが必要です。原意・全文訂正・祖先制約・採用した
catalog文書の全文を実子入力へ送り、独立criticとreceiptの入力digestへ束縛します。

## 知識CLIから使う

```sh
python -B tools/knowledge_base.py task-input compile --root KNOWLEDGE_ROOT --owner OWNER_JSON --input V1_INPUT
python -B tools/knowledge_base.py task-input verify --root KNOWLEDGE_ROOT --owner OWNER_JSON --candidate CANDIDATE_JSON
python -B tools/knowledge_base.py task-input simulate --root KNOWLEDGE_ROOT --owner OWNER_JSON --candidate CANDIDATE_JSON --input V2_INPUT --simulation SCENARIO_JSON --worker worker-a --worker worker-b
```

`compile`は候補全体を一つのJSONとしてstdoutへ返します。保存先と元入力は別にし、
既存ownerが候補の`payload`の全digest・全source_checksを明示的に受け入れてから、
`verify`または`simulate`へ進みます。CLIはowner・Task・入力ファイルを書き換えません。
`verify`はTask ID/revisionと`payload_digest`を返します。採用やモデル品質の判定ではありません。

`simulate`は[既存scenario形式](TASK-SWARM-CLOSED-LOOP.md#実行入口)の明示ファイルが必須です。
追加workerは`--worker`を繰り返し、独立criticは`--critic`（既定`verifier`）で指定します。
実providerは呼ばず、元ownerの同じTask/revision・累積予算・入力・critic検査を使います。
stdoutに統合候補とreceiptを返し、実行証跡は既存ownerのstorageへ保存します。
完成済みrunの再読には、先の応答から別途保存した`--receipt-sha256`を渡します。

終了値は候補生成・束縛確認・passedなsimulationが0、criticの未解決が3、入力や束縛の拒否が2です。
拒否はstderrへJSONを返し、stdoutに成功の断片を出しません。引数不足は通常のCLI usageで拒否します。
入力は256 KiB、scenarioは1 MiB以内です。出力JSONは端末の文字コードによらずUTF-8と末尾のLF一つを使い、
canonicalな候補JSONにはその1 byteの改行を許します。
`verify`と`simulate`は候補に保存した監査時点で現在の文書を再読します。異なる`--as-of`は拒否し、
現在clockの期限検査を免除しません。別の作業ディレクトリや
`python -I`でも、実行コードはこのsource checkoutから読みます。`--root`は知識の入力先です。

## 候補階層と文脈

### 通常候補の参照をinspectする

ownerが全payloadを受け入れた通常候補から、Goal/KGI/INITの実Concept・Source版/span・原意と
訂正・制約・未知・受入への参照を、JSONまたはMarkdownで読み取れます。source checkout専用です。

```sh
python -B tools/knowledge_base.py task-input inspect --root KNOWLEDGE_ROOT --owner OWNER_JSON --candidate CANDIDATE_JSON
python -B tools/knowledge_base.py task-input inspect --root KNOWLEDGE_ROOT --owner OWNER_JSON --candidate CANDIDATE_JSON --format markdown
```

既存normal verifierで再導出したpayloadと実Bundleから表示を作り、candidateのdiagnosticsや
context_projectionを権限・採用の表示根拠にしません。Source revisionはTask入力の版、spanはUnicode
文字offsetで、外部Goal ownerのcurrent revisionやUTF-8 byte offsetとは別です。表のConcept pathを
`show CONCEPT_ID --root KNOWLEDGE_ROOT --json`で読み、原文spanとSHAへ戻れます。全文は追加dumpしません。

表示を完全serializeしてから、実clockでnormal verifierを再実行し、candidateとownerの原file SHAを
bounded readerで再照合し、最後に現在Sourceを検査します。Source訂正・削除・rename、同size/mtimeでの
変更、期限切れ、owner/candidateの途中変更は成功の断片をstdoutへ出さずtyped refusalで拒否します。
出力は末尾LF一つを含めUTF-8 256KiB以内で、上限超過時に必須情報を切り捨てません。

これはDBを開かず、dispatch・Task/owner更新・新grantを行わない参照案内です。exit0も実行許可や成果受入
ではありません。actor実行許可とlearning decisionはNOT_EVALUATED、external Goal revision/adoption/accessは
UNRESOLVED、decision_readinessはNEEDS_RESOLUTIONです。外部採用ownerの保存先・current read contractは別の未解決です。

learning candidateや`--learning-origin`/`--learning-decision-digest`は、学習verifierに入る前に
`TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED`で拒否します。inspectの`--input`も未対応として拒否します。
既存learning verifyはorigin replay/SwarmState初期化・DDLへ到達するため、DB0のinspectへ流用しません。
その既存compile/verify/simulate経路は変更しません。wheel/installed CLI、外部モデル、全8階層の受入は別です。

`catalog_context` は既存のtyped strategy検査と`select_context`を使います。明示されたINIT、
KGI、Goalの順で最も狭いfilterを使い、必須文脈の欠落と要求された定義の省略を拒否します。
省略した任意Conceptはdiagnosticsと既存context projectionへ残します。候補の採用状態は変えません。
Conceptごとに元Markdownと一致する現在Sourceが必要です。異なる文書の連結でSource数を減らしません。

`hierarchy` は現在Markdownのpathとowner Source key/revisionの対応です。各文書の
`template_kind`は`project`、`phase`、`requirement`、`status`は`draft`に限定します。
既定は`id`と単数の`parent_ref`を読み、project→任意phase→requirementの明示関係だけを使います。
依存linkやpathの深さから親を推定しません。未解決親、重複、未使用の文書、placeholderは拒否します。

frontmatterの`task_context.constraints`に、必須制約の本文を明示します。requirementはさらに
`need`と`acceptance`を持ちます。各文字列は同じMarkdown本文に一意に存在する必要があります。
producerはそこからUnicode spanを計算し、祖先の制約を全子のmandatory条件へ入れます。
callerが候補の制約だけを削っても再導出に一致せず拒否されます。何を必須とするかはownerの宣言で、
本文の意味を自動分類したり、未宣言の制約がないと証明したりする機能ではありません。

## 明示した複数親を実Task入力へ渡す

[#372](https://github.com/Kotodama-Project/Kotodama-project/issues/372)の限定bridgeは、
現在Sourceのfrontmatterに`parent_refs`を明示した場合だけ
[既存の有限reader](KNOWLEDGE-HIERARCHY-TRACE.md)を遅延読込します。
Sourceには既存の安定IDを列挙し、producer宣言の`hierarchy`にも各現在文書を列挙します。

```yaml
template_kind: requirement
id: REQ-MEASUREMENT
status: draft
parent_refs: [PROJECT-A, PROJECT-B]
```

この例に`task_context`のneed・acceptance・constraintsと、一意な本文が必要です。
`parent_ref`との併記、未知ID、重複親、同じkindの親、未使用文書は拒否します。
既定の単数親APIは維持し、Project・任意Phase・Requirementに限り最大8 nodes、
各2 parents、経路2 edges、全16 edgesを検査します。両Projectの制約は同じ文でも
別Source/spanとして全work・criticのmandatory条件へ送ります。共有祖先は同じSource/spanを一度だけ送ります。
readerの行番号・hash等のmetadataをTask schemaへ混ぜず、元の4項目のspanを使います。

`diagnostics.structural_parents`は現在Sourceに書かれた親の辺・元span・reverse refsです。
候補文書の事実を示すだけで、Task owner・組織Plan・採用判断を追加しません。
構造の親、`all_of.children`による要件分解、`requires`による実行依存は別の辺です。
このbridgeはreaderの保存Plan検査を実行せず、既存producerから実coordinatorへ渡します。
actor・Task revision・全現在Source・Concept期限・critic・取消・最終receiptの検査は既存経路のままです。
最終公開前の不適格化はanchorを拒否し、公開のcutoff後は同じexact anchorを返します。
その後の再読は現在owner/source/期限を再検査します。

同じownerのN→N+1訂正では、原意と置換全文を**同じSource keyの別revision**へ束縛します。
旧行はNの保存inputから完全にコピーし、最新のProject Sourceに宣言を一つ置きます。
旧本文を現在ファイルへ再適用したり、外部履歴を検証済みにしたりしません。
`history=input_only_unverified`と、ownerによる新payload/digest/source_checksの明示受入を維持します。

| 固定fixture | 初期Source数 | 旧行を保持した訂正後 |
|---|---:|---:|
| 合成4Concept・独立3Requirement・2Project | 9 | 10 |
| 合成4Concept・根と2leaf・2Project | 9 | 10 |
| 合成4Concept・根と3leaf・2Project | 10 | 11なので拒否 |
| 公開6Concept・1Requirement・2Project | 9 | 10 |

合成3workersと独立criticの実子processでは、stdin bytes、保存input、dispatch digest、
receiptを照合します。criticはSource数値から別途計算し、echo・誤計算・担当証拠の欠落を拒否します。
公開6Conceptで3独立Requirementを同時に置く11Source候補も拒否します。
配列20条件と子選択32 spansは別の上限で、既存10 Sources・256KiB等を拡大しません。

入口はこのrepositoryのsource CLIです。readerはruntime wheelの公開coreに追加しません。
helperが欠けたcheckoutでは新分岐だけ`TASK_CONTEXT_HIERARCHY_UNSUPPORTED`でdispatch前に拒否し、
単数親と通常queryのimportは保ちます。無関係なimport例外をこの拒否へ変換しません。
実provider、installed CLI、組織Planや全8階層、複数親と学習再利用の組合せの追加受入はこの検証に含めません。

## 根Requirementから有限の仕事を導く

宣言version 2の到達可能な各Requirementでは、`task_context`に次の`frontier`を追加します。
`hierarchy`で列挙した現在文書の中だけを参照します。

```yaml
frontier:
  kind: all_of
  children: [REQ-LATENCY, REQ-RSS]
  requires: []
```

`atomic`は空のchildrenを持つ一つの仕事、`all_of`は列挙した子がすべて必要な要件です。
root/中間/leafのすべてで`kind`・`children`・`requires`を必須とします。
初期の独立仕事は`requires: []`です。現行の[#366](https://github.com/Kotodama-Project/Kotodama-project/issues/366)経路は、
2leafの間の明示した1依存だけを既存prerequisite reviewへ渡します。それ以上は拒否し、
独立性を推論したり、依存する仕事を独立として実行したりしません。`children`は要件分解の辺で、
文書の構造上の親や仕事の実行順序とは別です。通常テンプレートや宣言version 1へは適用しません。

根からの閉包を検査し、循環、未知の子、同じ子の重複、最大2辺を超える経路、未使用文書を拒否します。
先に短い経路をたどった共有nodeも、長い経路の深さを省略しません。同じ現在Requirementのatomic leafは
一つの仕事へまとめます。別文書の重複IDは拒否します。文書祖先と全到達Requirementの制約は
Task全体の条件として全子へ送り、相反する宣言も片方を捨てません。branchごとの制約の意味は追加しません。

全体acceptanceは根が先、残りの到達RequirementはID順、各文書内は宣言順です。同一Source/revision/span
だけを初出位置へまとめ、起点nodeの集合を残します。同文でも異なるSource/spanなら別条件です。
この順序が元seedのacceptanceと一致しなければ拒否し、seedを書き換えません。`A_i`は起点から到達する
leafの仕事へ割り当て、起点が複数なら和集合を使います。`R/S/U/I`とTask全体の`O_i/Q_i`は全仕事共通です。
全条件の本文、原意、全文訂正、根と必要な中間の原文は実子入力にも残します。

生成job IDは安定Requirement IDから決め、purposeはそのleafの現在needとします。呼出者はjobsや
担当条件を手で列挙しません。`diagnostics.frontier`に分解辺、leafとjobの対応、各条件のSource spanと
起点/担当leaf、元予算と初期必要attempt数を返します。ここで示す初期実行後の余裕は未実行時の計算値で、
実runの残予算ではありません。実行済みattemptは既存coordinatorが同じrunで管理します。

このsliceが保証するのは、明示分解からの入力配布・計画と全reportの収集です。現行の
[#362](https://github.com/Kotodama-Project/Kotodama-project/issues/362) validatorは、個々の`A_i`に割り当てた
全leafのpassed evidenceと実work入力を照合します。担当割当だけで要件の意味的達成を保証したとは扱いません。
テストの独立criticは与えた数値からp95/RSS欠測を計算し、echoや別leafの値を
失敗にする限定fixtureです。任意の実モデルの誤判定を検出する証明ではありません。

## 上限と検証範囲

既存の10 Sources（過去revisionを含む）、各12,000文字、全入力256 KiB、各配列の条件20件、
子選択32 spans、最大3 work jobs、4〜6 attemptsを増やしません。収まらない必須文脈は拒否します。
acceptance・constraints・unknowns・referencesはそれぞれの上限で、全criteriaの合計20件ではありません。
実行する仕事数は指定した有効worker数と元予算にも収まる必要があります。3leafに2workerなら、
切り詰めやworkerの自動追加を行わず、dispatch前に拒否します。
同じTaskの訂正は既存ownerがrevisionを更新します。compilerが改訂や予算補充を行うことはありません。

テストには、実公開catalogの6文書＋1要件＋親＋原文/訂正で10 Sourcesとなる実coordinator例と、
11 Sourcesとなる2要件版の拒否があります。別の小さな**合成catalog**では2要件を同時に送り、
同じowner pathでN→N+1訂正、旧入力拒否、全子の原文/訂正保持、B固有span更新、criticとreceiptを確認します。
これらは全公開階層の実用化、実モデルの品質やproviderへの配信、会社のCurrent Truthを証明しません。
宣言version 2のテストでは、atomic/2leaf/共有leafによる実入力とdispatch数の違い、
全経路の制約とSource spanの起点、3workerと元4attemptでの3leaf、2worker時の拒否を扱います。
同Taskの訂正ではA固有needを保持してBを更新しますが、旧完成reportを新revisionへ再利用する機能はありません。
全文訂正によって全子入力のdigestが変わることを維持します。

外部履歴を独立に検証していないため`history=input_only_unverified`を保ちます。
既存のLineageContextGateを使ったと偽装しません。組織Plan階層type、自動階層探索、実Node/Discord入口、
配布済みCLIの受入は後続です。未完runの復旧は現coordinatorの別の受入を参照し、
本bridgeの証拠をその代用にしません。このAPIとCLIはrepositoryのtoolsとして使い、
runtime wheelへKBの逆依存を追加しません。

## 一件の学びを現在のTask入力へ接続する

`task-input`は、[既存の学習再利用](TASK-LEARNING-REUSE.md)で選んだ一件を明示的に追加できます。
Goal・原意・訂正・祖先制約から導出した同じB Taskの各workへproposal全文を渡します。
既存のAの外部receipt anchor、独立review、B ownerの判断を再利用し、検索器やmemory DBは追加しません。

`--learning-origin`のJSONは次の4項目です。Aは既存の完了Task、Bは既存ownerに束縛された
v1 seedです。同一owner_ref・同一目的を要求し、Bを作成したりownerを書き換えたりしません。

```json
{
  "origin_owner": "/path/to/A-owner.json",
  "origin_input": "/path/to/A-input.json",
  "origin_anchor": "EXTERNALLY_RETAINED_A_RECEIPT_SHA256",
  "claim_index": 0
}
```

```sh
python -B tools/knowledge_base.py task-input compile --root KNOWLEDGE_ROOT --owner B_OWNER --input B_SEED --learning-origin ORIGIN_JSON
```

出力は未承認candidateです。元の`seed_digest`を保持し、学びを加える前のpayload / plan digestを
`diagnostics.learning`へ記録します。新しいpayload / planのdigestは候補として明示し、旧ownerの承認とは扱いません。
既存の手順でcandidate.payloadをB_INPUTへ保存し、B ownerの入力とsource checks、
`learning_reuse` grantを束縛した後、既存`learning_reuse review/decide`で判断を記録します。
review用contextのproposalとoriginはcandidate.learning、targetは同じB owner / B_INPUTです。

```sh
python -B tools/knowledge_base.py task-input verify --root KNOWLEDGE_ROOT --owner B_OWNER --candidate CANDIDATE_JSON --input B_INPUT --learning-decision-digest DECISION_SHA256
python -B tools/knowledge_base.py task-input simulate --root KNOWLEDGE_ROOT --owner B_OWNER --candidate CANDIDATE_JSON --input B_INPUT --simulation SCENARIO_JSON --worker worker-a --worker worker-b --learning-decision-digest DECISION_SHA256
```

verifyは最終B入力を実ownerで検証し、元のKB候補と一件の追加を再導出して完全一致を要求します。
現在のA証拠・B grant・独立review・判断headを再読します。simulateは既存coordinatorを使い、
保存した全work / critic入力、引用、判断digestをreceiptへ束縛します。前提を飛ばす成功callbackはありません。
完了済み再読には既存どおり外部`--receipt-sha256`が必要です。KB期限、grant、取消の検査は免除しません。

| 検査境界 | 担当 |
|---|---|
| compile | 実ownerのseedを検証し、Aをanchorから再検証。Aの読取後に元seedを再検証 |
| verify | 最終B入力・KB再導出、現在のReuseOwner、KB再導出、現在のReuseOwnerの順に照合 |
| 各work / critic呼出し前後 | adapterがKB再導出、既存coordinatorのguardがowner・全source checks・A・判断headを照合 |
| claim / report / accept / receipt / replay | 既存coordinatorのguardが同じ実owner・A・判断を再検証。保存済みの成功をキャッシュしない |
| 完了済みreplayの返却直前 | backendを呼ばずTask期限を免除する再読でも、adapterが現在時刻でConcept期限を再確認 |

一件学習adapterの初期公開v1受入にはcheckpointとfinalization recoveryを含めていません。
現在のcoordinatorの追加経路を、その初期証拠だけで受入済みとは扱いません。

最終B ownerにはcandidateの全`source_checks`の束縛が必要です。削除したcheckをcandidate側の自己申告で
補うことはできません。選択Conceptの最短期限を既存Task deadlineが越えない条件も維持するため、
backendのreturn後から最終receiptまでのKB変更・期限切れも既存guardで拒否します。

原意・訂正・参照・制約・未知・受入・停止条件が変わると、既存のpurpose比較が旧学びを拒否します。
Source、actor、判断headの変更や失効、10 Sources / 32 spans / 256KiB等の予算超過も拒否し、
祖先を削ったり期限を短縮したりして成功にしません。通常candidateとquery/show/contextの動作は維持します。
これは一件の明示選択を実入力へ接続するlocal simulationです。自動検索、連鎖的学習、
具体8階層の確定、実モデルの理解、Desktop導入、会社のCurrent Truthはこの受入に含めません。
検証した受入は独立leafのplan version 1です。`requires`を含むplan version 2の依存実行との組合せは
この受入で実証しておらず、追加の対応保証をしません。元のplan検証と予算制限はそのまま適用されます。
