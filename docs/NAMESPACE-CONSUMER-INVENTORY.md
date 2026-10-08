# namespace移行前の読み取り専用inventory

#26のprivate consumer調査用ツールです。固定Git commitのobjectだけを読み、PythonのAST、
文字列、設定、文書のcode領域から`runtime`、`kotodama`、`kotodama-core`、
`kotodama-control-plane`、`ktdm`の参照候補を抽出します。対象コードのimportや実行はしません。

```text
python -B tools/inventory_namespace_consumers.py --source-git PRIVATE_CHECKOUT --commit EXACT_COMMIT --private-output ../private-work/namespace-inventory.json
```

Python 3.12で実行し、Gitの40/64桁の完全commit IDを指定します。出力先のparentは事前に
用意し、ツール自身のrepositoryと調査対象repositoryの両方の外を明示します。
既存ファイルへの上書きは拒否します。対象はcheckout不要ですが、必要なGit objectは
事前に取得してください。調査中のlazy fetch、filter実行、source書込みは行いません。

## 記録するもの

commit/tree、tree一覧digest、scannerのbytes digestとPython版、path/blob/mode、読んだ
本文のSHA-256、構文種別、行とUTF-8 byte column、固定namespace名、提案dispositionです。
元の文字列値・本文・絶対保存先・remote URLは記録しません。path自体はprivate metadataに
なり得るため、出力を公開GitやIssueへ貼らないでください。stdoutは件数・種別・digestだけです。

単純なimportとalias、相対import、直接のimportlib呼出し、resource/serialized名を含む
文字列候補を区別します。同じ行の別consumerも保持します。Markdownの通常のproseは
CLI consumerとせず、code fenceとinline codeだけを候補にします。prefixが似ている別名は
対象にしません。生成物の明示headerとuv.lockはgenerated hintとして示し、再生成案にします。
hintはgeneratorの本人性や正本を認証するものではありません。

## 調査範囲と未確定事項

1 fileは4MiB、読取全体は256MiB、tree一覧は8MiB、出力は32MiBまでです。link/gitlink、
非text形式、上限超過、decode/parse不能、計算で決まるimportなどは未確認の行として残します。
working treeの未commit差分、環境設定、外部の配備caller、実import到達性は検査しません。
任意のPython動作や間接呼出しを完全に静的解決できるとは主張しません。

構文上の候補数は、実際の運用consumer数ではありません。提案がrenameやshimであっても、
各行のfinal dispositionは`BLOCKED`、owner/release/互換receiptは未入力です。
外部consumerも別の`BLOCKED`として保持します。semantic coverageとcutover authorityはfalseです。
この出力は移行の正本を置き換えず、private ownerの既存台帳へ照合するSource Evidence候補です。

ownerが候補を一つずつ確認し、生成元・互換の実行・2 minor releaseのalias保持・rollbackを
証拠へ結んでから既存台帳へ採用します。未確認を0件や移行完了と読み替えず、private source、
履歴、実設定を公開側へ移しません。公開core側は[package契約](../python/README.md)を参照します。
