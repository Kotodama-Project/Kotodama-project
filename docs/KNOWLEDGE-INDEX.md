# 再構築できるローカル知識索引

[小単位CLI](KNOWLEDGE-CLI.md)の検索に、明示したSQLite cacheを使えます。
正本は[既存OKF Markdown](KNOWLEDGE-BASE.md)と、そのprofile・schema・参照資料です。
索引の削除で正本は失われません。Task、Goal、権限、Current Truthを所有する新しい台帳は作りません。

## 作成・確認・検索

Python 3.12と既存の[依存・確認手順](CI.md)を使います。
書込み先の親directoryはあらかじめ用意し、他の資料と共有しない専用の`.sqlite`か`.db`を指定します。
次はcheckoutの一つ上のdirectoryへ保存する例です。

```bash
python -B tools/knowledge_base.py index --database ../kotodama-knowledge.sqlite --json
python -B tools/knowledge_base.py index --database ../kotodama-knowledge.sqlite --check --json
python -B tools/knowledge_base.py query 意図 --index ../kotodama-knowledge.sqlite --goal OUT-INTENT --json
```

`--root`と`--as-of`は既存CLIと同じです。cacheは選んだrootのdigestへ束縛され、同じ内容でも
別rootへの流用は拒否します。標準ではcacheを自動作成・自動検索・自動再構築しません。
`--index`なしの検索は既存の字句baselineです。外部URLの取得、directoryの自動追加、
モデルdownload、embedding、provider接続は行いません。

`index`は追加・本文やmetadataが変わったConceptだけを更新し、削除されたIDを取り除きます。
同じ入力なら検索行や世代を書き直しません。参照資料だけが変わった場合もsource digestを更新します。
行、FTS索引、source digestは一つのtransactionで確定します。中断時は前の世代へrollbackし、
writer競合は有限の待ち時間後に失敗します。失敗した新規cacheには空fileが残る場合があります。

`index --check`はschema・root・source digest・行の内容・SQLiteの整合性を確認します。
FTS5は外部contentとの整合検査にも書込み可能な接続を要求するため、この操作にはcacheの書込み権限と
短いwriter lockが必要です。検査transactionは必ずrollbackし、cacheの内容bytesは変更しません。
別形式の既存DBや非互換schemaを上書き移行しません。不要なcacheだけを削除し、同じコマンドで再構築します。

## 日本語と順位の契約

本文と検索語は既存baselineと同じNFKC・casefoldを使い、同じcode fenceを除きます。
SQLite FTS5のtrigramは**候補の絞込み**に使います。得た候補を元のConceptへ戻し、既存の
score、理由、安定順序、Goal/KGI/initiative、型とtag、期限、取消、discoverableを適用します。
一致条件は元の検索語またはtokenの部分一致で、tokenをAND条件へ変えません。

| JSONの`index.mode` | 意味 |
|---|---|
| `fts5-trigram` | 3文字以上の検索語をFTSで絞込み |
| `substring` | 1・2文字やFTS非対応環境で、SQLite `instr`による部分一致 |
| `fts5-trigram+substring` | 長語と短語が混在し、両方の候補を結合 |

短語fallbackも同じ順位です。LIKE wildcardへの置換や日付順への変更はしません。
短語がほぼ全件に一致する場合は全件の候補を扱うため、索引を使う方が遅い場合があります。
JSONの`candidate_count`は絞込み後・profileによる除外前の件数です。
FTS5/trigramが使えないSQLiteでは構築時に`backend: substring`を返し、拡張のinstallは要求しません。
FTSがあるcacheを未対応環境へ移した場合は、暗黙に読み替えず再構築が必要です。
索引検索の入力上限は正規化後4,096 Unicode文字・64 tokenです。超える場合はexit 2で拒否します。

## 古いcacheの扱い

検索のたびに現在のbundleを読み、元の入力bytesを照合します。mtimeやfile sizeだけを信じません。
cacheの世代が異なると`INDEX_STALE_REBUILD_REQUIRED`でexit 2となり、成功の空配列や古い本文を返しません。
schema、抽出方式、rootが違う場合も明示して拒否します。鮮度の判定時刻は現在のbundleから取得するため、
cache構築時に有効だったConceptが期限後に復活することはありません。

sourceが応答中に変わった場合も既存CLIの最終照合で拒否します。cacheには権限はありません。
取消後の古いcache、復元されたcache、同size・同mtimeの訂正も現在のsourceとの不一致として扱います。
検索前に全行のsource digestと正規化列のchecksumを調べ、候補から欠落した行も照合対象にします。
ただしFTS postingsは構築・明示`--check`時の検証を信頼し、検索ごとに全postingsを監査しません。
JSONの`postings_trust: same_operator_cache`、検索時の`postings_audit: not_performed`がこの前提を示します。
索引は同じ運用主体の派生fileです。手動で中身を改変して継続利用せず、`--check`か再構築を行います。
checksumと列を一緒に書き換える改竄や、検査後のFTSだけの破損を検索時に完全検知する保証はありません。
検索結果本文・出典は元のConceptから返し、cacheの本文を直接出力しません。

## 今回の範囲と残る測定

これは現在のbounded bundle向けの任意cacheです。各file 1MiB、合計8MiB、256入力fileの境界を維持します。
現在のsource読込み、schema検証、bytesの再照合は省略しないため、CLI全体の待ち時間が必ず短くなるとは限りません。
cache容量、構築時間、cold/warmの起動・検索、read bytes、peak RSS、部分一致の品質を分けて測ります。
大規模な合成索引単体の値を、admissionを通ったCLI全体の性能として扱いません。

Node `kotodama`と配布候補`kotodama-core`への接続、100kの実入力品質・性能、常駐reader、
選択した本文だけの読込み、私有profileの採用、壊れたFTS内部構造からの自動回復は
[#326](https://github.com/Kotodama-Project/Kotodama-project/issues/326)の後続です。
localの検証は実provider・実Task成果・公開の証拠ではなく、`NO_GO_UNPUBLISHED`を維持します。
