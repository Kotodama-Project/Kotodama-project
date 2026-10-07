# 既存Taskに束縛するswarm run（実装中）

#160の採用判断と#286の実装を、既存local Task ownerへ接続するための契約です。
この段階は純粋な入力・出力検査で、Task、grant、processを作成しません。
実行入口・Discord接続・実利用の受入は後続です。

## Task入力と固定plan

入力はversion、Task ID/revision、依頼、最大20件のacceptance、最大10件のSourceです。
Sourceはkey/revision、正確なUTF-8本文とそのSHA-256を持ちます。依頼4,000文字、
Source各12,000文字、全JSON256 KiBまでです。上限超過を切捨てて成功扱いしません。
公開fixtureは合成本文だけです。実運用のpayloadはprivate領域に置きます。

既存ownerが返す9項目のTask bindingを検査し、Task ID/revisionと全入力の
context digest、期限、active/validating状態を照合します。capabilityは
ref/capability/swarm_researchに限定します。この文字列や入力だけで権限が発行される
わけではありません。Node側で本人・現在grant・Sourceアクセスを照合する接続は後続です。

planはfacts、counterpoints、optionsの3 workerと、3報告を依存先に持つ独立review
の4 jobです。N=6、C=3、V=1、depth 1、期限は既存bindingの時刻を固定し、
残り1,260秒より長ければ拒否します。再試行で期限を延ばしません。同じTask ID/revision
は同じrun IDとなり、planの不変性とclaim排他は既存SwarmStateが所有します。

## 報告と独立レビュー

workerの報告はsummary、claims、conflictsを持ち、各claimはsupported/inference/unknown
を区別します。supportedにはTask入力中のSource key/revision、Unicode code point単位の
start/end、完全一致するquoteが必要です。別の版や本文・範囲違いを拒否します。
引用が一致しても意味の正しさやSource本人性を証明したとは扱いません。

独立verifierは依頼・acceptance・資料を含む全Task入力のcontext_digestと、正確な3報告の
digestに束縛され、C1〜C4とすべてのユーザー条件について
passed/failed/blocked/not_runと証拠位置を返します。証拠は実在するjob/claim番号です。
passedには証拠が必要で、C4は3報告すべてを参照します。未検査・拒否にはgap_reasonを
残します。古い報告のreview、条件抜け、重複、無いclaimへの参照は拒否します。

C1は依頼への回答、C2は主張の根拠、C3は推測と事実の区別、C4は3報告の食い違いの明示です。
validatorはverifierの身元や独立した実行を証明しません。後続controllerが別の実行receipt、
current binding、全criteria passed、各jobの受入を照合して初めて同じTaskへneeds_reviewを
返します。構造が正しいだけ、報告件数だけ、quiescentだけでTask完了にしません。

## 残る接続

入力契約の合成試験は、Source改変・古い版・別Task・期限・権限参照・上限・証拠位置・
古いreview・条件抜けを検査します。worker/model dispatch、parent pipe、ownerによる
停止fence、結果file読戻しは次のrunnerへ接続します。モデルは採用済みgpt-5.6-luna/max、
read-onlyを維持し、日次枠の既定は0、live利用枠・有効化・本人ログインは別のowner判断です。
