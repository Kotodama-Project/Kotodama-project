# 保持期限による削除receipt

この[receipt schema](../schemas/retention-deletion-receipt.schema.json)は、既存
[Session / Conversation ledger](SESSION-CONVERSATION-LEDGER.md)の`deletion_receipt_ref`が
参照する証拠objectです。別の保持policy・削除実行器・状態の正本は作りません。

```sh
python -B tools/validate_retention_deletion_receipt.py examples/retention-deletion/synthetic-receipt.json --as-of 2026-10-07T00:00:00Z
python -B -m unittest tests.test_retention_deletion_receipt -v
```

このCLIが読むのはreceipt自身です。PASSは構造と内部整合の検査だけで、ファイルの不在、
削除の実行、receiptの真正性は検証しません。reportのclaimsはfalse、scopeはSTRUCTURAL_ONLYです。
`--as-of`は歴史的な構造評価に使え、実際に使ったUTC時刻をreportへ残します。現在のreadbackを
過去へ付け替える引数ではありません。Node側で現物を再読する口は#149後半で接続します。

## 内容と対象の区別

receiptには本文・path・host・Discord IDを埋め込みません。ledgerと同じ安全なopaque refを
使い、保存時のarchive binding digest、policy/ref、期限、種類・件数、readbackだけを持ちます。

各artifact groupの`pre_delete_sha256`は削除前の内容digestです。同じ順序の
`manifest_entry_sha256`は保存済みmanifestの一項目`{ref, size, sha256}`を、キー順のcompact
JSON・UTF-8で符号化したSHA-256です。refはこのhashの入力にだけ使い、receiptへ載せません。
一人の原音ではmixedと個別trackのbytesが同じになるため、内容digestの一致は許容し、
同じmanifest項目の二重計上を拒否します。種類ごとの件数は両配列と一致させます。

合計1024artifact、同じ種類は一group、同じmanifest項目は全groupで一回に限定します。
削除した種類と`retained_by_policy`に重なる種類を拒否します。空の削除結果を成功receiptにはしません。
再実行で新しい削除が無い場合は、既存receiptの読み戻しやno-opとして扱います。

## 時刻とreadback

expiryではretain_untilより前の削除を拒否し、delete_byはretain_until以後です。
withdrawal/source_deleteは元の保持期限より早い削除を表現できますが、権限はこのreceiptから作りません。
削除・readbackともdelete_by以前、readbackは削除以後で、評価時刻より未来でないことが必要です。
readbackはCONFIRMED、residual_countは0だけを受け付け、欠落・残存・不明をPASSにしません。

## 既存ownerへ渡す境界

現行のrawAudioDays=30、transcriptDays/derivedTextDays=nullを変更しません。現行policyで
残す文字起こし等を`retained_by_policy`へ明記し、「全部削除」と読み替えないでください。
実期限、対象、withdrawal等の権限は既存retention ownerが決めます。

private側は保存済みmanifestとpolicyの版を固定し、許可された削除を行い、同じ対象を再読して
残存ゼロを確認してからreceiptを出します。Node側の再検査と既存ledgerへの記録は別の工程です。
公開contractの試験は合成データだけです。実データでの実行、文字起こしの保持変更、PB-G3と
Public Beta/Final Human GOの受入は人の作業として残ります。
