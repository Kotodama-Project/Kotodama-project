# agent診断の統合と境界

[投影CLI](AGENT-STATUS-PROJECTION.md)と[公開skill](../.agents/skills/kotodama-agent-status/SKILL.md)
を同じbundleへ束縛します。`--expected-bundle-sha256`は現在のコード・skill・消費する
統合契約を照合し、違えば投影前に拒否します。本人性や起動中コードの証明ではありません。

出力は`agent-status-v2`です。固定診断コードごとの`next_steps`と、観測の
missing/stale/future/fresh件数を保持します。v1出力のconsumerは明示的に新しい形を
受け入れる必要があります。現在のv2責任索引を、実agentの登録として読み替えません。

## 入力と表示

JSONは1MiB、配列・辞書は1000項目、深さ24、キー込み50,000 node、UTF-8文字列合計
1MiBに制限します。循環・共有参照の探索、非JSON値、surrogate、重複fieldを拒否します。
観測はtrusted ownerが管理する不変snapshotを使い、ACLは呼出側が確認します。
JSONとMarkdownは既定で名前・目的・Work/runを伏せます。明示のローカル表示は公開の承認ではありません。

pathとdescriptorはdevice/inode/file type/size/mtimeで結び付け、ctimeとpermissionは
それぞれ同じAPIの読取前後で比較します。CPython 3.12のWindowsではpathとdescriptorの
ctime・modeが異なるため、異種APIの値を無条件に同一視しません。読取中の差替え、成長、
同サイズ置換、APIごとのctime変更は拒否します。UNC形pathはアクセス前に拒否します。

## 診断CI

control-planeの任意workflowは関係pathの変更時だけ動きます。共通の依存導入が成功した
場合、focused回帰が失敗しても独立した知識・control-plane・maintenanceの読取結果を
残します。失敗を`continue-on-error`で成功にせず、summaryはfailure・skipped・not_reportedを区別します。

診断jobはLinuxとWindowsで`test_agent_status*.py`と公開skill監査だけを実行します。
必須チェックの全体unittestを重ねません。Windowsのsymlink作成権限やopen-file置換制約は
該当する試験だけがskipを記録します。これは現在のsourceへのローカル証拠であり、
live observer・実Work・native GUI・provider・本番の受入ではありません。

移植元は公開#64/#65、最終sourceは`d3452ed7cfd46bb689b83372ec5305307cae4cc5`です。
古い8agentという件数や旧workflowの全体試験重複を持ち込まず、現在の責任索引・
公開skill契約と#131のworkflow方針へ合わせました。
