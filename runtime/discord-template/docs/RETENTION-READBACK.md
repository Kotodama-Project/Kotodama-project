# 削除receiptの現物照合

`verify-deletion`は、既存retention ownerによる原音削除の**後**に使います。
このコマンド自身は削除も保持期間の変更もしません。既存runtimeのloopback controlへ依頼し、
同じStore writerが本文を含まない`retention.deletion_readback` eventを記録します。
別のarchive台帳やledger状態は作りません。

```sh
node bin/kotodama.mjs verify-deletion --config /private/config.json --actor OPERATOR_ID --file /private/receipt.json --scope /private/owner-scope.json --json
```

認証済みruntimeを起動しておく必要があります。archiveの録音機能は停止していても確認できます。
actorは現在のoperatorかつarchive.actorId、Task ownerはlocalである必要があります。
receiptとscopeはprivateファイルです。CLIはそれぞれ180,000/8,192 bytesに制限し、
重複JSONキー、不正UTF-8、深さ超過、ネットワークpath、symlink/hardlinkを拒否します。

## ownerが用意する入力

receiptは[公開契約](../../../docs/RETENTION-DELETION-RECEIPT.md)に従います。
単独配布templateでは`src/retention-deletion-receipt.schema.json`が同じ契約です。
このprojectionは正本とのbytes一致をroot試験で検査し、既存runtime source integrityの対象にも含めます。
schemaは保持方針を決めず、rawと文字起こしを削除したときの双方を表現できます。

scopeはownerが既存ledgerと保存台帳から作る一回の照合入力です。新しいSession IDを発行しません。

```json
{
  "archive_session_id": "session-synthetic",
  "archive_policy_ref": "ref/policy/synthetic",
  "session_ref": "ref/session/synthetic",
  "policy_ref": "ref/policy/synthetic",
  "policy_revision_ref": "ref/policy-revision/synthetic",
  "archive_binding_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "delete_by": "2026-10-08T00:00:00Z"
}
```

これは合成の説明例であり、そのまま使える削除証拠ではありません。
archive_session_idとarchive_policy_refは保存時binding/configと一致させ、session_refとpolicy refsは
既存ownerのopaque refへ対応付けます。delete_byは承認済みpolicyの実期限を渡します。
コマンドはこの対応の真正性を認証できないため、結果は常に`receipt_authenticity:UNVERIFIED`です。
scopeから実行許可やledgerへの昇格を作りません。scope/receiptは共有画面や公開Gitへ置かないでください。

## 初版で確認する範囲

- 完了した一つのarchive sessionのみ。保存時binding・保存receipt・configとpolicyの一致を検査します。
- 全PCM/MP3のmanifest項目を、種類・件数・内容hash・項目hashの組で照合します。
  mixed/個別音声の内容が同じでも、別manifest項目として照合します。
- session directory内の原音が無く、archive journalの該当PCM行が0であることを二度読み戻します。
  別名の余分なファイル、子directory、link、変更されたmanifestも拒否します。
- 現行policyの30日raw保持をmetadata.endedAtに束縛します。文字起こし・訂正・Source Evidenceは
  retained_by_policyで明示し、journal/Storeと実ファイルの一致を確認します。
- operator、archive/config binding、shutdown、Source、journalを非同期読取の後にも確認します。
- 現在の実時計がdelete_byを過ぎていれば拒否します。過去のreceipt時刻を現在の受入時刻に使いません。
  同じreceiptの再送も現物を検査します。内容の違う同じreceipt_refは拒否します。

この初版はRAW_AUDIO_PCM/RAW_AUDIO_ENCODEDの全件削除と、RAW_ASR/CORRECTED_TRANSCRIPT/
SOURCE_EVIDENCEの保持だけを受け付けます。文字起こし削除、追加segment形式、未完了録音、
失敗stagingの回収は既存ownerによる別の対象・期限契約が必要です。
markerは中立な内容schemaで見分け、private側の名前を契約に固定しません。

## 受入と限界

結果の`LOCAL_READBACK_ONLY`は、確認時の対象sessionとjournalの論理状態です。ディスク上の
消去済みpage/WAL、snapshot、backup、他の保存先の物理消去や、敵対的なOS writerに対する
複数pathの原子的snapshotは証明しません。retention ownerはそれらの対象を別途管理します。
runtimeは原音削除が実際に宣言時刻に行われたことも認証しません。

1. private ownerが対象manifestとpolicy/revisionを固定し、許可された削除を実行する。
2. ownerが全対象とbackupsを再読し、残存ゼロを確認してからreceiptとscopeを発行する。
3. 期限内に本コマンドで照合し、失敗時は原因を解決してから再照合する。失敗を成功に書き換えない。
4. ownerが既存ledgerのdeletion_receipt_refを紐付け、実データ・期限・撤回の証拠を人が受け入れる。

合成試験の通過はPB-G3、Public Beta、Human GOにはなりません。記録の3つのGO/authority値は
常にfalseです。稼働中の保持処理と本番データはこの変更では操作していません。
