# Git Stewardの業務演習

架空のチームの仕事を、訂正・同時作業・担当交代・再起動を通して確認します。
実Git、SQLite、Node子プロセスを自分で作った一時領域内で動かします。
Work・grant・context・check issuerは合成入力で、実顧客・provider・会話は使いません。

```sh
python -B -m unittest tests.test_git_steward_runtime -v
node runtime/git-steward/business-rehearsal.mjs
```

Node 24とGitを使用します。Python launcherはcoordinatorとbusiness-simulationの
両方を実行し、Node/Git不在・失敗・skip・cancel・0件実行を成功にしません。
既存のpath限定Git Steward workflowもLinux/Windowsで両方を実行します。
重複する全体監査workflowは追加しません。

| 検査する条件 | 変化させる入力 | 期待する結果 |
|---|---|---|
| 訂正 | queued/running/candidate/verified、再送0/1/3回 | 旧成果と旧revisionの再割当を拒否 |
| 調整 | 2/4/8担当、同一file・read/write・競合key・path別名 | 競合だけを直列化し、独立範囲は進む |
| 到着順 | 訂正・旧submit・停止確認・新claimの24順列 | 停止確認前の新版実行を拒否 |
| 時刻・再送 | 期限直前/一致/直後、大幅経過 | 時刻巻戻しで期限を復活させない |
| 根拠 | failure/skipped/missing/wrong-head/wrong-issuer | 誤った検証とbase移動を拒否 |
| 復旧・上限 | 送達不明、旧epoch、同時数上限 | 未照合の再実行を拒否し記録を捨てない |
| 権限 | 購入・返金・顧客送信・配備・merge command | Git担当の外の命令を実行しない |
| 連続運転 | 旧processの遅延結果と協調停止の2種類 | 訂正した同じ仕事をSQLiteから復元して別processへ渡す |

連続運転では「移動後に音声会話を再開できる」という合成目的を、
「スマホ単体・BLE変更対象外」へ訂正します。実際に動いている旧processの結果を拒否し、
exitを観測してから新版を割り当てます。SQLiteを開き直して目的・制約・digestを照合し、
別processで架空関数を修正、さらに別processで「接続だけ成功して音声なし」を検査します。
一時repository内でのみ統合し、翌日の再読でも版を保持することを確認します。

reportは69シナリオと10分類を示します。Nodeのトップレベル試験数とは別です。
同じ演習をCLIとtestの両方で実行しても独立ケースとして加算しません。
`status=pass`は列挙された合成条件の一致だけで、`coverage`と`claims`を併読します。
実モデルの長文理解、実組織のACL、実機音声、GitHub待ち時間・費用・顧客満足は未測定です。
この時点でも`task_completed=false`です。

元の公開実装は #58 head `297c771`。演習と13回帰試験を現在のR1へ再配置し、
強化済みcoordinator/observer/storeは維持しています。旧stackのCompany Pack fixture修正、
JSON parser、分類registry、Knowledge Workは取り込みません。これらはそれぞれの
main実装または #133・#134・#137で扱います。

実運用への接続は[Git StewardのG1〜G3](GIT-STEWARD-AND-WORK-CELLS.md)に従います。
現在Workとgrantの確認、最終入力digest、隔離と停止確認、GitHubの現在head/base/issuer、
外部作用の照合をそれぞれ受け入れます。journalを消して再実行したり、
ローカルGitの統合だけで元の利用者の目的が完了したと扱ったりしません。
