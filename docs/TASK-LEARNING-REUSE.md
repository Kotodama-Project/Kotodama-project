# 検証済みの学びを次の一つのTaskへ渡す

[#328](https://github.com/Kotodama-Project/Kotodama-project/issues/328)の限定実装です。
[同じTaskの閉ループ](TASK-SWARM-CLOSED-LOOP.md)が残した一つの学びを、独立reviewと
既存Task ownerの明示判断を経て、同じ目的の次のTaskの実入力へ渡します。
元の依頼・訂正・制約・未知・受入条件を保持し、次のworkerがその資料を引用し、
独立criticが結果を検証するまでを既存coordinatorで実行します。

この版はproviderを呼ばないlocal simulationです。学習内容を実モデルが理解したこと、
会社のCurrent TruthやPolicyへの昇格、全体の自律運用は証明しません。
複数の学びの検索・競合解決、連鎖的な再利用、planner生成は後続です。

## 証拠と判断の流れ

| 段階 | 条件と保存先 |
|---|---|
| 元Task A | 呼出元が保存した外部receipt SHA-256で全artifactを再読し、配布入力・報告・全roundのcriticを再検証する |
| proposal | 最終criticが引用したsupported claimを一つ選ぶ。原文のquoteと出典、元Task/revision、receipt、目的digestを保持する |
| 独立review | 元のproducer群とowner以外の現在有効なactorが、対象proposalと次Task Bの範囲を明示してallow/rejectする |
| owner判断 | Bの既存ownerがreview・現在grant・Bの入力/revisionを指定し、allow/reject/revoke/supersedeする |
| 次Task B | 同じ目的、明示判断、現在のgrant・資料・actorを照合し、proposal全文を子入力へ配布する |
| 成果 | criticが引用する報告と統合候補に、配布した学びの出典を要求する。実行receiptに判断digestを固定する |

reviewと判断はAの既存`execution.sqlite`に型付きの証拠として保存します。
新しいTask台帳や全社の知識ownerは作りません。判断は一つのproposalと一つのB Task/revisionに限定し、
generationのCAS、同内容のidempotency、最大8件のreview/判断履歴を持ちます。
古いallowを再送して取消後のheadを戻すことはできません。
既存の`learning.json`は`unadopted`のままで、別の限定判断がBでの利用だけを許します。

## 入力と既存owner

AとBは[version 2 Task入力](TASK-OBJECTIVE-CONTRACT.md)と既存`OwnerFile`を使います。
Bの入力は`with_learning_source`でproposalを通常のSourceとして追加したものです。
この関数はTask登録・owner更新・利用許可を行いません。既存owner側でその入力のdigest、
source checks、actor、保存先を用意し、次の`learning_reuse`を明示します。

```json
{
  "version": 1,
  "grant_ref": "ref/grant/one-reuse",
  "policy_revision_ref": "ref/policy/current-reuse",
  "proposal_digest": "PROPOSAL_SHA256",
  "origin_receipt_sha256": "EXTERNALLY_RETAINED_RECEIPT_SHA256",
  "target_context_digest": "TASK_B_INPUT_DIGEST",
  "purpose_digest": "SAME_PURPOSE_DIGEST",
  "reviewer_ref": "verifier",
  "expires_at": 1234567890
}
```

これはoperatorが供給するlocal owner入力の拡張です。actor名の指定だけで外部の本人確認や権限を作りません。
grantの期限はBのowner期限以内かつ実行deadline以後です。目的digestは元依頼・訂正履歴・参照・
制約・未知・受入条件・停止/rollbackを含みます。BのTask IDや実行予算はBのownerに別途束縛します。
資料の追加・目的変更・revision更新には、その内容に対応する既存ownerの更新が必要です。

## CLIとPython

installed packageでは`python -m kotodama_core.task_swarm.learning_reuse`を使います。
source checkoutでは`PYTHONPATH=runtime`と`task_swarm.learning_reuse`を使います。
`propose --owner A_OWNER --input A_INPUT --anchor A_RECEIPT_SHA256 --claim-index 0`はproposalを、
`prepare --input B_INPUT --proposal PROPOSAL_JSON`は未承認の投影入力をstdoutへ返します。
本文を含むため、その出力は元資料と同じ閲覧範囲で扱います。

既存ownerがBの入力とgrantを束縛した後、context JSONを用意します。
項目は`origin_owner`、`origin_input`、`anchor`、`target_owner`、`target_input`、`proposal`のみです。
最後の`proposal`にはファイル名でなくproposal objectを入れます。

```sh
python -m kotodama_core.task_swarm.learning_reuse review \
  --context CONTEXT_JSON --review-ref ref/review/one --reviewer verifier \
  --outcome allow --reason "The selected claim supports this Task purpose."
python -m kotodama_core.task_swarm.learning_reuse decide \
  --context CONTEXT_JSON --actor ref/owner/fixture --review-ref ref/review/one \
  --outcome allow --key ref/decision/one --expected-generation 0
python -m kotodama_core.task_swarm.learning_reuse run \
  --context CONTEXT_JSON --decision-digest DECISION_DIGEST \
  --plan FINITE_PLAN_JSON --simulation SCENARIO_JSON --worker worker-a
```

`current`は現在の判断digestを照合します。`decide`の`--outcome revoke`または`supersede`は
新generationを追加し、旧判断での利用を拒否します。CLIはreviewやowner判断を自動生成しません。
plan/scenarioは[閉ループの形式](TASK-SWARM-CLOSED-LOOP.md#実行入口)と同じで、
各workerの選択spanはproposal全文を含めます。CLIは成功やquoteを補完しません。

Pythonでは`ReuseOwner.review/decide/current/execute`を使います。`execute`は既存
`execute_closed_loop`へ委譲し、coordinator自身が現在のowner/storeを読みます。
任意のsuccess callbackや自己申告のcontext bindingで判断検査を置き換えられません。
dispatch前と報告の利用前に取消・grant・owner・資料を再確認します。
完了済みBの再読には外部保存した`--receipt-sha256`が必要です。有効なowner/grantの範囲で
objective deadline後も再読できますが、新dispatch・review・判断は期限後に受け付けません。
失効・取消・改訂後の旧証拠による利用は拒否します。

## 確認すること

`tests/test_task_swarm_learning_reuse.py`は実coordinatorとSQLiteを使い、Aから別processのBへ
実資料を渡します。同じ目的・予算で資料なしのBはunknownと失敗criticを残し、採用済みのBは
元観測値を引用して判断します。合法な観測値8→11でBの結果も11へ変わることを確認します。
資料を無視するworker、判断なし、reject/revoke/supersede、古いgrant/revision/資料、
CAS衝突、期限超過、途中取消、全文を欠く配布、完了証拠の改変を拒否します。
これらは接続機構の合成検証であり、実運用や実モデルの改善測定ではありません。
