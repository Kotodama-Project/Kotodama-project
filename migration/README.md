# Migration ledger directory

このディレクトリは、公開移行台帳 `public-migration-ledger.v1.jsonl` の置き場です。

**台帳ファイルは現時点で not yet populated です。** 契約（schema、verifier、
tests、fixture）だけが先に入っています。

理由は単純です。1 レコードは実在する `subject_digest` と
`private_receipt_digest` を必要としますが、それらは private control plane が
receipt を出して初めて確定します。まだ存在しない digest を埋めた台帳は、
形式的には検証を通っても中身が偽になります。この repository の既定に従い、
値が無いものは埋めずに空けておきます。

台帳を作る手順は次の通りです。

1. private control plane で対象ごとの receipt を発行し、opaque な receipt
   参照と digest を確定する。
2. `docs/PUBLIC-MIGRATION-LEDGER.md` の語彙に従ってレコードを組み立て、
   `tools/validate_public_migration_ledger.py` の `canonical_content_hash()`
   で `content_hash` を計算し、`prev_hash` を直前レコードの `content_hash`
   に束縛する。
3. 1 行 1 レコードの JSONL としてこのディレクトリへ追記する。
4. 次を実行し、`LEDGER_CONSISTENT_UNVERIFIED` を確認する。

```
python tools/validate_public_migration_ledger.py migration/public-migration-ledger.v1.jsonl
```

台帳が空、または存在しない状態で verifier を実行すると `INPUT_INVALID` で
fail-closed します。これは意図した挙動で、空の台帳を「移行対象なし」と
読み替えないためのものです。

台帳が整合しても、移行の実行、private 継続性、公開、Promotion、Current Truth、
Public Beta GO のいずれも意味しません。Public Beta は `NO_GO_UNPUBLISHED` の
ままです。
