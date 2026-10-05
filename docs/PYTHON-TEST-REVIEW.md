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

## 初回レビューで優先した修正

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

## 5項目の後続修正（#219）

[#219](https://github.com/Kotodama-Project/Kotodama-project/issues/219)では、
元の改善候補から次の5点を選び、現行の入力・処理・判定を補強しました。

- 保存済みCompose evidenceの3入力を通常ファイルに限定し、読取り量と読取り中の変化を検査する。
- lifecycleの不正なprofile IDはreportへ返さず、有効な公開IDは他の条件で拒否された場合も保持する。
- checkpointの意味論変異はself-digestを計算し直して変異後の文書に署名し、狙った拒否理由を確認する。署名・digest自体の拒否も別に維持する。
- NONE decisionは受理される通常eventから始め、4つのreferenceをそれぞれ独立に変えて確認する。
- dependency失敗後も、無関係なpending jobをclaimして完了・owner受入へ進められることを確認する。

署名失敗や別referenceの拒否だけで意味論の検査が通ったことにしません。
代表するguardを外した負例も使い、実fileとproduction entrypointを通す検査と
実CLIの境界検査を保持します。profile IDの修正はそのreport fieldの範囲であり、
任意のunknown field名などを含む全診断の非開示を証明するものではありません。
上の942・202・52は元の固定点での判断です。#219は5項目の後続修正であり、
全202件の完了は下の#221と個別対応表で区別します。

## 全202件の対応（#221）

[#221](https://github.com/Kotodama-Project/Kotodama-project/issues/221)では、
固定点の改善候補202件すべてについて、元の目的・指摘・改善案を現在の実装に照合しました。
154件を追加実装し、48件は先行PRの実装と具体的な検証が既に成立していると
独立レビューで確認しました。保留・未対応は0件です。

| 領域 | 対応候補 | 追加実装 | 既存実装を確認 |
|---|---:|---:|---:|
| 署名・schema・SQLite lease・child cleanup | 21 | 17 | 4 |
| 移行台帳・Session/conversation ledger | 36 | 7 | 29 |
| Company契約・CLI・業務文書 | 36 | 34 | 2 |
| Cloudflare preview・Voice候補 | 29 | 29 | 0 |
| Repository運用・文書・secret scanner | 50 | 45 | 5 |
| 候補IO・agent swarm・通信計測 | 30 | 22 | 8 |
| 合計 | 202 | 154 | 48 |

[個別対応表](PYTHON-TEST-IMPROVEMENTS.json)に、全case ID、元の指摘と改善案、
実装、検証、guard欠落などの負の対照、独立レビュー、残る測定境界を保存します。
対象sourceのrevision・method位置・SHA-256を束縛し、共通する検証内容はcatalogから
参照します。これは有限の監査記録であり、Task状態や稼働環境の正本ではありません。
元のTSVのSHA-256も固定し、942件の維持判断と52件の共通化候補を再分類しません。

202件の元のcase IDはすべて保持しています。元の公開集計1,196 entriesには、
この202件とは別の#213の共通化でscannerの1methodを目的の明確な名前へ変更した
履歴があります。旧`test_current_tracked_tree_passes`は
`test_cli_scans_owned_git_snapshots_and_redacts_values`へ置き換えられています。
CIの依存導入前の全tracked tree gateと、実GitのHEAD/index/working treeを通すCLIを
保持しており、全1,196 IDが逐語的に同じとは説明しません。

### 補強した実効性と軽量化

- 有効なschema入力から一つの状態・reference・署名済み内容を変え、目的の理由コードを確認する。
- childの不正UTF-8出力やclose例外でも、起動済みの全childを回収することを検査する。
- リンク先・anchor・実コマンド・stepの順序を検査し、リンクされていない見出しの表現変更を許す。
- CLI境界を実childで残し、同じproduction entrypointへ通す意味論の変異とimmutable fixtureを再利用する。
- Session ledgerのshapeを一回の検証内で再利用し、不正なenum/roleのJSON型を例外終了から構造化した拒否へ変える。
- 候補IOの上限・通常file・aggregate budget・cleanupを、入力内容の別の失敗で隠さず検査する。
- SQLiteのSELECTはprojection/aliasも計測し、履歴読取り上限とN+1の負の対照を確認する。
- peer通信の実receiptに必要な`payload_state`を閉じたschemaへ追加し、未知field・未知stateを拒否する。

各領域を実装者とは別のagentが読み、レビュー指摘を処理しました。
統合したローカルPython検査は1,306件、skip 0件で成功しました。
必須CIではPythonの3委譲表示をTask swarm SDKのLinux/Windows試験と照合します。
所要時間は測定した環境の参考値として扱い、別runnerの保証に使いません。

## 継続して測定する点

短文・長文・複雑な依存の通信benchmarkは、合成fixtureで入力と処理結果を照合し、
実モデルを呼ばないことも確認します。モデル推論品質、実Dot、live provider、
世界規模の同時利用・長時間稼働の受入には、それぞれ実環境での測定が必要です。
この監査の完了はPublic Beta、配備、Final Human GOを意味しません。
