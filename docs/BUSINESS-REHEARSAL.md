# 2人とAIで開発・日常業務を進める検証

この変更は、会話で決めた仕事が、訂正・同時作業・担当交代を経ても元の目的から外れないためのローカル演習です。対象は架空のウェアラブル製品チームです。実在する会社、参加者、顧客、会話、認証情報は使いません。

実際のGit、SQLite、別Nodeプロセスを動かします。Work・grant・context・check issuerは合成入力です。自然言語からの意図抽出、実際の組織への参加、常駐AI、GitHub送達、実機音声、配布、本番稼働の成功には広げません。

## 最初に実行する

Node 24、Git、Python 3.12と既存の`requirements-test.txt`を使います。既存のテスト起動口へ追加しています。

```sh
python -m pip install -r requirements-test.txt
python -B -m unittest discover -s tests -p test_git_steward_runtime.py -v
node runtime/git-steward/business-rehearsal.mjs > business-rehearsal.json
python -B tools/smoke_company_pack_review_chain.py > company-review-chain.json
```

2番目は元のGit Steward試験と追加回帰・演習を実行します。3番目は同じ演習を再実行し、各要求・拒否・版・状態をJSONへ出します。重複した実行を独立ケース数として加算しません。4番目は既存のCompany Pack作成からreview・decision handoffまでの13段階を別プロセスで確認します。このchainはGit Stewardに接続された会社運営のE2Eではありません。

`status=pass`は列挙した合成ケースの期待動作だけを表します。`coverage`と`claims`を必ず一緒に読みます。未実装の機能を「成功ケースから除いたので会社は動く」と扱わないでください。演習が書くのは自分が作った一時領域だけで、外部通信・push・配布はありません。JSON出力先は利用者が指定します。

## 仮説と反証条件

| 仮説 | 入力を変える軸 | 失敗とする結果 | 実際に使う処理 |
|---|---|---|---|
| H1 訂正後に古い仕事を採用しない | queued/running/candidate/verified、再送0/1/3回、連続訂正 | 旧版submit、旧版再割当、新版が停止確認前に同Workを実行 | 既存GitStewardのadd/claim/submit/stopped、追加の版失効 |
| H2 人やAIが増えても担当範囲を壊さない | 2/4/8参加者、独立・同一file・read/write・意味上の競合・大小文字・file/directory | 重なる担当が同時実行、または無関係なprefixまで排他 | 実coordinator。別途元suiteの実SQLite同時writer試験 |
| H3 到着順が変わっても古い結果を採用しない | 訂正/旧submit/停止確認/新版claimの24順列 | 訂正後の旧結果が通る、停止確認前に新版実行 | 実coordinator。未知cellやまだ必要のない停止確認の拒否も確認 |
| H4 再送や拒否後の時刻巻戻しで権限を復活させない | lease直前/一致/直後/大幅経過、再送・拒否、旧journal | 一度過ぎた期限を過去時刻で復活、古い保存形式を暗黙採用 | v2 journalと時刻high-water、SQLite永続化、回帰試験 |
| H5 CI表示や旧headを成果受入に流用しない | failure/skipped/missing/wrong-head/wrong-issuer、base移動 | 検証済み候補・統合可能な観測として通る | verify/assess、実Git差分。実GitHubチェック認証は未接続 |
| H6 再開と送達不明で二重作業を作らない | unknown/再claim/停止確認/旧epoch、同時上限 | 未照合で再起動、古いepochの結果受理、上限で記録を捨てる | 実coordinatorと元suiteのSQLite再起動/競合 |
| H7 一件を訂正から引継ぎ・実行・reviewまで通せる | 動作中旧processの遅延結果／協調停止、SQLite close/reopen、別process | 旧結果採用、目的・BLE除外の消失、割当branchの不一致 | 実Git/worktree、実SQLite、実child process、合成contextのdigest照合 |
| H8 開発委任を会社全体の権限と取り違えない | 購入・返金・顧客送信・配備・merge要求 | Git担当がその命令を実行、または完了を主張 | 未定義command拒否とtask_completed=false。実組織のACL試験ではない |

最初の6回帰ケースは基準コードで失敗しました。追加の独立レビューから、拒否時刻・旧journal・統合済み依存の訂正の3ケースも失敗を再現して修正しています。最終点検では、訂正版自身が失効させる推移的consumerへ依存するケースも拒否するよう修正しました。元37ケースは残し、意味を変えた「拒否時の保存」試験だけを、業務変更のrollbackと時刻観測の保存へ更新しています。

基準コード`1b5d79c`へ同じ69シナリオを適用した比較では27成功・42失敗となり、修正候補では69成功でした。これはこの演習に対する比較で、既存の全68製品要件の達成率や実利用成功率ではありません。追加回帰を含むNodeのトップレベルテスト数と、その中のシナリオ数も加算しません。

Company Packの既存テストには、成功fixtureの有効期限が固定された過去日付になっている箇所がありました。実行時点から1日後の合成期限にし、期限拒否という製品動作は変更していません。subTestのassertを各case内へ戻し、Windowsでsymlink作成権限が本当にない場合だけ未実施と表示します。権限変更や無条件skipで検査を通しません。

## 一件の連続した仕事

1. 架空Workの目的を「移動後に音声会話を再開できる」とし、contextをファイルに保存してdigestをセルへ束縛する。
2. 旧担当の実Nodeプロセスを起動し、readyを受け取る。生成されたepoch付きbranch名で実worktreeを作ったことも照合する。
3. 同じWorkを「スマホ単体・BLE変更対象外」へ訂正する。旧担当はstopping、新版は停止確認待ちになる。
4. 一方の演習では旧processへ遅い結果を書かせる。他方では協調停止する。どちらも旧結果のsubmitは拒否され、実際のexitを観測してから旧予約を解放する。
5. SQLiteを閉じて開き直し、同じ新版の目的・制約・digestを復元する。重複addで仕事を増やさない。
6. 新担当の別processが同じcontextを読み、架空の接続＋音声判定を修正する。Gitにcommitし、実diff/treeを観測してsubmitする。
7. さらに別processで「接続だけ成功・音声なし」を拒否する試験を実行する。成功した合成checkを独立reviewerへ渡す。
8. 一時repository内だけで統合を実行し、実SHAを読んでintegratedへ進める。翌日の再読でも版とcontextが残る。
9. **この時点でもtask_completed=false**。端末、利用者の声、配布版を確認していないので、製品の相談を完了したことにはしない。

これは、あらかじめ与えたcontextを保持するプログラムの試験です。AIが会話を正しく理解した証明ではありません。遅延書込みは隔離した旧worktreeに実際に発生します。拒否できたのは古い成果の採用であり、悪意あるprocessの物理書込みをfenceした証明でもありません。

## 演習で修正したもの

- 再送と業務上の拒否でも、信頼されたclockの観測上限を保存する。拒否されたcell変更・request dedupは保存しない。
- Work ownerが新しい現行revisionをaddした場合、旧revisionを原子的に無効化する。旧queuedはcancelled、それ以外の未終端はstoppingとし、停止確認まで予約を保持する。
- 統合済み成果は歴史として残すが、訂正された依存先のconsumerも推移的に無効化する。上位contextに依存しない別仕事まで止めない。
- 古いrevisionの再追加・再割当・停止後の再queue、失効した依存への新規bindingを拒否する。
- projectionへWork revision、context digest、失効理由の参照を返し、引継ぎ時の照合を可能にする。新しいTask正本は作らない。
- fileとその配下、大小文字aliasを同時予約しない。書込み許可のpath比較は引き続きexactで、fileの予約をdirectory書込み権限へ広げない。

予約比較の大小文字変換は保守的な調整で、OSの全alias・symlink・NTFS短縮名を封じるsandboxではありません。実executorのパス解決と隔離は次の受入対象です。

### journal互換性

保存形式をv2にしています。v1は`JOURNAL_VERSION_UNSUPPORTED`で拒否し、bytesを保持します。旧版で合法だった複数Work revisionや、保存されなかった時刻観測を、現行規則の成功として読み替えないためです。自動migrationやjournal消去は実装していません。

既存v1がある環境では、そのまま置換しないでください。新規受付を止め、実executorの停止/fenceと外部書込みを照合し、journalとcheckpointを保存する。その後、既存Work ownerから現在のrevision/contextを解決し、重複実行を防ぐ引継ぎと旧epochより進んだfenceを設計・試験してから導入します。新しい空DBを作るだけでは復旧になりません。

## 日常の会社運営で残ること

| 実際の場面 | 演習で確認できた範囲 | まだ接続・検証が必要なもの |
|---|---|---|
| 「手伝うよ」と参加する | synthetic principalによる担当の分離、Company Pack候補作成とreview chain | 本人・組織・所有者の初回認可、担当変更、読取/実行/送信権限の対応 |
| 2人の優先順位が衝突する | 正式にadmitされた訂正版の伝播と旧版停止 | 発言者の権限、提案か決定か、矛盾が未解決なときの判断。後着発言だけでrevisionを発行しない |
| 昨日の話をもう一度説明したくない | 合成contextの実ファイル保存、digestとSQLite再開、別processの入力確認 | 既存ナレッジ/context窓口から実際のWork/sessionへ渡る最終payloadと出典版・ACL照合 |
| 「直ったけど音が出ない」 | 架空関数の否定試験、Git担当がTask完了を主張しないこと | 同じWorkへ実機失敗を返し、実機・provider・配布版で再受入する接続 |
| 不在中に問い合わせが来る | 開発kernelが顧客送信・返金を実行しないこと | 問い合わせの閲覧範囲、回答案、認可済み送信、本人対応が必要な例外。実顧客情報は未使用 |
| 利用者増加で費用が増える | 同時数・試行・実行時間・journal上限 | 金額の実計測、予約済み費用、課金期間、欠損をunknownとする処理。実採算は未評価 |
| 基板を発注したい | 開発kernelがpurchaseを受けないこと | 仕様/数量/見積の出典付き準備、当該発注権限、外部送達と決済の照合 |
| 朝夕の状況を知りたい | 同じWorkの現在版と未完をprojectionで取得 | 状態変化だけを通知する既存上位担当との接続、誤完了通知0件と再説明負担の実測 |

これらは「未実装でも適当に成功したことにしたケース」ではなく、次に受け入れる実境界の一覧です。部署、全社DB、常駐agent群を先回りして作る提案ではありません。

## GitHubは遅いか

今回測ったのはlocal演習の合否です。GitHub通信や人のreview待ちを実測していないため、速度改善率は出しません。

比較する案は、A「内部の細かな状態もGitHubへ都度同期」、B「既存Workで内部処理し、まとまった変更と結果をGitHubへ同期」です。GitとGitHubを分け、どちらも同じコード・検査・review・受入条件で比較します。Bのために別Task台帳を作りません。

測る区間は `相談→意図確定→実行開始→修正/検査→統合→配布版で利用成功`。区間ごとの待ち、費用、人の実作業時間、再説明・転記・実質判断の回数、重複実行、誤完了通知を記録します。GitHub同期を省いたぶんreviewも省く比較は不公平です。実機待ちが支配的なら、GitHubの置換では改善しません。

GitHubには[webhook](https://docs.github.com/en/webhooks/about-webhooks)があり、[APIの制限](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)もあります。毎回pollingする設計を前提に速度を断定しません。切断中の内部作業と外部操作の未送達状態を分け、復旧時に照合してから再送する設計を比較します。

## 本番への接続案と受入順序

既存の[Git Steward G1–G3](GIT-STEWARD-AND-WORK-CELLS.md)、[共通管理契約](CONTROL-PLANE-OPERATIONS.md)へ戻る順序です。新しい全体構成への移行を要求しません。

1. **現在Work・contextのadmission**。既存の本人/ACLとWork ownerで現行版を解決し、読み取った出典から最終executor入力までdigestを照合する。訂正は同じWorkの新revisionとして入れる。取消・未解決の意見・古いsnapshotを含む否定試験を行う。現在のcoreはcallerの参照文字列の真正性を検証しない。
2. **限定executor**。割当のrepository、branch、workspace、scope、epochを実際の起動と書込み直前へ束縛する。訂正/停止要求を届け、応答しないprocessも対象を特定して停止/fenceし、曖昧書込みを照合する。host跨ぎ・sandbox・credential分離は別の試験で証明する。
3. **GitHub同期**。既存の認可範囲を再利用するApp/adapterで署名検証済みイベント、delivery ID、現在head/base/check issuerを解決する。内部transactionに外部通信を入れない。送達不明→readback→必要な再送を試し、実際の統合revisionを受け入れる。merge queue等の採否は現在のrepository条件を確認して決める。
4. **Work成果の受入**。Gitの統合と、ユーザーの問題解消を分ける。元の目的に応じたdevice/provider/配布版の証拠を既存Work ownerへ戻し、「接続だけ直ったが音が出ない」で同じ仕事が継続することを確認する。通常更新を毎回の人間再承認へ変えない。
5. **復旧と日常運転**。v2 journalの保存・復元、時刻巻戻し、旧executor残存、出典訂正、ACL取消を組み合わせ、別session/hostでも二重実行しないことを確認する。実費、通知、人の負担を同じ一件で測る。

本番の最初の試行は一つの認可済みrepository、一つの既存Work、二つの担当、合成または明示的に認可された入力に限定します。read-only observationから開始し、限定実行を経て対象候補を採用します。受付停止、旧worker隔離、外部作用照合、旧candidateへの切戻しを準備し、journalを消してやり直しません。

PRはこの順序の実装候補と検証です。baseの#57、その下の#56/#49、別stackのnative OS/context候補の統合とCI状態は、それぞれ確認が必要です。このPRが成功しても、未接続の本番環境を稼働済みとはしません。

既存全体監査には分類inventoryの不足が残り、baseのworkflowが参照する`tools/audit_knowledge_workspaces.py`はそのbaseに存在しません。新しいBusiness Rehearsalチェックを全体監査の代用にせず、Checks欄の実結果と区別します。欠落したKnowledge Work実装を検査名の変更や無条件skipで隠していません。
