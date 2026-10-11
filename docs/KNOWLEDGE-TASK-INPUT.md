# 知識と要件を同じTask入力へ渡す

`tools/kotodama_kb/task_input.py` は、[#327](https://github.com/Kotodama-Project/Kotodama-project/issues/327)・[#347](https://github.com/Kotodama-Project/Kotodama-project/issues/347)の限定producerです。
既存ownerに束縛されたversion 1入力から、[Task v2](TASK-OBJECTIVE-CONTRACT.md)候補と
[既存closed loop](TASK-SWARM-CLOSED-LOOP.md)の有限planを作ります。Task作成・owner更新・CLI・Node接続は含みません。

## 候補生成とownerによる受入

`compile_task_input(bundle, seed_payload, owner_path, clock=...)` は実ownerを再読し、seedの
Task ID/revision、全入力digest、現在Sourceを検査します。seedの通常のSource本文に、次の
マーカーで囲まれたJSON宣言を一つ置きます。v1 schemaの追加fieldではありません。

````text
<!-- kotodama-task-context-request -->
```json
{ "kind": "kotodama.task-context-request", "version": 1 }
```
````

これはマーカーの説明だけで、そのまま使える宣言ではありません。完成例と既存ownerへの
束縛は `tests/test_knowledge_task_input.py` の `setup` にあります。宣言の必須fieldは
`owner_ref`、`intent`、`references`、`max_concepts`、`catalog_bindings`、`hierarchy`、
`jobs`、`constraints`、`unknowns`、`budget`です。参照・span・予算の形はTask v2を再利用します。

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

## 候補階層と文脈

`catalog_context` は既存のtyped strategy検査と`select_context`を使います。明示されたINIT、
KGI、Goalの順で最も狭いfilterを使い、必須文脈の欠落と要求された定義の省略を拒否します。
省略した任意Conceptはdiagnosticsと既存context projectionへ残します。候補の採用状態は変えません。
Conceptごとに元Markdownと一致する現在Sourceが必要です。異なる文書の連結でSource数を減らしません。

`hierarchy` は現在Markdownのpathとowner Source key/revisionの対応です。各文書の
`template_kind`は`project`、`phase`、`requirement`、`status`は`draft`に限定します。
`id`と`parent_ref`を読み、project→任意phase→requirementの明示関係だけを使います。
依存linkやpathの深さから親を推定しません。未解決親、重複、未使用の文書、placeholderは拒否します。

frontmatterの`task_context.constraints`に、必須制約の本文を明示します。requirementはさらに
`need`と`acceptance`を持ちます。各文字列は同じMarkdown本文に一意に存在する必要があります。
producerはそこからUnicode spanを計算し、祖先の制約を全子のmandatory条件へ入れます。
callerが候補の制約だけを削っても再導出に一致せず拒否されます。何を必須とするかはownerの宣言で、
本文の意味を自動分類したり、未宣言の制約がないと証明したりする機能ではありません。

## 上限と検証範囲

既存の10 Sources（過去revisionを含む）、各12,000文字、全入力256 KiB、20条件、
子選択32 spans、最大3 work jobs、4〜6 attemptsを増やしません。収まらない必須文脈は拒否します。
同じTaskの訂正は既存ownerがrevisionを更新します。compilerが改訂や予算補充を行うことはありません。

テストには、実公開catalogの6文書＋1要件＋親＋原文/訂正で10 Sourcesとなる実coordinator例と、
11 Sourcesとなる2要件版の拒否があります。別の小さな**合成catalog**では2要件を同時に送り、
同じowner pathでN→N+1訂正、旧入力拒否、全子の原文/訂正保持、B固有span更新、criticとreceiptを確認します。
これらは全公開階層の実用化、実モデルの品質やproviderへの配信、会社のCurrent Truthを証明しません。

外部履歴を独立に検証していないため`history=input_only_unverified`を保ちます。
既存のLineageContextGateを使ったと偽装しません。Plan階層type、自動階層探索、複数親、実Node/Discord入口、
配布済みCLI、未完runの復旧は後続です。このAPIはrepositoryのtoolsとして使い、
runtime wheelへKBの逆依存を追加しません。
