# Agent診断の統合・入力境界・CI改善

基本の入力仕様は [AGENT-STATUS-PROJECTION.md](AGENT-STATUS-PROJECTION.md) を参照してください。

## 統合と v2 の境界（Issue #63）

本候補は #60 `2ed4aa268e04e62ade868c6900637873eaea37b9` と #62
`d8c1b0b315b0d0c818ac41b17d0fcf74b0146119` の合流です。#58 にある期限fixture、
深さ64の共通JSON、Knowledge Work実装、Git Stewardの訂正・復旧を再実装しません。
既存の8 Agent登録を使用し、別の台帳やschedulerは追加しません。

出力を `agent-status-v2` に更新しました。v1の厳密なconsumerは明示的に移行して
ください。Agent行には固定診断コードに対応する `next_steps: [{code, action}]` が
加わり、summaryには `observation_freshness` の missing/stale/future/fresh件数が
加わります。表示のための診断で、healthy判定・権限・再起動・再送許可ではありません。
Markdownには対処手順を表示しますが、非公開のpurposeや入力本文は展開しません。

JSON入力は1 MiB、各配列/辞書1000項目、値の深さ24に加え、辞書キーを含む
総50000ノードと合計UTF-8文字列1 MiBを上限にします。直接pure関数を呼ぶ場合も
適用し、循環/共有参照による探索増大を止めます。不正Unicode surrogate、JSONでない
オブジェクト、数値変換エラー、重複required view fieldsも構造化した拒否です。

ファイルはlink/reparse pointを拒否し、開く前・descriptor・読後のidentity/size/
mtime/ctimeと実読込サイズを照合します。Windowsもbinary descriptorで読みます。
これは観測可能な差替え/途中変更の検出です。悪意ある同時書込みに対するatomic
snapshotや認可の証明ではなく、入力はtrusted ownerが管理する不変snapshotにします。

Control Plane Auditは回帰失敗後も、依存導入が成功していれば独立した読み取り監査を
実行します。各stepの失敗はjob失敗のままで、`continue-on-error` は使いません。
結果一覧には skipped と failure を分けて示します。診断のLinux/Windows検証を追加し、
Windowsがopen fileのunlinkを禁止する試験やsymlink権限不足だけを明示的にskipします。

native GUI、認可済みobserver、実Work接続、本番deployの受入は別です。#45–#48/
#59/#61をこの候補へ無差別に取り込んだものではありません。切戻しは本候補のscoped
revertで、旧PR、既存Knowledge Work、Git journalやprivate evidenceを削除しません。
