# Runtime boundaries and recovery

この文書はDiscordテンプレートの設定・運用契約です。Task状態の正本や
公開受入の台帳を追加しません。配備・実サービス・利用者受入の境界は
[ACCEPTANCE.md](ACCEPTANCE.md)のままです。

## 解析の受付

`analyzer.admission`はCLIとResponsesの両構成に適用します。

```json
{
  "concurrency": 2,
  "perRoom": 1,
  "perActor": 1,
  "maxPending": 32,
  "maxPendingPerRoom": 16,
  "maxPendingPerActor": 8,
  "maxDailyCalls": 500,
  "maxTotalCalls": 5000
}
```

これはPipeline経由の会話解析の受付上限です。音声の秒数上限、金額上限、
SDK内部の再試行回数や他の独立したarchive処理全体の上限ではありません。
API提供者側の費用上限も別に設定してください。既存のcontext・出力・timeoutの
制限は維持します。予約した解析枠は失敗・中断でも返しません。
CLIにfallbackを設定した場合は、開始前に2枠を一括予約します。

日次はUTC日付です。全期間の予約は日付変更や再起動でリセットしません。
`maxDailyCalls: 0`は重い解析の開始を止めますが、出典記録自体を止める操作では
ありません。設定変更は再起動して適用します。稼働中の上限引下げの即時反映は
この実装の契約ではありません。

出典は解析の受付前に保存されます。満杯・予算到達・高優先度入力への枠譲渡では、
`analysis: recorded_only`と理由を返し、`analysis.deferred`イベントを残します。
保存だけの出典を「解析済み」と表示せず、未解析の依頼をTaskとして実行しません。
背景会話は後続解析の許可されたbounded contextに含まれ得ますが、全件の自動再解析を
保証しません。明示した依頼は`do`/`request`経路でも出せます。この経路も既存の
権限・出典・Task検査を通ります。

訂正は待機中の旧版を取り消します。モデル呼出し直前と結果採用前に出典の版と
閲覧可能性を再確認します。停止は待機中・実行中の解析を取り消します。

## 書込みTaskの検証

`develop`/`write_file`のローカル実行にはLinuxとbubblewrapが必要です。
read-onlyの`research`/`summarize`は、この追加前提を必要としません。
Windowsからの書込みは既存のremote owner構成を使用します。

`worker.verify`に空でない検証コマンド配列を設定してください。モデル呼出しと
worktree作成より先に、実際の隔離プロセスでpreflightを行います。失敗した場合は
実行を開始せず、隔離なしの検証へ切り替えません。

検証の作業ディレクトリは`/workspace`です。worktreeは読取専用で、scratchは
一時的な`/tmp`、HOMEもその隔離領域です。ホストのHOME、Git credential、
共有worktreeの管理ディレクトリ、任意のホストパス、ホストネットワークを
検証コマンドへ追加公開しません。検証が書込みやcacheを必要とする場合は、
その出力先をscratchへ変更します。モデルの変更を検証中に書き換えない契約です。

標準の実行環境として`/usr`、`/bin`、`/lib`、`/lib64`を読取専用で公開します。
管理者が設置した追加toolchainは`worker.verificationRuntimeRoots`に指定できます。
指定可能なのは正規化された実体のある`/opt/`配下のディレクトリで、workspaceとの
重なりやsymlinkを拒否します。追加rootに機密情報や特権socketを入れないことは
管理者の責任です。ホーム配下のtoolchainを見せるためにHOME全体をmountしては
いけません。OSの隔離制限を無効化してpreflightを通す運用も行いません。

この変更は検証子プロセスの境界です。Codex実行のsandbox、信頼されたworkspaceの
Git設定、ホスト管理、OS/kernel、CPU・メモリ・ディスクの資源制限を置き換えません。
ホスト側のGit検査では任意のdiff helper/textconvや任意のhook/fsmonitorを
無効化します。新しい本番の安全性や配備受入を、この変更だけで宣言しません。

成果ファイル・ローカル制御ファイルは、通常ファイル・単一link・サイズ上限を
検査し、非ブロッキングで開いたdescriptorと読取り前後の対象を照合します。
FIFO、directory、symlink、hardlink、過大ファイルを読めた成果として扱いません。

## 再起動と利用者への説明

`status`の`analysis`はactive/pending、`recovery`は起動時の照合件数です。
既存の`tasks`とTask IDを使い、別の依頼やSQL編集でやり直す運用を避けます。

| 状態・理由 | 意味 | 次の操作 |
|---|---|---|
| `queued` | 未着手。起動時に現行権限と出典を照合して受付を復旧 | 受付後の権限が有効なら同じTaskの`resume`で再投入可能。revisionは変えない |
| `task.recovery_blocked` | 受付済みだが現在の権限・出典・revisionで進められない | 原因を確認し、正当な権限・依頼に直して同じTaskを再開。アクセスを緩めて回避しない |
| `uncertain` / `TASK_RECONCILIATION_REQUIRED` | 以前の実行・停止が確定していない | プロセス・成果・実行記録を運用側で照合。自動再実行も「完了」への昇格もしない |
| `ANALYSIS_QUEUE_FULL` / `ANALYSIS_QUEUE_PREEMPTED` | 出典は保存、重い解析は未実施 | 負荷状況を確認。必要な明示依頼は既存の依頼経路へ |
| `ANALYSIS_DAILY_LIMIT` / `ANALYSIS_TOTAL_LIMIT` | 解析の予約枠が上限 | 利用量・費用設定を確認。再起動やDB削除で停止を回避しない |
| `WRITE_VERIFICATION_REQUIRED` | 書込みの検証が未設定 | 検証コマンドを設定する |
| `VERIFICATION_SANDBOX_UNAVAILABLE` / `COMMAND_UNAVAILABLE` | 必要な隔離・toolchainを作れない | Linux側の前提を確認。通常のホスト検証へfallbackしない |

`uncertain`の照合結果を承認・記録する専用の復旧操作は未実装です。
この制約を隠して、未確認の仕事を`cancelled`や`needs_review`にしません。
remote ownerの再起動・Task復旧はそのownerが所有します。

## 検証と統合条件

追加の回帰試験は`tests/analysis-admission.test.mjs`、
`tests/artifact-boundary.test.mjs`、`tests/verification-boundary.test.mjs`、
`tests/pipeline-hardening.test.mjs`、`tests/hardening-config.test.mjs`です。

正式環境の`pnpm test`と`pnpm check`を実行してください。
実Linux隔離試験は`KOTODAMA_REQUIRE_SANDBOX_TEST=1`で有効にします。
GitHubのLinux jobはこれを有効にし、bubblewrapをinstallします。
未対応の環境でskipしたfixture試験を、実隔離の成功と読み替えません。

Repository validationの既存の必須jobは、同じcommitの再利用Discord workflowを
`needs`で待ち、`always()`の下で依存結果が`success`であることを明示検査します。
Discord workflowの直接triggerは再利用呼出しへ統一し、同じmatrixを二重起動しません。
Node側の失敗、取消、skip、結果欠落を成功にしません。GitHubの管理設定自体を
変更したという意味ではありません。変更がmainに入るまでは候補の挙動です。

実Discord、実音声、課金、2人30分の通話、別利用者の新規導入、独立review、
本番配備は別の受入です。CLI fixtureや合成テストで代替しません。
