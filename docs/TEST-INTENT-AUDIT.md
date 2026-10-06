# 利用者の意図を保持する合成試験

公開#65 `d3452ed7cfd46bb689b83372ec5305307cae4cc5`の監査を、#136のoffline状態投影と
#137の[統一context v2](KNOWLEDGE-CONTEXT.md)へ接続します。実行結果の`source_sha256`が
検査した実装を固定します。テスト件数や古いmainのSHAを現在の実行証拠に置き換えません。

12職務×18場面の216件のうち、16種類の実装動作×12パラメーターが192件です。
実会話からWorkを作る経路と実業務操作の2種類×12件はBLOCKEDとして残ります。
これは216の独立した機能や実業務の成功ではありません。日本語の依頼文はreview用で、
LLMへ送らず、事前に構造化した合成fixtureを既存の実装へ渡します。

```sh
python -B tools/run_persona_intent_audit.py > persona-results.json
python -B tools/run_persona_intent_audit.py --inventory > test-intent-inventory.json
python -B -m unittest tests.test_persona_intent -v
```

`--inventory`は現在のtestsからAST、assertion、呼出、行、decoratorを列挙します。
本文を意味的に全件reviewした証明ではありません。`--root`で別のoperator選択checkoutを
検査する場合は新しいPython processを使います。他checkoutのmoduleが既に読み込まれていれば
root不一致で拒否し、そのbytesを調べたと偽ってhashだけを表示しません。

## 検査する境界

| 層 | 実際の検査 | 証明しないこと |
|---|---|---|
| Work context | 元のbytes、出典変更・期限・感度、訂正した受入条件、成果物参照、予算 | 意味の正しさ、LLMの理解、業務完了 |
| agent診断 | 鮮度、Work/run、停止要求と観測、自己申告の検証状態、表示の無害化 | 本人性、実稼働、閲覧権限、実行許可 |
| AST一覧 | 各testの構造と呼出 | 網羅性や人間による意味的review |

受入条件と成果物の対応は`work.acceptance_criteria`と`work.deliverable_bindings`で照合します。
旧`knowledge_context_bundle`を併存させず、共通v2のschemaで成功と拒否の両方を検査します。
拒否時は`work`とsource digestがnullで、本文・条件・成果物を残しません。受入条件の訂正が
context digestを変えること、CLIから出た実UTF-8 bytesが指定予算内であることも確かめます。
旧版からの変更は欄とready/refusalの名前の対応です。16動作と192 PASS / 24 BLOCKEDの
意味は維持し、BLOCKEDを件数調整のためにPASSへ変えません。

診断入力のlegacy v1 registryは、未認証のoffline snapshotを表示する合成fixtureです。
現行の責任索引v2をactiveへ変えたり、実agent registryとして採用したりしません。
CLIのJSON・Markdownは既定で名前・目的・Work/runを伏せます。`--include-context`は
表示選択で、閲覧権限を付与しません。明示表示でもMarkdown/HTMLを無害化します。

## CIと未受入

任意のpersona workflowは関係pathに限定し、現在のaction pinとhash付き`requirements-ci.txt`
を使います。full regressionは既存の必須CIに任せ、このworkflowでは重複実行しません。
FAILが一件でもあれば失敗します。24 BLOCKEDが残る正常な合成結果でworkflowが緑でも、
会話理解・認証済みの実Work接続・送信や返金等の業務操作は受入済みになりません。
schema/診断のLOCAL_PASSと、device/provider/humanの受入を別々に追跡します。
