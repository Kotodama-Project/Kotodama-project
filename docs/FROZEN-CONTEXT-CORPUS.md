# 検索・文脈評価の固定corpus

検索方式を比較する前に、[公開用の合成fixture](../examples/retrieval-evaluation/corpus.json)と
[閉じたschema](../schemas/frozen-context-corpus.schema.json)を固定します（#54の前半）。
17文書・3出典・24ケースで、Issueが要求する16区分を保持します。

各caseはactor/宛先/目的、Task・Session・Intent・Policy・Grantの合成参照、検索内容、
現在版、必須Concept・Source・制約、禁止/旧版/撤回、不明、期待する次の行動、
bytes・token評価単位・Concept数・遅延・費用の上限と評価器の版を明示します。
実grant、Company truth、実Task成果、実配送、Human GOの証拠ではありません。

期待するrequired/forbidden/unknown集合も含めて`corpus_sha256`へ束縛します。
期待値、本文、版を変えたfixtureは古いhashでは受理せず、変更と新しいhashをreviewします。
Source Bindingは既存lineage契約で検査し、本文のdigest・現在版のlogical ID・重複・
区分の欠落・未定義の欄・大きすぎる入力を拒否します。fixtureを受理しても実行を許可しません。

分類名だけで網羅したことにしません。取消の時点、失効した出典の禁止集合、旧版との差、
必須依存と予算、変更のない更新、KPIだけの改善など、分類を成り立たせる入力を照合します。
任意リンクは`optional_dependencies`へ欠落したtargetを明示し、命令として扱わない箇所は
`inert_instruction_fragments`で本文中の断片を固定します。新sessionは直前のsession参照と
変更出典を持ちます。これらは最低限の構造条件で、文章の意味やcaseの代表性は独立reviewも必要です。

日本語の表記差、別projectの似た文、低順位の必須制約、出典の旧版、訂正と矛盾、
検索前/組立後の取消、予算不足、生成文書内の命令、出典/任意参照の欠落、新session、
KPIだけの改善、失効情報のrollback、no-opを、正常ケースと別々に記録します。

```text
python -m unittest tests.test_frozen_context_corpus -v
```

この段階はschema・fixture・admissionだけを追加します。exact/lexical/ngram/BM25/graphの
比較、Context Pack候補manifest、採点・attestationは後続の評価器PRで接続します。
embedding、vector DB、reranker、private dataset、本番Gatewayは採用しません。
