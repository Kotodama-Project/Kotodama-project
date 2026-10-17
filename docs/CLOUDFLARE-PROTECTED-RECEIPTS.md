# 保護されたpreview実行とprivate receipt保存先

Issue #10の設定前に使う契約案です。これ自体はEnvironment、credential、保存先の
承認や実装済みのnonce serviceを作りません。実uploadは固定candidateに結び付いた
Work Orderと別担当者のEnvironment承認が成立してから行います。

## 実行前に読み戻すもの

- 対象account、現在のWorkers entitlement、追加費用の上限、既存versionとrollback先。
- tokenの対象がそのaccount一つで、Workers Scripts Writeに限定され、期限・取消状態が
  有効であるというprivate証拠。secretの名前や更新日時だけでは代用しない。
- Environmentのrequired reviewer、prevent self-review、管理者bypass禁止、配備branchが
  mainだけであること。実行者と異なる登録reviewerが現在承認可能であること。
- workflowの2 jobがUbuntu 24.04に固定され、validatorのbytesがdispatchしたmain SHAへ
  束縛されること。runner labelだけでimageや実hostの隔離を証明しない。
- 承認前と承認後のremote main tip、実checkout SHA、runner image/version、run/job/attempt。
- 8つのbinding名が揃うこと。値は出力しない。実行前にtarget/scopeをprivateで照合する。
- 信頼するclock、one-time nonceの発行者・用途・期限・消費先。run IDは識別子であり、
  それだけで権限やnonce消費を証明しない。発行者と消費記録が未定ならuploadを止める。

必要なbindingは[Worker手順](../runtime/cloudflare-edge/README.md#runtime-bindings)の6つと
`CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_API_TOKEN`です。現在値は実行のたびに読み戻し、
過去のtoken期限やreviewer人数から自動的に設定変更・再発行を決めません。

## 保存先の契約案

ownerは公開repository/GitHub artifact以外の、暗号化・明示ACL・backup/restoreを備えた
private evidence保存先を一つ選びます。既存の正本があればそこを使い、別のTask台帳を作りません。
相対layoutの例は `receipts/<run-id>/<attempt>/<candidate-sha>/`。実path、hostname、
account/zone ID、person IDを公開文書へ写しません。

保存するのは閉schemaを通した棚卸し・preview receipt、対象commit/tree、runner imageの
digest/版、workflow/actionの固定SHA、run/job/attempt、Work Order/承認/nonce記録への
digest参照、header-only読み戻し結果、各ファイルのSHA-256です。元のprivate対応表や署名の
検証材料はそれぞれのownerが管理し、このcontent-free bundleへ本文や秘密値を混ぜません。

保存処理は新しいbundle IDへ原子的に確定し、同じIDの上書きを拒否します。read-only化、
利用者別ACL、暗号鍵の保管、保存期間、backup周期、削除承認者をownerが明記します。
GitHub artifactの短期retentionは診断用で、durable receipt sinkの代用ではありません。
保存・digest検証が失敗した場合はprovider実行を継続せず、成功記録も生成しません。

## restoreの受入手順

1. ownerが指定した保存先で、本文を含まない合成bundleを一つ保存する。
2. 別の空directoryへbackupから復元する。現在のbundleや既存記録は上書きしない。
3. ファイル一覧・bytes・SHA-256・閉schema・candidate/run/attemptの対応を独立に照合する。
4. 欠落、1 byte改変、期限切れ、別candidate、nonce再利用、無権限reader、上書きを拒否する。
5. 復元先でもACLと保存期限を確認し、復元担当・時刻・対象digest・結果だけを記録する。
6. 合成restoreの記録は合成として残す。実protected-runのreceiptは別の実bundleで同じ手順を通す。

消したふりの記録、手で記入したPASS、単なるファイル存在確認はrestore evidenceになりません。
実sink、backup鍵、clock/nonce、独立担当が未確定なら未完了として止めます。

## 確認できる範囲

[棚卸し契約](CLOUDFLARE-PROVIDER-INVENTORY.md)と[previewの検査](../runtime/cloudflare-edge/README.md)
はローカルJSONの形・digest・revision・statusを検査します。本人性、秘密値のscope、実restore、
provider操作、公開、Final Human GOはそれぞれ別の受入です。Workers Logsとcacheの扱いは
#9のデータ判断に従い、判断前は有効化しません。Public Betaは`NO_GO_UNPUBLISHED`です。
