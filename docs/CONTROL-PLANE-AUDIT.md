# 知識とagent担当索引の監査

`tools/audit_control_plane.py` はファイル分類、出典の鮮度、知識Concept参照、
担当索引の構造を読み取る道具です。知識の正本は `knowledge/` と既存のproducerです。
別のOKF、Goal/KGI定義、Task owner、実行registryを作りません。

この段階は #134 の道具とschemaです。実台帳とmaintenance plannerは後続で接続します。
未配置の台帳で実行した場合は `REFUSED` です。合成台帳と実際の公開知識を組み合わせた
試験を通しても、実agentの登録・配備・稼働は成立しません。

```sh
python tools/audit_control_plane.py --root . --as-of 2026-10-06 --format json
python -m unittest tests.test_control_plane -v
```

入力は `governance/knowledge-registry.json`、`governance/agent-registry.json`、
`governance/audit-policy.json` と対応schemaです。JSONは256KiB、列挙は20,000 entryに
制限し、除外directoryを先に除き、リンクを辿りません。canonical fileの読取りは
既存のbounded readerを使い、path escape、特殊file、読取中の変更を拒否します。

分類の下限98%をschemaと実行器で維持します。未分類fileを報告し、古いreview日付は
警告として残します。`PASS`はエラーのない構造を意味し、鮮度警告ゼロを意味しません。
`--fail-on warning`で警告も終了コードに反映できます。日付だけを更新して隠しません。

agent索引v2は既存IDと `canonical_role`、`knowledge_refs` を対応付けます。
旧 `kgi_links` / `key_factor_links` を受け付けず、参照先を現行bundleで照合します。
`active`、実行権限、runtime receipt、promoted状態はこの索引で宣言できません。
実行の記録は既存の[lifecycle契約](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md)、計画は
[swarm契約](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md)の担当です。

移植元は公開 #64 `e0460b3` のauditと3 schemasです。`check_okf()` と競合OKF registryを
除外し、schema検証、有限読取り、Concept参照、Markdown無害化を追加しました。
出力はread-only/candidate-onlyで `NO_GO_UNPUBLISHED` を維持します。
