# 要件漏れと追加条件

[68項目へ](README.md)

68項目のIDは維持した。独立監査の17提言は重複を裁定し、16件を既存項目の細目、1件を横断するrelease義務として整理した。加えて最新指示・実運用・Issueの10補足を紐付ける。27は新機能数でも独立要件の総数でもない。記載は新規実装の開始指示ではない。

READMEのCompany OSという中心概念に対応する8領域は68項目に存在する。一方、元の短い受入文だけでは、下記の拒否系・運用条件・採用条件を判定できなかった。「要件漏れが絶対にない」とは宣言しない。

## ADD-R20-ENVELOPE

分類: ADD_SUBCRITERION。対応: R20。

64 events/900 seconds/10 ticks/STOP/digest-replay-restore-projection/deny-by-default MCPを一receiptに固定

出典: README.md:L65-70。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R38-OWNER-INVARIANTS

分類: ADD_SUBCRITERION。対応: R38。

max depth 2、N/C/W/V、work_key、same-writer、budget/TTL/kill/rollback、rerun抑止、auto-revert、bounded escalation

出典: README.md:L77-83。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R32-R36-AGENT-SEPARATION

分類: ADD_SUBCRITERION。対応: R32, R36。

Routing/Metadata agentsはexecute/truth promoteせず、reuse filter順を検証

出典: README.md:L84-89。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R39-DISPOSABLE-GRANT

分類: ADD_SUBCRITERION。対応: R39。

exact base/image、owner、data/network/tool grant、budget/TTL/kill/export/cleanup

出典: README.md:L93-95。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R40-R41-MODEL-POLICY

分類: ADD_SUBCRITERION。対応: R40, R41。

Luna-first、rationale、actual provenance、metered API除外、no hidden fallback

出典: README.md:L96-101,124-132。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R55-ZFS-PRODUCTION-BOUNDARY

分類: ADD_SUBCRITERION。対応: R55。

encrypted package/ZFS 8/8 syntheticとproduction key/retention/deletionを分離

出典: README.md:L102-107。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R39-R42-GITHUB-AUTONOMY

分類: ADD_SUBCRITERION。対応: R39, R42。

branch/commit/PR/mergeはindependent review/tests/revert pathが条件

出典: README.md:L108-111。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R09-R11-R57-15MIN-BOUNDARY

分類: ADD_SUBCRITERION。対応: R09, R10, R11, R57。

900秒確定、private post、rejoin、retention/delete receiptを別acceptanceに分解

出典: README.md:L287-300。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R24-R26-QUICKSTART-SAFETY

分類: ADD_SUBCRITERION。対応: R24, R26。

public example不変、existing bundle target拒否、同一candidate pathの後続検査

出典: README.md:L507-559,864-931。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R51-R59-DEPENDENCY-BOUNDARY

分類: ADD_SUBCRITERION。対応: R51, R59。

stdlib CLI、test-only dependency、local PASSのlive拡張禁止

出典: README.md:L987-1004。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R60-R62-ATTESTATION-MATRIX

分類: ADD_SUBCRITERION。対応: R60, R62。

toolごとの証明範囲/trust boundaryをreason-specific acceptanceへ束縛

出典: README.md:L964-978。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R24-R28-R63-EXAMPLE-COMPANY

分類: ADD_SUBCRITERION。対応: R24, R28, R63。

9段階のExample Company導線とplaceholder≠設立/権限/Promotionを受入化

出典: README.md:L1006-1018。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R67-SURFACE-MAP

分類: ADD_SUBCRITERION。対応: R67。

eight-surface mapのリンク、ideal/current分離、surface boundary

出典: README.md:L134-159。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## ADD-R21-R68-PROJECTION-BOUNDARY

分類: ADD_SUBCRITERION。対応: R21, R68。

Owner-confirmed directionはprojectionであり、rightsholder/adoption/GOではない

出典: README.md:L32-44。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## GAP-LICENSE-01

分類: CROSS_CUTTING_RELEASE_OBLIGATION。対応: R62, R68。

Apache-2.0、NOTICE、contributor/rightsholder、source-specific compatibilityの独立受入

出典: README.md:L1044,1161-1163。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## GAP-DOC-MAP-01

分類: ADD_SUBCRITERION。対応: R67。

Project Map/implementation/status/runtime/evidence linksのfresh clone存在・anchor・revision検査

出典: README.md:L12-18,1061-1119。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## GAP-PUBLIC-BOUNDARY-01

分類: ADD_SUBCRITERION。対応: R59, R61, R62, R63。

public invite/Voice/live deployment/Context/Agent/Business/protected reconciliation各NO-GOを個別Rへ反映

出典: README.md:L1140-1152。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D01 最新のmodel選択とprovenance

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R40, R41。

今回の一般chatは既存local Qwenを明示選択。旧READMEのgeneral-purpose local LLM deferredを今回の禁止へ流用しない。親modelの全体固定、metered API、cloud fallback、他Taskのモデル変更は認可していない。

出典: 直接ユーザー訂正 2026-09-06。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D02 保存期間と使えるファイル

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R13, R57。

今回の運用方針は原音30日、transcript/要約/出典は期限なし。JSON/Markdown/VTTと添付本体の取得を分け、native exportのtimeoutとCDN403を未検証として残す。

出典: 直接ユーザー訂正 2026-09-06。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D03 文書破損・既存instance・運用再開

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R45, R47, R50, R52。

default Blueprintのblocks検査を修正したが、既存Gadgetには旧codeが残る。本文を保全したinstance更新と不正入力拒否、PC停止・常設起動・backup/upgrade/recoveryを別受入にする。

出典: 実OS評価 E09/E10。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D04 実identityと派生先ACL

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R30, R33, R58。

情報分類、opaque主体、担当、read/review、purpose、取消を元ownerへ結び、引用・export・index・embeddingへの継承も検査する。ID化/要約だけで公開分類へ下げない。

出典: 直接ユーザー訂正と情報アクセス候補 E03。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D05 repository管理面

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R59, R62, R63。

required check名、最新push独立承認、bypass、会話解決、force push/deletion、CodeQL、private reporting、secret/push protection/history scanを実管理面で読み戻す。

出典: GitHub #19。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D06 packageと移植の完了定義

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R62, R68。

rights/NOTICE、公開/非公開namespace、二release互換、wheel/sdist allowlist、SBOM/provenance/signature、immutable pin、canary/rollback、zero residual consumersが必要。

出典: GitHub #24 #25 #26 #28 #30 #31 #32。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D07 provider/supply/supportの細目

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R43, R48, R49, R50。

body/residency/cache/log、trusted deploy runnerとdurable receipt、registry/source workflow trust、Windows/Linux契約、lint/chunk budget、独立security/support判断。古い別coreのPASSを新coreへ流用しない。

出典: GitHub #2–#16。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D08 関連repositoryのowner/lifecycle

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R67, R68。

7つのlegacy repositoryのowner・依存・support・successor分類は別Issue。今回のクロージングから一括archive/deleteや全社Project閉鎖を推定しない。

出典: GitHub #23。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D09 利用品質の判定値

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R01, R04, R08, R14, R29, R32, R64, R66。

音声の遅延/途切れ、ASR/話者/引用の誤り、検索漏れ、質問の有用性、成果採否を実fixtureと利用者で測る。閾値・対象母集団・評価期間は未決であり仮の数値を合意済みにしない。

出典: READMEの利用体験から導く未確定の測定条件。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。

## D10 同じTaskの入口・閉鎖と手動再開

分類: SUPPLEMENT_OR_OPERATIONAL_OBLIGATION。対応: R03, R05, R37, R38, R54, R67。

OS、Discord Voice・text、Telegram、Codex、Claudeは同じstable Task ID・revision・ownerを解決し、別のTask正本を作らない。再送・切断・再接続・訂正・duplicate writerを同じ記録で扱う。この作業は未受入を保持してクローズし、heartbeat等で自動再開せず、次の直接指示後に現在revision/ownerを解決する。サービス削除・データ削除・他owner閉鎖を含まない。 個人の制作・開発Taskを管理することと、Company本番業務へ組み込むことは別です。個人Taskの記録・owner対応・sourceを、本番へ自動採用・同期・接続・公開しません。共通の管理契約を再利用しても業務データの移行は別scopeの判断です。

出典: 直接ユーザー訂正 2026-09-06。READMEの行はレビュー固定点 `f168a2ebd52d0eb62fbd491c403effdefcb9aa97` に対応。
