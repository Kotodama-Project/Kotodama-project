# Cloudflare OSのGit担当と必要単位のエージェントシステム

Status: **実行可能な調整コアのcandidate / 未配備 / proposal_only**。
既存の[全Agent統合案](OPENMAUS-UNIFIED-AGENT-CONTROL-PLANE.md)に追加する。
独立した管理画面、Task正本、scheduler、承認系は作らない。

## 1. 分けるのは「AI製品」ではなく「責任と作業」

Codex担当、OpenMaus担当、人間担当の別台帳に分けるのではない。
同じ目的・Work・成果物を共有し、実行手段を交換可能にする。
管理役の定義は常に参照できても、すべての役を常駐LLMとして動かす必要はない。

| 単位 | 担当 | 責任 |
|---|---|---|
| 目的・Work全体 | 既存Work Orchestrator | 目的、受入条件、子Work、依存関係、予算を整理する |
| リポジトリ | **Git Steward** | 担当範囲、branch/workspace割当候補、競合、差分、PR/CI/統合順を扱う |
| 検証可能な成果物 | 作業セル（Work Cell） | 一つの既存Work revision、担当、基準commit、context、grant、成果物を束ねる |
| 実装・調査の実行 | Codex等、必要なswarm、人間 | 割当範囲で作業し、証拠付きの候補を返す |
| 独立した検証 | 既存Evidence Auditor等の別principal | 成果物・CI・差分・受入条件を、作成者と分離して検査する |

今回追加する定義は既存の `governance/agent-registry.json` 内の
`git-steward` 一つ。Work Orchestratorや監査役を重複定義しない。
`candidate` であり、台帳への追加は実行権限や稼働証拠ではない。

### 作業セルを増やす条件

「誰が、何を、どこまで変更し、何をもって完了とするか」を独立に
説明・検証できる境界で分ける。実装、文書、試験を別セルにする場合も、
共有API・schema・lockfileなどの結合点を先に宣言する。
小さい修正は実装担当一つと必要な独立検証でよく、人数だけ増やさない。

同じ子Work revisionを複数providerへ二重に割り当てない。
比較実験をするなら、既存Work ownerが比較目的と別成果物を持つ子Workを作る。
swarmの追加も親の許容範囲・深さ・fan-out・費用・期限内に限る。
今回のコアはswarmを自動spawnせず、既存のbounded swarm/lifecycle契約へ接続する。

## 2. Cloudflare OS内での位置

```text
Cloudflare OS / 共通Workforce Gadget
  ├─ 目的、Work、担当者、各実行の現在位置
  ├─ Git表示：担当範囲、branch、PR、CI、競合、統合待ち
  └─ native Gatekeeper：観測認可 / submit → apply / 既存Grant照合
       └─ canonical repository IDごとのGit Steward / Durable Object
            ├─ atomicな割当journal、依存、lease、fencing番号
            ├─ immutableなbase/head/tree/diff、検証結果の照合
            └─ 限定adapter → 隔離executor / Proxmox等
                              ├─ Codex・別AI・人間の作業
                              └─ Git観測 / 停止照合 / 証拠回収
```

OSの同じ画面から見ても、元資源への閲覧権限は毎回再確認する。
workspace共有をリポジトリ閲覧権限や実行grantと同一視しない。
Cloudflare OS側のnative Gadget/Gatekeeperを使い、外部harnessをiframeで
埋めたり、秘密情報をGadgetに渡したりしない。既存brief専用Codex bridgeを
汎用コマンド実行APIに変更しない。

repository IDをもとにした一つの調整領域を全参加者で共有する。
provider・人・workspace・branch別の調整領域を作ると同じ変更を
同時に所有できてしまう。複数repositoryの変更は、上位Workの依存関係で
束ね、跨るトランザクションが成立したと偽らない。

Cloudflareには管理・状態保存を置く。CLIや任意コードは隔離executor側。
今回のSQLite adapterはDurable Objectの同期transaction APIを利用する形だが、
実Cloudflare環境への配備・native RPC生成・認証試験はまだ行っていない。

## 3. Git担当が守ること

**割当を先に決める。** 既存Work/Grant/context版、immutable base、担当者、
独立reviewer、write/read paths、意味上の競合キー、依存、予算を固定する。
割当時にbranch/workspace名と単調増加するfencing番号を発行する。
名前の発行と実Git資源の作成は別で、今回のコアは後者を実行しない。

**競合を後任に押し付けない。** 書込み同士に加え、書込みと読取りの
重なりを検査する。ファイルが違っても共有契約を変える場合は同じ
`conflict_keys` を使用する。依存先は「AIが完了と発言」ではなく、
独立検証と実際の統合の照合が済んでから後続を進める。

**完了を段階に分ける。** 基本状態は次のとおり。

```text
queued → running → candidate → verified_candidate → integrated（観測済み）
             └→ reconciling / stopping → 停止の証拠 → queued / cancelled
```

依頼受信、承認、実行開始、候補作成、検証、Git統合、canonical Taskの完了は
同じ状態ではない。`assess` が通っても `merge_authorized: false`、
`task_completed: false` のまま。Git統合の記録もTask完了やPromotionを作らない。

**時間切れを停止扱いしない。** leaseが切れても範囲を保持する。
旧workerが止まった、または書けなくなったことを限定adapterが検証してから
再割当する。前回のfencing番号で届いた成果物は拒否する。
同じrequest IDの再送は新しい実行を作らず、現在の状態を返す。
実際のGitHub書込みが成功したか不明な場合は照合を先に行う。

**古い証拠を使わない。** base/head/tree/diff、変更パス、CI issuerとhead、
reviewerを束ねる。renameは移動前・移動後の両方を検査する。
headの更新やbaseの移動があれば、受入済みの証拠を流用しない。
GitHub上のtargetが最後の読取り直後に動く競合は、この内部照合だけでは
排除できない。既存のstrict protectionやmerge queueと、実際のintegration
revisionに対するCIを別途接続する必要がある。保護設定は変更しない。

worktreeは作業ディレクトリを分ける道具で、セキュリティ隔離ではない。
悪意のあるコードを動かすときは、credentialを分離したclone/VM/containerと
write gatewayを使う。Git管理に参加していない人の操作まではleaseで防げない。

## 4. 具体例：複数人と複数AIで同じ機能を進める

ある機能について、既存Work ownerが「API実装」「画面」「統合試験」の
子Workと受入条件を確定する。Git Stewardは別々の作業セルへ束縛し、
Codex、人間、別のAIなどに割り当てる候補を管理する。

API契約が先に必要なら画面側を依存待ちにする。独立して進められる
仮実装なら契約versionと範囲を明示する。同じschemaを両方が変更する
割当は競合として拒否する。APIがmergeされたら、Work ownerが後続の
base/contextを更新したrevisionを発行し、その新しいセルで作業を進める。
古いbaseのまま自動継続することはしない。

OS画面ではproviderの会話履歴だけでなく、共通Workの目的、今の担当、
候補、待機理由、何が未検証かを同じ場所に表示する。モデル固有のsession IDは
権限付きadapterの内部に留め、公開journalへ転記しない。

## 5. 今回の実装と検証範囲

[`runtime/git-steward/`](../runtime/git-steward/README.md) に調整コア、
SQLite adapter、read-only Git observer、実行テストを追加した。
実行手順・各command・入力契約・制限はそのREADMEを参照する。

ローカル37テストは、競合、依存、再送、期限切れ、停止確認、旧epoch、
自己review、CI不備、上限、不正パス、SQLite再起動・同時writer競合を検査する。
Gitのテストは実際の一時repository/worktreeとrenameを使う。
認証principal・grant・CI receiptの入力は合成fixtureであり、
本物のGitHub/Cloudflare認証やGrant失効を検証したものではない。
Python regressionから起動するlauncherを追加し、未導入環境で黙ってskipしない。

## 6. 実稼働までの受入単位

| 段階 | 実装・合格条件 | このPR時点 |
|---|---|---|
| G0 調整コア | 複数参加者、排他、依存、永続化、再送、差分bindingの試験 | ローカル試験済みcandidate |
| G1 native OS接続 | #45–47の受入済み固定点に合わせたGadget/Gatekeeper、複数人ACL、workerd試験 | 未実装・未配備 |
| G2 限定executor接続 | live Work/Grant/context検証、隔離、GitHub Appの最小権限、実行直前fence、停止・曖昧書込み照合 | 未接続 |
| G3 統合と運用 | 正確なcheck issuer、base移動競合、merge queue等、復元、journal保持、独立review | 未受入 |

新規Gadget・公開endpoint・Cloudflare課金資源・credential・DNS・Proxmox設定を
このPRで作らない。既存の各PRを勝手にmerge/closeしない。
#56上に積み、#49とnative addon群の統合状況を別々に再確認する。

## 7. 根拠となる公開仕様

- Cloudflare OSの既存互換固定点:
  `cloudflare/cloudflare-os@c0b6f3e52ff0ab8d44d290647e256936e88e6b57`。
  Kotodama native addon参照は `9a5b616c7974a37b123e024334a69dd4964ad017`。
  最新版や本PRへのruntime取り込みを意味しない。
- [Cloudflare SQLite storage API](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/):
  同期transactionの原子性。外部APIのexactly-onceを保証する仕様ではない。
- [Git worktree](https://git-scm.com/docs/git-worktree): 作業ツリーと共有refsの区別。
- [GitHub merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue):
  targetと統合候補に対する検証。利用条件・必要workflowは導入時に再確認する。

2026-09-08にContext7と公式ドキュメントでAPIを確認した。
この文書は機能設計・コード候補の説明であり、採用・公開・Human GOの記録ではない。
