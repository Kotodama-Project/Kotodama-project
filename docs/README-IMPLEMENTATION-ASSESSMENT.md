# README の実装状況と限定ローカル経路

2026-09-13。既存の #43 候補を現在のmainへ合わせた、限定ローカル経路の整理です。Company AGI の完全な利用体験は、まだ提供できていません。
README の目標に対応する component の実装と、利用者が通して使える状態を分けます。

| README の約束 | 既存の状態 | 今回の前進 | 残る受入 |
|---|---|---|---|
| 意図から仕事を実行して成果を返す | Task の耐久性を試す固定 fixture と、実ファイルを作る Company Pack generator が別々 | [Task に結び付けた Pack 実行](COMPANY-PACK-TASK-EXECUTION.md)。実生成、独立 validator、byte readback、中断後の再観測 | 自然文からの Task 作成・専門 Agent 起動・利用者の成果受入 |
| 会話の同じ対象を確認・訂正する | Edge projection が対象の ID/revision を返さず、review は既知 ID に依存 | [Local review Gateway](../runtime/local-review-gateway/README.md)。ID/revision、CAS、actor 分離、実 HTTP の保存・再読 | Voice sourceの取込、公式 OS の Gadget、HTTPS/Access の実環境 |
| 公式 Cloudflare OS を会社のアプリ基盤にする | source pin、Gatekeeper metadata projector、過去の local evaluation | 本書で Edge と OS 本体の到達点を分離 | Gadget/Blueprint/Gatekeeper と Kotodama executor の実接続 |
| 元の意図を保持する | source digestや意図schemaはあるが、全入力経路が制約・訂正を保持するとは未証明 | 既存Task・Work Order・capabilityの参照と実装revisionを検証。handoffとの自動結線は未実装 | source span・訂正・unknownと実Taskの接続 |
| 継続的に音声で相談できる | local/private Voice処理は存在 | このrevisionではVoice captureや実環境を変更しない | 自然発話、途切れない応答、再参加、利用目的に合う区切り、保持/削除の実測 |
| 共有Context・知識・学習を使う | lexical retrieval、grant、lifecycle、OKFの個別候補 | 既存の実処理を再利用する接続先を特定 | 一つの現行source revisionで許可→取得→仕事→feedbackを結ぶ |

## 用途に応じた配置profile

[現行の利用方針](OWNER-INTENT-COMPANY-AGI.md)では、カジュアルな単体利用と組織利用が共存します。Cloudflareや会社全体の基盤は単体利用の必須条件ではありません。組織向けには **Proxmox** や **Workers** を配置profileとして評価します。
これは配置先の要件であり、両方の本番運用が検証済みという意味ではありません。

公式 OS の `pnpm run-local` は frontend / Workshop / Gatekeepers / Gadget loader を
Wrangler/workerd 上で動かします。upstream は開発・評価用と明記し、standalone
workerd の本番配備 tooling は未提供としています。Proxmox では固定 candidate の
実 Gadget 作成・再起動・隔離restoreから検証し、常用に必要な認証、保存、監視、
network境界を別途実装します。[公式 source](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/README.md#run-locally)

既存候補に固定された starter `3d211477…` の core gitlink は `6478a144…` です。別に観測した core
main `c0b6f3e5…` と混ぜて、同じ検証済みcandidateとは呼びません。
Workersの利用可否と、モデルAPI・Workers AIの従量課金可否も分けて確認します。
Codex subscriptionの実行経路は公式 OS のprovider選択だけでは接続できません。
[starter](https://github.com/cloudflare/cloudflare-os-starter/tree/3d211477ad009e13a98d863d843e5c12a29ad02b)

## 次の未接続部分

1. 同じ source / review / Task に対して、実成果を生成・検証する一経路を通す。
2. その経路を公式 OS の Gadget と限定された executor に接続する。
3. Proxmox と Workers をそれぞれ同じ受入条件で検証する。
4. Voice、Context、学習を一つずつこの経路へ結ぶ。

local test数、schema数、agent数だけを完成率に換算しません。各受入項目について
実装、実行した検証、残る実環境・人間の確認を記録します。今回の経路も
`read-only/candidate-only` / `NO_GO_UNPUBLISHED` のlocal candidateです。
