# 自動改善ループ（このリポジトリ）

[Company AGI direction](OWNER-INTENT-COMPANY-AGI.md) の「Unattended Improvement Loop」と「Standing GitHub delegation」を、この公開リポジトリの開発に適用する運用契約です。agent がこの文書だけを読んで一周を進め、人は判断が必要なときだけ呼ばれます。会社の Task 台帳や Current Truth は作りません。

## 一周の流れ

```text
観察 -> 一件を選ぶ -> 最新 main から branch -> 最小の変更と検証
-> 独立 review -> PR -> 必須 CI -> merge -> main を監視 -> 退行なら revert
-> 学び（CHANGELOG・Issue・地図）を更新
```

1. **観察**: main の必須チェック、agent が開いた PR の CI・レビュー・衝突、`priority/P0`〜`P2` の Issue、CodeQL と Dependabot の PR、`tools/lint_docs.py`、`STATUS.md` の `Updated:` の日付を読みます。下記の体験と通信の検査を、今回の変更で退行していないか照合します。
2. **一件を選ぶ**: 次の順で最初に当てはまるものを一件だけ選びます。
   1. main の必須チェックが赤い → 原因の PR を revert するか、最小の修正を出す。
   2. agent が開いた PR が赤い、衝突している、未対応のレビューがある → それを直す。
   3. `priority/P0`、`priority/P1` の bug（`status/needs-decision`、`status/parked` を除く）。
   4. docs lint の失敗、古くなった `STATUS.md` / `ROADMAP.md` / 地図。
   5. `priority/P2` と、観察で見つけた小さな改善。
   判断が人に残っている Issue（`status/needs-decision`、ライセンス、公開、課金、配備）は選ばず、周回の報告に並べるだけにします。
3. **変更と検証**: 最新 main から branch を作り、一件に必要な最小の変更をします。[CI と必須チェック](CI.md) のローカル確認を通し、失敗を再現してから直します。
4. **独立 review**: 変更を書いた agent とは別の reviewer（別の agent / 別の session）に diff を読ませ、根拠のある指摘を直します。指摘が残るうちは merge しません。
5. **merge**: 必須チェック（[4 本](CI.md)）がすべて緑、独立 review に未解決の指摘がなく、衝突がないときだけ squash merge します。
6. **監視と自動 revert**: merge 後に main の必須チェックを読み戻します。その merge が原因で赤くなったら、先に revert PR を出して main を緑へ戻し、原因は別の PR で直します。
7. **学び**: `CHANGELOG.md` の Unreleased、閉じた Issue、必要なら [プロジェクトの地図](PROJECT-MAP.md) と `STATUS.md` を同じ PR で更新します。

## 体験と通信を毎回照合する

[製品方向](PRODUCT-DIRECTION.md)の受入例に対し、変更する経路で次の観測を確認します。
これらは現在のfixtureで再現できる範囲であり、利用者の満足や実モデルの推論品質は別に測ります。

| 理想 | 現在の回帰検査 |
|---|---|
| 普段の相談に余分な操作を要求しない | Dotsの通常の全文一覧を保持し、読取りでTaskを作らない。簡略一覧と全文の続きは必要なagentだけが使う |
| 必要な情報を漏れなく、現在の条件で読む | 先頭10件より後の依頼、cursorの終端、全文digestとUnicode境界を確認。Task一覧は要求者とactorを照合。訂正・取消・権限失効後の古い読取りを拒否 |
| 長文と複雑な条件を分担して扱う | 短文・多言語長文・pageをまたぐ依存の3profileで原文・根拠・訂正を照合し、欠落や古い根拠なら失敗 |
| 同じ仕事へ結果を返す | 再起動、重複、reply ACK、独立reviewer、owner受入待ちを検査。ACKやworker結果だけで受入済みにしない |
| 履歴と遅い通信で処理量が無制限に増えない | SQLiteのVM命令数、SELECT回数、payload bytesとraw未終了処理の枠を確認。timeoutを完了やremote書込み取消と扱わない |

実行方法と限界は[Luna benchmark](LUNA-TASK-SWARM.md)と
[Dots plugin](../runtime/discord-template/dots-plugin/README.md)にあります。
Luna benchmarkの成功時reportは件数・bytes・検査結果・実装digestを出し、実会話やcredentialを使いません。
作業量の決定的な上限を合否に使い、機械によって変わる経過秒数は参考値にします。
実モデルで試すときは、モデル・入力digest・利用tool・最新訂正・根拠・欠測・費用を記録し、
一回の成功を常時監視、live接続、世界規模の負荷受入へ拡張しません。

## ブランチと候補を整理する

merge後のbranchは削除し、14日以上更新のないDraftは
[CONTRIBUTING](../CONTRIBUTING.md)に従って`status/parked`にし、再開条件を元のIssueへ残します。
未統合の候補を整理する場合は、現在のheadをannotated archive tagに保持し、remoteのtagと
commitを読戻してから、対象SHAを条件にbranchを削除します。open PRのhead/baseと未確認の
独立作業は保持します。squash merge後はancestor判定だけで統合済みと推測しません。
再開では履歴を復元して参照し、必要機能だけ最新mainへ再配置します。古いstack全体を
まとめてmergeしたり、元の受入証拠を新しいheadへ流用したりしません。

## 予算と停止条件

- 一周で merge する PR は一件までです。同じ Issue に三周続けて進展がなければ止め、Issue に理由と必要な判断を一度だけ書きます。
- 同じ入力（同じ main と同じ Issue）には同じ作業を繰り返しません。
- テストの skip・削除・弱体化、空 commit、PR の close と reopen で CI を通しません。
- 秘密値、login、2FA、課金、本人確認が必要になった時点で止め、人に必要な操作だけを伝えます。

## agent がしないこと

- force push、履歴の書き換え、branch protection・リポジトリ設定・secret・visibility の変更。
- 配備、provider への upload、有料機能の有効化、公開状態（`NO_GO_UNPUBLISHED`）の変更。
- 人の PR の大きな設計変更。提案をコメントし、判断は作者に残します。
- private な会話、音声、host 識別子、credential をリポジトリ・PR・コメントへ書くこと。

## 人が決めること

製品の方向、競合する設計のどちらを正本にするか（知識の正本、音声の control plane など）、ライセンスと権利、公開・配備・課金、login。agent は選択肢と推奨を示し、決定を待つ間は他の一件を進めます。

## 動かし方

定期実行する場合も手動で頼む場合も、各周回は新しい session で始め、この文書と [AGENTS.md](../AGENTS.md) を読んでから一件を進めます。周回の報告は、選んだ一件、実行した検証、merge / revert の結果、人の判断待ちの一覧です。local の PASS を live、配備、Public Beta、Human GO と呼びません。
