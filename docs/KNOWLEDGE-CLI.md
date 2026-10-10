# 小さな知識をCLIで探し、必要な節だけ読む

元の目的を検索の変数として残し、結果のIDから一つのConcept、必要な節、限定contextへ進みます。
正本の公開知識は[OKF Markdown](KNOWLEDGE-BASE.md)、目的の定義は
[Goal](../knowledge/project/goal.md)と[KGI](../knowledge/project/success-model.md)です。

## 準備

source checkoutのrootでPython 3.12と[hash固定の依存](CI.md)を使います。
この入口は`tools/knowledge_base.py`です。現在のNode `kotodama`と配布候補の
`kotodama-core`へは未接続で、Discord設定や起動中のBotは不要です。

```bash
python -S -B tools/check_tracked_secret_hygiene.py
python -m pip install --require-hashes -r requirements-ci.txt
python -B tools/knowledge_base.py validate
```

Windows PowerShellも同じ引数を使えます。`--root PATH`で対象checkoutを明示できます。
CLIは外部URLを取得せず、private donorを自動巡回しません。

任意のSQLite索引の構築・検証・利用と未達の性能条件は[永続索引](KNOWLEDGE-INDEX.md)を参照します。

## 目的を保って検索する

```bash
python -B tools/knowledge_base.py query KGI --goal OUT-INTENT --kgi KGI-INTENT --json
python -B tools/knowledge_base.py query context --initiative INIT-METHOD-RENEWAL --limit 5
```

| 入力 | 意味 |
|---|---|
| `--goal` | 元の成果の型付き参照。例: `OUT-INTENT` |
| `--kgi` | その成果を測る定義への参照。例: `KGI-INTENT` |
| `--initiative` | 改善候補の定義への参照。例: `INIT-METHOD-RENEWAL` |
| `--type` / `--tag` | Conceptの型・tagを絞る |
| `--limit` | 順位付け後の結果件数。1〜100 |

同じ種類の参照は繰り返してOR指定でき、異なる種類はANDです。絞込みは順位付けと
`--limit`の前に適用します。未知の参照はexit 2で拒否し、成功の空配列にしません。
JSONは実際の参照filters、source digest、鮮度を評価した`as_of`、scoreと理由、出典を返します。
参照の指定はGoalの採用、数値targetの設定、Task作成や実行の許可にはなりません。

## 一つのConceptから必要な節を読む

```bash
python -B tools/knowledge_base.py show project/goal --json
python -B tools/knowledge_base.py show project/goal --section "Required properties" --max-chars 2000
```

`show`は本文を返し、YAML frontmatterは本文へ混ぜません。metadataは同じConceptから
返し、JSONとMarkdownでID、repository相対path、選択範囲の1始まりの行番号、Conceptの
SHA-256、bundleのsource digest、`as_of`、出典、knowledge stateとtrustを確認できます。
行番号は選択全体の範囲です。`offset`はその選択内のUnicode文字位置で、行番号ではありません。

節は`#`〜`######`のATX見出しの文字列で指定します。同じlevel以上の次の見出しの直前まで、
子見出しを含めて返します。code fence内の見出しは選択候補にしません。重複する見出しは
曖昧として拒否し、不在の節や任意file pathも読みません。Setext見出しやblockquote内の
見出しは節指定の対象外です。見出し一覧は最大32件で、省略の有無と総数を示します。
list・blockquote内のfenceは未対応として、節指定を`SHOW_SECTION_STRUCTURE_UNSUPPORTED`で
拒否します。Concept全体は読めますが、`sections_supported: false`と空の見出し一覧を返します。
本文中の脚注の定義が節の外にある場合は、Concept全体と表示された出典を確認します。

本文の既定上限は4,000文字、指定範囲は1〜65,536文字です。これはmetadataを含む
応答全体のbyte上限ではありません。切詰めはJSONの`truncated`と`next_offset`、
Markdownの`PARTIAL`へ必ず出します。

続きはJSONの`resume_args`を**shell文字列に連結せず、引数配列として**使います。
引数配列は同じcheckout root・ID・section・source digest・audit instantとJSON形式を保持します。例:

```bash
python -B tools/knowledge_base.py show project/goal --offset 4000 --expected-digest SOURCE_DIGEST --as-of AUDIT_INSTANT --json
```

`SOURCE_DIGEST`と`AUDIT_INSTANT`は前の応答へ置き換えます。`--offset`が0より大きい
読取りは`--expected-digest`が必須です。Conceptや参照資料が変わったら続きも拒否し、
最初から新しいsnapshotで読みます。明示された過去の`--as-of`は歴史的監査で、
現在の鮮度や実行の適格性を証明しません。CLIは応答の直前にも現在の出典bytesを再照合します。

取消・deprecated・stale・非discoverableのConceptと無効bundleは`show`で返しません。
`query --include-stale`は診断用の一覧に限り、`show`の鮮度拒否を解除しません。

## 限定contextへ進む

```bash
python -B tools/knowledge_base.py context --goal OUT-INTENT --max-concepts 12 --json
```

検索上位の本文をそのまま実行入力にしません。既存context selectorで必須のGoal・
governanceを保持し、欠落・鮮度・予算を確認します。actor/purposeのdecision readinessと
実入力への束縛は[Context Pack](KNOWLEDGE-CONTEXT.md)と[lineage](KNOWLEDGE-LINEAGE.md)で
別に確認します。取得した指示文はgrantやDecisionではありません。

## 小単位で知識を保つ

一つのConceptには、一つの問い・定義・判断材料・検証方法を置きます。
titleとdescriptionで読む必要を判断できるようにし、安定したID、出典、生成/独立検証、
鮮度期限、state、担当とreview担当、Goal/KGI/initiativeの参照を既存profileへ記録します。
本文は目的、根拠、制約、検証、未確定、次の参照に短く分け、関連Conceptへリンクします。
原会話や旧文書を丸ごと転載せず、訂正は既存source/Task ownerのrevisionへ戻します。
候補を確認済みの知識へ自己昇格しません。

## 後続の受入

| Issue | 次に実証すること |
|---|---|
| [#326](https://github.com/Kotodama-Project/Kotodama-project/issues/326) | 再構築可能な永続索引、日本語検索、cold/warm CLIの規模別性能、配布入口 |
| [#327](https://github.com/Kotodama-Project/Kotodama-project/issues/327) | 原意図・訂正・目的/制約/許可/予算/停止を既存Contextと実executorへ束縛 |
| [#328](https://github.com/Kotodama-Project/Kotodama-project/issues/328) | 仮説・実験・独立検証・rollback・出典付き学びの限定改善経路 |

現行検索は全Conceptを読む字句baselineで、大規模な永続DB検索の実証ではありません。
各1MiB、合計8MiB、256入力filesの境界も維持します。検索速度、検索品質、実Task成果を
それぞれ測定し、文書数やPR数で達成を代替しません。`NO_GO_UNPUBLISHED`を維持します。
