# Knowledge Workの出典・主張・成果物を検証する

既存Workに属する調査・判断材料を`knowledge-work.json`で束縛する候補実装です。
[知識基盤](KNOWLEDGE-BASE.md)はConceptの参照・探索、このpackageは一つの作業成果と根拠の固定を担います。
別のTask台帳、会社DB、承認サービスは作りません。

## 実行

Python 3.12とhash付き`requirements-ci.txt`の依存を使います。

```sh
python -B tools/audit_knowledge_workspaces.py --format markdown --fail-on error --require-package
python -B tools/validate_knowledge_work_package.py examples/knowledge-work/business-rehearsal
python -B -m unittest tests.test_knowledge_work_validation tests.test_knowledge_work_source_roots -v
```

auditは`examples/knowledge-work/`と`knowledge-work/`を最大64package・4096entryまで逐次探索し、
各packageをvalidatorで検証します。壊れた根拠をpackage件数の多さで成功にしません。
symlink/reparse point、特殊file、読取不能を拒否し、`--require-package`はゼロ件を拒否します。
上限に達した探索を部分的なPASSにしません。

`--workspace`はroot相対の明示workspaceを既定探索へ追加します。各directory直下のmanifestを読み、
未知・不正・重複workspaceを拒否します。64package/4096entry上限を広げる指定ではありません。

```sh
python -B tools/audit_knowledge_workspaces.py --root LOCAL_ROOT --workspace outputs/package-a --workspace outputs/package-b --source-root EVIDENCE_ROOT --ceiling restricted --require-package
python -B tools/validate_knowledge_work_package.py PACKAGE_DIRECTORY --source-root EVIDENCE_ROOT --ceiling restricted
```

原資料を複製できない場合はoperatorが`--source-root`を明示します。manifestはworkspace、sourceと
deliverableの相対pathはsource-rootから読みます。省略時は各workspaceを使い、明示rootで
見つからない資料をworkspaceや親directoryへ探し直しません。auditでは既定探索を含む全packageへ
同じsource-rootを適用します。

`--ceiling public|internal|restricted`の既定は`public`です。宣言が上限を超える場合、
source/deliverable本文を読む前に拒否し、package ID/digestやbindingsを出力しません。
感度を引き下げる宣言はそれ自体を先に拒否します。これは検査範囲の指定で、実ACLや本人認証、
read/export権限の付与ではありません。許容した範囲のreportにはpackage ID等を含むため、公開前に確認します。

## 入力と検証の境界

- workspace/source-rootは全祖先のsymlink/reparse point、UNC、親への逸脱を拒否します。
  artifactは通常fileだけを読み、絶対path、hardlink、代替streamを拒否します。
- manifest最大256 KiB、1artifact最大1 MiB、1package合計8 MiBです。
  読取前後のidentity・size・mtimeと、最後の再読時のSHA-256を照合します。
- sourceは`synthetic_fixture`か`local_snapshot`です。snapshotはtimezone付き期限が必要で、
  期限切れを拒否します。`--as-of`は評価時刻であり、過去時点のPASSを現在の受入には使いません。
- candidateには既存Work参照、根拠のあるmaterial claim、受入条件、対応する成果物が必要です。
  未解決の重大な矛盾、blocking question、受入未達、重複ID、参照不整合を拒否します。
- draftのblocking questionはwarningとして残ります。`--fail-on warning`ならauditは失敗します。
  `error`で構造PASSでも、draftをcandidateへ昇格しません。
- reviewはproducer/reviewer IDの分離とsubject digestだけを照合します。
  本人性、意味的正しさ、実際のreview実施は認証しません。

`create_knowledge_work_package.py NEW_DIRECTORY PACKAGE_ID`は既存の親directory内へ未束縛draftを
作ります。既存targetを上書きせず、失敗したdirectoryも自動削除しません。

この検査は信頼されたoperatorが選ぶlocal directoryを対象とします。同権限の敵対的processを
隔離するOS sandboxではありません。実運用のACL、single writer、取消は既存ownerで照合します。
すべてのreportで承認、reviewer本人性、意味的支持、実行、Promotion、Current Truthのclaimはfalseです。

## 元候補と後続

package/validatorは#198、監査とsource-root試験は#133のR3bです。公開#60の
`2ed4aa268e04e62ade868c6900637873eaea37b9`を元に、現在の有限reader・拒否理由・出力抑制を保持します。
compilerは未統合です。元のcompiler専用assertionと混在methodのcompiler部分は
[#137の対応表](https://github.com/Kotodama-Project/Kotodama-project/issues/137#issuecomment-5849351363)
に保存しています。両試験moduleはcompilerなしで実行し、R3bで元の監査試験を復元します。

後続#137は選択済みの一つのgenerated-knowledge-context形式へ束縛します。
現packageのsource kindにはConcept参照がなく、その接続、context予算、executorへ渡す最終payloadの
検証も後続です。監査PASSから実Task完了やlive接続は主張しません。
