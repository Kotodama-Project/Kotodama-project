# プロジェクトの地図

Kotodama は、会話から意図・仕事・成果・学習へつなぐ Company OS を目指します。
この地図は、README の目標から既存の実装・文書・レビューへ進むための入口です。
機能の採用、Task 状態、実環境の稼働を決める台帳ではありません。

## 何を確認するか

| 知りたいこと | 根拠 | 読み方 |
|---|---|---|
| なぜ作るか、どんな体験を目指すか | [README](../README.md)、[Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) | 方向と実装済みの範囲を分ける |
| この checkout で使えるもの | exact commit のファイル、[STATUS](../STATUS.md) | 別 branch の機能を含めない |
| 次に統合する候補 | PR の head / base / diff / review / checks | 本文内の古い SHA と現在の API 値を照合する |
| 公開までに必要なこと | [ROADMAP](../ROADMAP.md) | テスト成功だけで gate を閉じない |
| 既存能力の移植 | [migration Epic #24](https://github.com/Kotodama-Project/Kotodama-project/issues/24) | private source と consumer を保全し、能力単位で移す |
| 実際の配備 | 非公開の operator runbook と対象環境の検証記録 | repository の状態から稼働を推測しない |

公開製品の repository は `Kotodama-Project/Kotodama-project` です。
既存の private donor/control-plane と operator workspace には別の source と
運用記録があります。公開向けには必要な契約と出典を選別し、接続情報や private
source body をこの地図へ集めません。

## README の領域から進む

| 領域 | この branch の入口 | 次に証明すること |
|---|---|---|
| Office / Voice | [README の Voice](../README.md#voice--最初に価値を体感する入口) | consent、話者、継続、応答、保持を実際の同じ経路で結ぶ |
| Intent / GrillU | [Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) | 会話から重要な曖昧さを閉じ、一つの仕事に接続する |
| Governance / Evidence | [Session / Conversation ledger](SESSION-CONVERSATION-LEDGER.md)、[Review Workflow](REVIEW-WORKFLOW.md) | 訂正、根拠、権限、検証、採用の連続性を保つ |
| Company Pack | [5-minute tour](FIVE-MINUTE-TOUR.md)、[Starter Walkthrough](STARTER-WALKTHROUGH.md) | 公開手順を手元で再現する |
| Context | [README の Context](../README.md#context-platform--会社の共有記憶) | 許可された情報集合から根拠付きで取得する |
| 情報アクセス | [情報の分類と閲覧者](INFORMATION-ACCESS.md) | 情報IDと主体IDでread/reviewを検査し、取消・失効を反映する |
| Workforce | [Company AGI direction](OWNER-INTENT-COMPANY-AGI.md)、下記 #34〜#36 | 一つの実行を owner、Task、effect、receipt に結ぶ |
| Runtime | [Runtime overview](../runtime/README.md)、[Installation Lifecycle](INSTALLATION-LIFECYCLE.md) | install、restart、rollback、restore を実環境で検証する |
| Business / Learning | [README の Business Loop](../README.md#ai-business-loop) | 一つの成果の有用性と feedback を確認する |

## 公開 PR の関係

以下は **2026-09-05 の読取時点**の整理です。次に作業するときはリンク先を再取得してください。

公開 `main` は `be71f424689648b3ab1b1db15adbaddea374586b`。
基盤 [#18](https://github.com/Kotodama-Project/Kotodama-project/pull/18) は
`70cb13df01fb7d6241cb827d26e2ad09ff0e5d05` で、まだ `main` に統合されていません。
この地図を含む変更も、その基盤に対する候補です。

| PR | 役割 | 対象 branch / 関係 |
|---|---|---|
| [#18](https://github.com/Kotodama-Project/Kotodama-project/pull/18) | governance、validation、公開基盤 | `main` に対する未統合候補 |
| [#40](https://github.com/Kotodama-Project/Kotodama-project/pull/40)、[#41](https://github.com/Kotodama-Project/Kotodama-project/pull/41) | Cloudflare、Company AGI / ledger | #18 の branch に統合済み。`main` には未到達 |
| [#17](https://github.com/Kotodama-Project/Kotodama-project/pull/17) | bounded skills | #18 に積まれた候補 |
| [#21](https://github.com/Kotodama-Project/Kotodama-project/pull/21) | status / roadmap の整理 | #18 に積まれた候補 |
| [#27](https://github.com/Kotodama-Project/Kotodama-project/pull/27)、[#29](https://github.com/Kotodama-Project/Kotodama-project/pull/29)、[#33](https://github.com/Kotodama-Project/Kotodama-project/pull/33) | hierarchy、architecture、schemas の移植 | #18 に積まれた候補。出典と採用条件を持つ |
| [#34](https://github.com/Kotodama-Project/Kotodama-project/pull/34) → [#35](https://github.com/Kotodama-Project/Kotodama-project/pull/35) → [#36](https://github.com/Kotodama-Project/Kotodama-project/pull/36) | swarm → migration ledger → agent lifecycle | この順番の stack。契約が存在することは実行の証明ではない |
| [#37](https://github.com/Kotodama-Project/Kotodama-project/pull/37) | Public Beta gate の識別子 | #18 に積まれた候補。gate は未証明のまま |

#18 の checks は読取時点で成功していましたが、独立した最新push承認と未解決レビューが残っています。
[出典・ライセンス判断 #25](https://github.com/Kotodama-Project/Kotodama-project/issues/25) も別の受入条件です。
現在のレビュー指摘を確認せず、古い本文の「全件解決」や `mergeable` だけから統合を判断しません。

## 作業を一つ進める

1. README のどの利用体験を前進させるか、一文で決める。
2. 上の入口から exact source と既存の Task / Issue / PR を選ぶ。
3. checkout、owner、対象ファイル、受入、停止、rollback を固定する。
4. 小さな変更を実装し、その利用経路と拒否経路を検証する。
5. 結果を対象の記録へ戻し、PR の本文を現在の head と検証結果に揃える。

Task contract を持つ checkout では、そこの `AGENTS.md` と Task resolver / records /
events / restart checkpoint を読みます。この branch に無い contract をあるものとして扱わず、
session の要約から別の Task 台帳を作りません。

運用記録を追加しただけで runtime が配備されたことにはしません。
`read-only/candidate-only`、`NO_GO_UNPUBLISHED` と Final Human GO の境界を維持します。
