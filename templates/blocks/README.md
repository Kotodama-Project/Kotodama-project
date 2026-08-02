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

## Public starterで動くauthority chain

- [`work-order.json`](../../examples/company-starter/blocks/work-order.json): 実行権限を含まない作業候補
- [`capability-grant.json`](../../examples/company-starter/blocks/capability-grant.json): exact Work Orderへ最小権限候補を束縛
- [`change-execution.json`](../../examples/company-starter/blocks/change-execution.json): Work OrderとGrantが一致するときだけChange Candidateを生成
- [`promotion-gate.json`](../../examples/company-starter/blocks/promotion-gate.json): receipt群をPromotion Candidateへ集約
- [`promotion-decision.json`](../../examples/company-starter/blocks/promotion-decision.json): 人間の判断証拠を記録するがPromotion自体は実行しない
