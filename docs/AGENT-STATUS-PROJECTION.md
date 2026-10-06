# agent状態のオフライン表示

`tools/project_agent_status.py`は責任索引とOpenMaus統合契約、任意の観測snapshotを読み、
接続・実行・停止の観測・独立検証を区別して表示します。サービスへ接続せず、変更や
実行の制御も行いません。終了コード0は投影できた意味で、健全・認可済み・配備済みの証明ではありません。

```sh
python -B tools/project_agent_status.py --as-of 2026-10-06T00:00:00Z --format markdown
python -B tools/project_agent_status.py --bundle-sha256
python -m unittest tests.test_agent_status_projection -v
```

入力の正本は `governance/agent-registry.json` と `governance/openmaus-integration.json`です。
v2責任索引はcandidate-onlyで、active・実行権限・runtime evidenceの宣言を拒否します。
過去のv1形式もオフライン比較用に読みますが、観測の真正性や認可は検証しません。
現在の索引だけから稼働を推定せず、観測がなければofflineでなくunknownを返します。

`--observations`は操作者が閲覧を許可されたローカルJSONを渡す入口です。
取得・ACL確認はこの道具の外にあります。未来・期限切れの観測でrunningと判定せず、
取消要求を停止観測に、実行終了を独立検証完了に読み替えません。
`access_evaluation: not_evaluated_do_not_serve`の出力を、そのまま公開サービスへ配信しません。

JSONとMarkdownの既定表示では名前・目的・Work/run IDを伏せます。
必要な操作者が`--include-context`で明示した場合だけ表示します。このflagは権限を与えません。
純粋な`project()` APIは呼出側へ完全なprojectionを返すので、その出力にもアクセス制御が必要です。
Markdown中の未信頼文字列はHTML・リンク・行追加として解釈させません。

1入力は1MiB、JSONは深さ24・幅1000・総node数50,000に制限します。
file/descriptorとpathの読取前後を照合し、リンク・特殊file・観測できた差替えを拒否します。
これは敵対する同権限writerからのatomic snapshotやOS sandboxではありません。

出力のinput digestは実際に解析したbytes、bundle digestは現在のコードと統合契約を表します。
本人性、実行中コードのattestation、独立検証の証拠ではありません。公開skillと診断CIは
#136後半でこのbundleへ追加します。元は公開#65 `d3452ed7cfd46bb689b83372ec5305307cae4cc5`
の投影器と試験で、旧OKFや別のTask台帳は導入しません。
