# Blocks

Blockは、一つの責任を持つ最小の再利用単位です。単なるpromptではなく、入力、出力、権限、禁止事項、検証、rollbackを一緒に持ちます。

## Good Block examples

- Intent extraction
- Decision request
- Work Order
- Capability Grant
- Discord intake
- Voice transcription
- Speaker attribution
- Verification
- Retention and deletion
- Incident stop

## Rule of thumb

Blockを単独で読んだときに、次の質問へ答えられるようにします。

1. 何をするBlockか。
2. 何を入力し、何を出力するか。
3. 誰の権限で、いつまで動くか。
4. 絶対にしないことは何か。
5. 成功・失敗を何で検証するか。
6. どう停止し、どう戻すか。

最小形式は[Work Order Block](work-order-block.md)を参照してください。

## 公開starterの9 Blocksを目的で選ぶ

公開starterは、次の9 Blockを一つのcanonical flowとして出荷しています。
表のJSONはBlock契約の入口なので、目的を選んだら入力・出力・authority・
拒否条件・receiptの詳細を直接確認できます。

| # | Block | shipped contract | 目的 |
|---:|---|---|---|
| 1 | Source Intake | [source-intake.json](../../examples/company-starter/blocks/source-intake.json) | Source、access/consent、retention候補を取り込む |
| 2 | Intent Candidate | [intent-candidate.json](../../examples/company-starter/blocks/intent-candidate.json) | Sourceから未確定の意図候補を抽出する |
| 3 | Human Decision | [human-decision.json](../../examples/company-starter/blocks/human-decision.json) | authorityを持つ人の判断候補を記録する |
| 4 | Work Order | [work-order.json](../../examples/company-starter/blocks/work-order.json) | target、action、期限、rollbackを束縛する |
| 5 | Capability Grant | [capability-grant.json](../../examples/company-starter/blocks/capability-grant.json) | exact Work Orderへ最小権限候補を結び付ける |
| 6 | Change Execution | [change-execution.json](../../examples/company-starter/blocks/change-execution.json) | Work OrderとGrantに対応するChange Candidateを作る |
| 7 | Verification Receipt | [verification-receipt.json](../../examples/company-starter/blocks/verification-receipt.json) | candidate、test、negative check、effectを記録する |
| 8 | Promotion Gate | [promotion-gate.json](../../examples/company-starter/blocks/promotion-gate.json) | receipt群をPromotion Candidateへ集約する |
| 9 | Promotion Decision | [promotion-decision.json](../../examples/company-starter/blocks/promotion-decision.json) | 人間のPromotion判断候補を記録する |

この表は同じcanonical flowを読むためのnavigation mapであり、runtimeを実行する
一覧ではありません。JSON SchemaやvalidatorのPASSは構造検証だけで、実行権限、
Human approval、Promotion、Current Truth、Public Beta GOを作りません。公開starter
は`read-only / candidate-only`で、状態は常に`NO_GO_UNPUBLISHED`です。

上の9件以外のVoice transcription、speaker attribution、retention and deletion、
incident stopなどは、将来のadapter / Block候補を考えるための概念例です。すべてが
現在の公開starter JSONとして出荷されているわけではありません。

## Public starterで動くauthority chain

- [`work-order.json`](../../examples/company-starter/blocks/work-order.json): 実行権限を含まない作業候補
- [`capability-grant.json`](../../examples/company-starter/blocks/capability-grant.json): exact Work Orderへ最小権限候補を束縛
- [`change-execution.json`](../../examples/company-starter/blocks/change-execution.json): Work OrderとGrantが一致するときだけChange Candidateを生成
- [`promotion-gate.json`](../../examples/company-starter/blocks/promotion-gate.json): receipt群をPromotion Candidateへ集約
- [`promotion-decision.json`](../../examples/company-starter/blocks/promotion-decision.json): 人間の判断証拠を記録するがPromotion自体は実行しない

## 現在のstarterと後続review

公開starterのBlockは、実行runtimeではなく入力・出力・authority・拒否条件を
検証する契約です。Block出力をexact bytesへ固定した後は、[Review Request](../../docs/REVIEW-REQUEST.md)、
[Review Response](../../docs/REVIEW-RESPONSE.md)、[Decision Handoff](../../docs/REVIEW-DECISION-HANDOFF.md)
へ進めます。starterの`19/46/5`は例示値で、別Packでは保存済みreportとchainの
実数を使います。いずれもHuman approval、Promotion、Current Truth、runtime、
Public Beta GOを作りません。
