# 固定した検索・文脈評価

#54の評価は[合成corpus](../examples/retrieval-evaluation/corpus.json)を先に固定し、同じ入力で
検索方法を比較します。実データ・実grant・Company truth・実agent配送・Human GOではありません。
[schema](../schemas/frozen-context-corpus.schema.json)はactor/目的/宛先、Task/Session/Intent/Policy/
Grant refs、現在版、必須・禁止・不明、制約、上限、期待する次の行動を別の欄に持ちます。

## 固定するもの

corpusは17文書・3出典・24ケースを持ちます。Goal/KGI/Task/Intent/Decisionの完全一致、
日本語の半角・かな・漢字/同義のalias・文字区切り、別projectの似た文、低順位の必須制約、
旧版・訂正・矛盾、検索前/組立後の取消、予算超過、命令を含む生成文書、欠落出典、任意参照、
新session、KPIだけの改善、rollback、no-opの16区分を含みます。

`corpus_sha256`は期待するrequired/forbidden集合を含む全入力を固定します。本文、版、期待値を
変えた場合、古いhashでは受理しません。source/document textは各digestとも照合します。
expectedは**採点にだけ**使い、検索・選択の入力には使いません。期待値の変更で検索結果を
誘導せず、corpusの変更とアルゴリズムの変更を分けてreviewします。

Source更新の影響集合は合成文書を既存の[履歴契約](KNOWLEDGE-LINEAGE.md)へ対応させ、
実際の逆引きindexで求めます。欠落出典を新しい出典として補完せず、必須依存の循環も同じ
lineage検査で検出します。Source変更がないケースでは影響集合を空に保ちます。

## 比較する基準線

1. ID/revision/aliasの完全一致。
2. Unicode NFKCとかなの正規化、語彙の一致。
3. 日本語の文字n-gram、BM25のそれぞれ。
4. 必須の型付き依存を先に確保するgraph展開。

いずれもownerの現在版・project/Task・actor・source accessの合成申告を先に照合します。
現行refや出典の版と一致しないもの、拒否・撤回・失効済みの文書を似ているだけで選びません。
必須制約はoptionalに場所を奪われず、予算不足や未解決ならneeds_resolutionです。生成文書内の
指示は検索対象のtextであり、実行やpolicy変更に使いません。

## 実行とreadback

```text
python -B tools/evaluate_context_corpus.py --corpus examples/retrieval-evaluation/corpus.json
python -B tools/evaluate_context_corpus.py --corpus examples/retrieval-evaluation/corpus.json --mode typed_graph
python -B tools/evaluate_context_corpus.py --corpus examples/retrieval-evaluation/corpus.json --attest work/evaluation-receipt.json
python -m unittest tests.test_frozen_context_evaluation -v
```

CLIはstdoutへ出すだけで、receiptやKBを自動保存しません。全mode実行は一つでも期待不一致が
あればexit 1です。固定corpusではexact/lexicalは日本語の文字区切りケースを落とし23/24、
ngram/BM25/graphは24/24でした。全modeの不成立を隠さず残します。これは限定された合成例での差です。

各caseのmanifestにactor等のrequest digest、選択したConcept/source revisions、source-set digest、
required/supporting分類、不明・省略理由、bytes/Concept数、rendered digestを持ちます。
reportはcorpus/index/source/code/schema/modelなしの状態を固定します。attesterは現在の固定入力と
codeで再計算し、per-case結果の改変も拒否します。実際のOS実行imageを認証するものではありません。

## 指標と証拠の上限

required Concept/source recall、制約保持、引用binding整合、禁止・失効・別scopeの混入、不明の保持、
影響集合precision/recall、bytes/Concept数をcase別に出します。権限違反・漏えい・binding改変は
平均に関係なくrunを失敗させます。引用の参照整合と意味的entailmentは別で、後者は未検証です。
分母0の指標を100%にせずnullにし、expectedが安全な拒否なら空の出力と次の確認行動を照合します。

実tokenizer/modelを選んでいないためactual_model_tokensはnullで、token予算は**明示したUTF-8 byte
評価単位**で保守的に扱います。実modelのtoken数だとは主張しません。外部呼出し・外部費用は0、
local computeの金額は未測定です。latencyは実測しますが、意味上の決定的digestとは分離します。
latency/cost観測の真正性はattesterで証明しません。人の重大な訂正率・実Task成果は未測定のnullです。

## semantic retrievalの採用前

corpus revisionを凍結し、exact/lexical/graphに対する必要文脈・依頼成果の実質的改善を確認します。
禁止情報、取消、必須制約、rollback、決定性の退行が一つでもあれば採用しません。遅延・費用・
運用の複雑さ・再構築・障害復旧も比較し、負の結果や不明を記録します。ownerが範囲・rollbackを
決めたcanaryで受入するまで、本番を切り替えません。この実装はembedding/vector DB/reranker、
運用token予算・品質target・private dataset・runtime Context Gatewayを採用しません。
