# Taskの目的・訂正・制約を入力へ束縛する

[Task swarm](TASK-SWARM-RUN.md)の既存ownerとrunnerが、任意のversion 2入力を
扱います。version 1の入力・既定予算・出力は維持します。これは
[#327](https://github.com/Kotodama-Project/Kotodama-project/issues/327)の最初の実装範囲です。
Markdown検索からの自動解決、Discordでの生成、履歴の独立検証は未接続です。

狙いは[元の意図](OWNER-INTENT-COMPANY-AGI.md)を保持したまま、最新の依頼・制約・
未知をworkerと独立verifierへ渡すことです。Taskの正本、承認、権限発行、成果の採用は
既存ownerのままです。入力を検査しただけで依頼の達成や`KGI-INTENT`達成とはしません。

## 同じTask入力への追加

version 2はversion 1の6項目に`objective`を追加します。共通の上限は依頼4,000文字、
受入条件20件、Source 10件・各12,000文字、全JSON 256 KiBです。
`objective`は次の閉じた形です。省略値の推測や余分な項目の読み捨てはしません。

| 項目 | 入力と検査 |
|---|---|
| `owner_ref` | 現在のTask bindingのownerと完全一致 |
| `intent.original` | 元の依頼のSource span。本文を別に複製しない |
| `intent.replacements` | 最大9件。同じSource keyのrevisionが厳密に増加する、依頼全体の訂正版 |
| `references` | 最大20件の`kind`、`id`、`source`。少なくとも1件のgoalが必要 |
| `constraints` | 最大20件の現在Source span。1件1,000文字以下 |
| `unknowns` | 最大20件の現在Source span。1件1,000文字以下。値で補完しない |
| `acceptance` | 現在Source spanの配列。本文と順序が既存`acceptance`に完全一致 |
| `budget` | `attempt_budget`は4〜6、`deadline`は現在時刻より後かつ既存bindingの期限以下 |
| `stop_conditions` | `cancelled`、`binding_changed`、`deadline_exceeded`の順序付き配列 |
| `rollback` | `not_applicable_read_only`。このrunnerは読取調査の範囲で動く |

spanは`source_key`、`source_revision`、`start`、`end`の4項目だけです。
位置はPythonの文字列indexと同じUnicode code point単位、終端は含みません。
指すSource key/revisionが入力内に存在し、その本文digestが一致している必要があります。
現在のspanは、同じkeyで入力へ渡された最大revisionを参照します。
元の依頼と途中の訂正版だけは、その入力内の過去revisionを参照できます。

最後の訂正版、訂正がなければ元の依頼が、現在の`request`と完全一致する必要があります。
訂正版は単なる差分ではなく、既存ownerが用意した現在の依頼全文です。
訂正を適用する意味の判断、欠けた履歴の探索や補完を、このvalidatorは行いません。

`references`の形は次のとおりです。

```json
{
  "kind": "goal",
  "id": "OUT-INTENT",
  "source": {
    "source_key": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "source_revision": 2,
    "start": 0,
    "end": 10
  }
}
```

これは構造例であり、対応するSource本文・digest・Task bindingを含む実行入力ではありません。
`kind`は`goal`、`kgi`、`initiative`で、IDはそれぞれ`OUT-`、`KGI-`、`INIT-`形式です。
spanの本文はIDと完全一致しなければなりません。重複、未解決のSource、古い現在参照を拒否します。
この検査は入力中の参照を照合するものです。公開knowledge catalogへの存在・型・採用を
独立に確認したことにはなりません。既存catalogのresolver接続は後続です。

## plan・worker・review・再開

既存の`task-run --owner ... --input ...`がversion 2を受け取ります。
呼出し元は同じownerが承認する全入力の`context_digest`とSourceの`source_checks`を
更新しなければなりません。既存のactor、grant、親の生存確認はそのまま必要です。
新しい実行経路や権限の代替にはしません。

全入力は既存workerのpromptと、独立verifierのpromptへ渡り、各jobのpayload digest、
入力artifact、reviewのcontext digest、最終receiptへ束縛されます。
制約は`O1`以降、未知を確定値へ置き換えない条件は`Q1`以降として、既存の`C1`〜`C4`と
`U1`以降へ追加します。verifierの条件欠落・古い入力digestを拒否します。
引用や構造の一致だけで、その内容やverifierの判断の正しさを証明するわけではありません。

3 workerと1 verifier、同時実行3、verifier予約1は維持します。
version 2で指定した試行数と期限は既定値を狭めるだけで、grantの期限を延ばしません。
取消・binding変更・期限超過では既存runnerが停止し、成功receiptを出しません。
利用者固有の停止条件や金額・token予算の実測制御は、この版に含めません。

同じTask ID/revisionでは同じrun IDです。入力や目的を変えて過去の成功を使い回せず、
元のreceipt hashを伴う同一入力だけを再読します。完了後の再読はobjectiveの実行期限を
過ぎても可能ですが、owner自体の有効期限・取消・入力とartifactの照合は維持します。
再読を指定して未作成runを実行することはできません。現在の訂正を採用する際のTask revision更新は
既存ownerが行います。runnerはTask更新やCASの代行をしません。
全条件がpassedでも結果は`needs_review`であり、ownerの成果採用、実利用受入、
PromotionやCurrent Truthの変更を意味しません。

## 検証範囲と残り

合成テストはv1互換、v2のspanと訂正順、現在参照、予算、制約・未知のreview coverage、
実worker prompt生成、既存runnerの保存・再読・期限停止を検査します。
モデル、Discord、実利用者の受入は実行していません。

Sourceの本文digestとownerによる全入力の束縛は、履歴の完全性や出典本人性の独立実証とは
別です。この版は`history_verified`などの肯定的な判定を作りません。
原意や過去の本文を取得・確認できない場合、callerはそれを検証済みのspanとして作らず、
v2の準備を止めて欠落を元のTaskへ返します。別台帳で履歴を作り直しません。

残る#327の範囲は、既存knowledge resolverによるID・revision解決、採用状態と
Context Packへの束縛、訂正差分からの現在依頼形成、Discord入口、inspect/validate/planの
CLIと共通schema、金額・token・個別停止条件の制御です。
公開面の状態は`NO_GO_UNPUBLISHED`のままです。
