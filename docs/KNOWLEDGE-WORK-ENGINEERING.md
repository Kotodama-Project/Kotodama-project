# Knowledge Workの出典・主張・成果物を検証する

既存Workに属する調査・判断材料を`knowledge-work.json`で束縛する候補実装。別のTask台帳、会社DB、承認サービスを作らない。旧control-plane PR本文には記載があったが、このstackには検証処理がなかったため、ここで実装と合成例を追加した。旧実装を回収したという意味ではない。

## 実行

```sh
python tools/audit_knowledge_workspaces.py --format markdown --fail-on error --require-package
python tools/validate_knowledge_work_package.py examples/knowledge-work/business-rehearsal
python tools/compile_knowledge_context.py examples/knowledge-work/business-rehearsal --ceiling public --max-claims 8
python -m unittest discover -s tests -p test_knowledge_work_validation.py -v
```

auditは`examples/knowledge-work/`と`knowledge-work/`内を、最大64package・4096entryで探索する。symlink/reparse pointを拒否し、`--require-package`でゼロ件を拒否する。見つからない検証をskipしない。

`python tools/create_knowledge_work_package.py NEW_DIRECTORY PACKAGE_ID`は、既存の親directory内に新しいdraftを作る。既存targetは上書きしない。作成時はWork未束縛・Promotion blockedで、contextへは使えない。失敗したdirectoryも自動削除しない。

## 入力と構造条件

`schemas/knowledge-work-package.schema.json`は、目的、既存Work参照、producer、package全体の感度、source、observation/inference/assumptionの主張、仮定、未解決質問、矛盾、受入条件、成果物、review、Promotionを分ける。

`work_ref`は既存ownerへの参照で、文字列だけで実行権限やTask所属を得ない。`source_refs`は根拠の所在であり、文章が主張を本当に支持するかは独立した意味評価が必要。

candidateにはWork参照・主張・受入条件・対応する成果物が必要。重大な未解決矛盾、blocking question、受入未達、根拠のないmaterial観測/推論を拒否する。assumptionは別記録で追跡し、受入と成果物の参照は双方向に照合する。

## 実bytesと鮮度

- workspace内の通常fileのみ。絶対path、親への逸脱、symlink/reparse point、hardlinkを拒否する。
- 1file最大1 MiB、manifest最大256 KiB、合計8 MiB。読取前後のfile identity・size・mtime、最後の再読とSHA-256を照合する。
- `local_snapshot`はtimezone付き期限が必要。期限切れsourceのclaimはcontextへ進めない。claim独自の鮮度や内容の真実性を証明するものではない。
- `synthetic_fixture`は合成だと明示された不変例で、期限なしを許す。実情報をfixtureと名付けるだけで鮮度を証明できない。source種別・分類の正しさと本人性は認証しない。
- `--as-of`はその評価時刻の結果を作る。過去時刻でPASSしても現在の準備完了として使わない。

信頼されたoperatorが選ぶworkspaceが前提。同権限の敵対的processを隔離するOS sandboxではない。実運用では現行ACL、保存先、single writer、取消を既存のアクセス窓口で照合する。

## Bounded Context

compilerは検証エラー、draft、感度上限超過を拒否する。sourceよりclaim/packageの感度を下げる宣言も拒否する。宣言の整合性を検査しており、本物のACL認証ではない。

material claimに加え、保持するassumption/contradictionの参照先も必須集合にする。上限に入らなければ拒否し、参照先なしの`READY_CANDIDATE`を返さない。非必須claimは決定的な順序で選び、除外IDを残す。bytes上限でも無言で切り詰めない。

source本文とlocal pathは含めず、claim本文、source metadata/digest、仮定、質問、矛盾を保持する。拒否時は本文・package/work metadataを返さない。context digestは`context_sha256=null`としたJSONをUTF-8、key順、既定separatorでencodeしたbytesのSHA-256。

## Reviewと承認境界

`review.performed`ではproducer/reviewerのID分離と、reviewを除いたsubjectのdigest一致だけを検査する。本人性、意味的正しさ、評価の実施を認証しない。そのため`approved`/`verified_candidate`は受け付けず、Promotion blockedのcandidateまでに限定する。

出力schemaは`knowledge-work-validation-report.schema.json`と`knowledge-context-bundle.schema.json`。承認、reviewer本人性、entailment、実行、Promotion、Current Truthのclaimはすべてfalse。合成例も`SEMANTIC_REVIEW_NOT_RUN`を隠さない。protected review receiptや本物の決定への接続は別の受入。

## 検証と次の接続

source/成果物変更、path、symlink/hardlink、根拠欠落、重複ID、期限、矛盾、受入対応、自己review、subject変更、感度、context予算、参照の欠落、読取中drift、既存target保全、ゼロpackageを試験する。

独立点検で「非material claimを省いてassumption/contradictionだけ残す」問題を発見し、実fixtureで再現して必須集合へ修正した。deterministicな成功は自然言語の理解や本物の仕事の完了ではない。

次は既存のknowledge context/Work ownerから、executorへ送る最終payloadまでを束縛する。ナレッジbundleは参照・探索、このpackageは一つの作業成果と根拠の固定であり、新しい会社SSOTではない。
