# 利用者の意図から見るテスト監査

対象基準: PR #64 `e0460b31da0032e7028559b7aa184c737784a833`。画面系統は別PR #47に存在し、本変更へ統合済みとは扱わない。

## 判定の意味

テストは「現在の実装と同じ値が出た」ではなく、利用者が目的を達成するための条件を反証できることが必要。既存の67 Pythonテストファイル・638 testメソッドをASTで台帳化し、assertion、呼出、行、decoratorを保存する。**AST調査は全638件の意味・網羅性を人間が精査した証明ではない。** 既存スイートの成功、構造台帳、今回の利用者起点の検証を別々に読む。

| 層 | 実際に確かめるもの | この層だけで証明しないもの |
| --- | --- | --- |
| 文書・スキーマ検査 | 記載、参照、設計上の制約が維持される | 操作画面・実サービスが動くこと |
| 診断kernel | 鮮度、Work/run、停止、自己検証の扱い | 実観測の真正性・利用者の閲覧権限 |
| Knowledge Context | 出典の実bytes、訂正、受入条件、予算 | AIの意味理解、主張の意味的正しさ |
| Git/SQLite/child process演習 | 実ローカル保存・競合・再開・訂正 | 実会社の本人確認・顧客送信・実機 |
| 別系統のブラウザ試験 | 実clientのDOM・操作・応答順・幅 | Native OS、Gatekeeper、実CodexまでのE2E |

## 216件のシナリオ台帳

12職務（経営、業務管理、営業、顧客対応、経理、人事、PM、開発、運用、契約審査、調査、外部協力）と18場面。16の実装検査を12パラメーターで実行して192件、実会話→Workと実業務操作の2経路×12は24件をBLOCKEDとして残す。

実装へ渡す入力は事前に構造化した合成fixture。日本語の依頼はレビュー用で、LLMへ送っていない。216エージェント、216独立機能、実会社216業務の成功ではない。別プロセスで同じ試験を再実行しても新しいケースとして加算しない。

```sh
python tools/run_persona_intent_audit.py > persona-results.json
python tools/run_persona_intent_audit.py --inventory > test-intent-inventory.json
python -B -m unittest discover -s tests -p test_persona_intent.py -v
```

固定した基準checkoutに同じoracleを当てるときは`--root`を使う。期待値は実装の出力から生成しない。新しい表示引数の有無は呼出方法の適応にだけ使い、必要な情報の判定条件は変えない。

## 改善した境界

### 引継ぎに合格条件を残す

従来の派生contextは目的・claims等を残す一方、criteriaとdeliverableの結びつきを返さなかった。出力を**knowledge_context_bundle v2**へ更新し、acceptance_criteriaとdeliverable_bindingsを必須化する。元のpackage形式はv1のまま。追加情報もbyte上限に含め、入り切らなければ拒否し、重要条件を切り捨ててREADYにしない。CLIのUTF-8出力も同じ予算で確認する。

`reported_state`は作成者からの報告で、独立検証・採用・実行許可ではない。全claims=falseを維持。拒否時は追加の条件・成果物情報も消す。source/deliverable本文やfilesystem pathは追加しない。

v1限定consumerは明示的にv2を受け入れる変更が必要。過去のcontext digestを付け替えず、元packageから派生物を再生成する。既存Work、実行journal、Current Truthの移行や採用は行わない。

### 状態を見て判断できるが、守秘を壊さない

Markdownへ評価時刻、停止のrequested/observed、独立検証not_evaluated、最終観測を表示する。Work/run、名前・担当目的は既定でwithheld。正当に取得したローカル入力を操作者が表示する場合のみ`--include-context`を選ぶ。このフラグは認可ではなく、Webへ安全に公開できるという意味でもない。JSONの既存診断契約は変更しない。

初期修正で目的を無条件表示したところ、既存`test_markdown_exposes_next_steps_without_private_display_text`が失敗した。このテストの守秘意図を維持し、期待値を緩めず表示設計を修正した。明示表示でもMarkdown/HTML構文を無害な文字列として扱う。

## 残る受入条件

実会話の曖昧さ・矛盾・発言者権限を正しく解決すること、許可された出典を本人の画面から参照すること、受入条件と同じ実Workをexecutorへ送り独立検証を戻すことは未接続。拒否テストの成功を「顧客への回答・返金等を完了できた」に置き換えない。

STATUSの鮮度警告や既存の未分類ファイルを日付変更・除外で隠さない。未解消のCompose入力問題、他のPRの本体統合、独立した人間レビュー・マージ・配備は別途の残件。
