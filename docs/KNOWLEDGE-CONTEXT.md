# 統一された知識context v2

実行器へ渡す文脈は `kotodama.generated-knowledge-context` / `v2` に統一します。
[schema](../schemas/knowledge-context-bundle.schema.json)は一つで、旧ファイル名に含まれる
bundleという語は別の`knowledge_context_bundle`形式を導入する意味ではありません。
`tools/knowledge_context.py`がenvelopeとdigestを生成し、KBもこの関数を使います。

全producerは16の同じ欄を持ちます。既存のkind、版、bundle、source digest、評価時刻、
authority、state、filters、Concepts、omitted/unresolved IDs、consumer ruleに、
`errors`、`work`、`claims`、`context_sha256`を加えました。

KBの文脈は`work: null`です。Workの文脈はConceptsとselectorを空にし、`work`へ
package/subjectのdigest、既存Work参照、目的、選択した主張、出典のdigest/期限/感度、
仮定・質問・矛盾、受入条件、成果物のdigestとcriterion参照を入れます。
受入状態はproducerの`reported_state`で、独立検証ではありません。
Workのcompilerと既存assertionの復元は#137の後続sliceで、この形式へ接続します。

digestは`context_sha256`をnullにした全体を、キー順・compact JSON・UTF-8で符号化して
SHA-256を取ります。整数の別表記は正規化し、非整数の数値はこの形式では扱いません。
CLIから実際に出たbytesの外側のpinとは別で、両方を確認します。基になるsource digestは
既存ownerが現在と確認した値を使い、入力自身のhashだけで本人性やACLを認証しません。

Node adapterはv2を明示的に受け付けます。source/context pin、版、時刻、状態、入力上限、
閉じた欄とfalseの権限claimsを確認します。Workの感度は呼出側の`sensitivityCeiling`
（既定public）以内に限り、出典の期限、関連主張、受入条件と成果物の対応を照合します。
これは閲覧許可やTask実行grantの代替ではありません。

旧v1や旧familyは自動変換せず拒否します。必要なconsumerを更新し、元の出典から再生成して
新しいdigestへ束縛してください。過去の文脈・receiptのdigestは付け替えません。
producerがready_candidateでも、利用先の16KiB等の予算や現在の権限確認は別に必要です。

`claims`はHuman approval・reviewer identity・意味的支持・実行・Promotion・Current Truthを
すべてfalseのまま保持します。拒否はneeds_resolutionで、Workの識別子・目的・受入・成果物を
消し、構造化した理由を返します。新しいTask ownerや知識の正本は作りません。
