# Python検査の批判的レビュー

[#212](https://github.com/Kotodama-Project/Kotodama-project/issues/212)の固定点は
main `dca377bb2b790a498ed62a8734776c07540ead04` です。
公開jobの全case IDと同じ版のdiscoveryを照合し、4人のagentが全method・setup/helper・
関連する対象実装と仕様を読み、個別に目的・scope・assertの根拠・改善案を記録しました。
subTestの変異は所属methodの一部として読み、独立したmethod数へ水増ししません。

## 集計の意味

| 対象 | 件数 | 意味 |
|---|---:|---|
| 実unittest cases | 1,193 | 文書・schema・CLI・local runtimeの異なる検査 |
| ModuleSkipped | 3 | pytest専用moduleを必須Task swarm jobへ委譲する表示 |
| 公開unittest集計 | 1,196 | 上の合計。1,196件のruntime実測ではない |
| 維持 | 942 | 3委譲表示を含む個別レビューの判断 |
| 改善余地 | 202 | oracle・運用前提・fixture・実行コストに改善案がある |
| 共通化候補 | 52 | helperや文書assertの共通化候補。削除した件数ではない |

scopeはcontract 288、CLI 404、runtime 285、static 216、collection 3です。
runtimeには実際に動かしたlocalなscanner・state/storage関数も含み、
本番接続や常時稼働を意味しません。改善案の件数も失敗したテスト数ではありません。

## 今回優先した修正

- 次の操作手順をcredential gate、hash付きlock、workflow参照、suiteの順に統一する。
- 名前だけでリンクの存在を検査したことにせず、実ファイルとanchorを調べる。
- TemporaryDirectoryのcleanup前に出力不在を検査し、拒否後の書込みを見逃さない。
- aggregate budgetを個別size拒否やJSON失敗と取り違えない。guard欠落で失敗する負例を使う。
- 日本語を含む有効fixtureでUTF-8出力を検査し、ASCIIだけの成功で済ませない。
- Gitのignore規則は文字列に加えて、隔離した実Gitでroot・nested・例外の挙動を確認する。
- required gateは実workflowのrunとenvを対象にし、全216状態の拒否を保持する。
- lockはhashの総数に加えて全requirementのhashを既存parserで検査する。

## 同じ対象を軽く検査する

Task swarmのpytest collectionは無関係なmoduleをimportしない設定にし、
変更前後の100 node IDsを一致させました。ローカル参考値は4.01秒から0.24秒です。

意味論的なlifecycle/ledger変異は同じproduction `main(argv)`、実input file、
bounded reader/parser/schema/semantic/reportを直接通します。正常CLI、引数、終了コード、
深い/不正JSON、size、nonregular file、入力を出さない診断は実child processで残します。
代表例の全payload/終了コード一致とguard欠落の負例を独立に確認しています。
scannerの重複した全repository検査は、実GitのHEAD/index/working treeを分けた
実CLI fixtureへ1対1で置換しました。CIの依存導入前の全tracked tree gateは維持します。

同一Pythonのローカル参考値は、lifecycle 51件が75.07秒→15.63秒、migration 48件が
69.53秒→8.80秒、scanner 95件が47.53秒→1.19秒です。
検査内容・case集合とguardの実効性を合否に使い、時間短縮率をruntime性能や
別runnerのCI所要の保証として使いません。

## 継続して見る点

個別監査には、逐語的な文書assert、署名失敗が意味論的拒否を隠すfixture、
時刻・独立job・候補の状態軸の不足など、今回の小変更に含めない改善案もあります。
優先度・実仕様・負例を確認して狭いPRへ分けます。件数を減らすだけのskipや弱体化はしません。
実Dot、live provider、モデル推論品質、世界規模の同時利用は別の測定が必要です。
