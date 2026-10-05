# Git Stewardと作業セル

Git Stewardは、一つのrepositoryに対する変更範囲・依存・実行の版を調整する
ローカル候補です。Taskの目的・完了・権限は既存ownerへ返します。
実行手順とcommandの契約は[runtime README](../runtime/git-steward/README.md)、
合成の連続運転は[業務演習](BUSINESS-REHEARSAL.md)にあります。

| 単位 | 管理主体 | 扱うもの |
|---|---|---|
| 目的・Task | 選択済みのWork owner | 目的、受入条件、訂正、依存と予算 |
| repository | Git Steward | 書込み・読取り範囲、競合key、基準commit、割当候補 |
| 作業セル | 一つのWork revisionに束縛した担当 | context digest、grant参照、branch、leaseとepoch、成果物 |
| 検証 | 作成者と異なるreviewer | 同じhead・diff・check issuerの確認 |
| 統合の観測 | 別のattester | 実際の統合revisionとreceipt。Task完了とは別 |

割当は先に固定します。同じWorkの訂正は旧revisionを失効させ、旧workerの停止確認まで
範囲を保持します。lease期限切れや停止要求だけでは予約を解放しません。
書込み同士・読取りとの重なり、共通契約の競合keyを検査し、依存先の候補提出だけでは
後続を起動しません。再送は同じ現在状態を返し、別の実行を作りません。

```text
queued → running → candidate → verified_candidate → integrated
             └→ reconciling / stopping → 停止確認 → queued / cancelled
```

`integrated`でも`task_completed`と`merge_authorized`はfalseです。principal・grant・
receiptの参照文字列を本人認証と扱わず、実executorのadmissionで確認します。
Git worktreeは作業ディレクトリを分けます。実際の隔離には、credentialを分離した
実行環境と書込み前のfenceが必要です。元のbranchを一括mergeする設計ではありません。

| 段階 | 受入条件 | 現在の範囲 |
|---|---|---|
| G0 調整コア | 排他、依存、訂正、永続化、再送、差分binding | mainのローカル実装と合成演習 |
| G1 表示接続 | 認可された読取り、同じWorkと現在版の表示 | 未接続。日常入口は[Dots](OPENAI-ALIGNMENT.md)、Cloudflare OSは[任意の設計候補](OPENMAUS-CLOUDFLARE-OS-INTEGRATION.md) |
| G2 executor接続 | live Work/grant/context照合、隔離、停止・曖昧書込み照合 | 未受入 |
| G3 統合と運用 | 実check issuer、base移動競合、復元・保持、独立review | provider未接続。ローカル演習で実Git/SQLite/processを使用 |

新しい会社台帳や常駐agent群は作りません。journal v1は保存して拒否し、自動でv2へ
読み替えません。実際の旧worker停止・外部作用・epoch・現在Workを照合してから移行します。

公開出典は #57 / #58（`297c771`）です。旧文書のCloudflare共通画面、agent-registryの
追加、旧stackの受入済みという記述は持ち込まず、現在の[製品方向](PRODUCT-DIRECTION.md)
と[R1実装](../runtime/git-steward/README.md)に合わせています。
