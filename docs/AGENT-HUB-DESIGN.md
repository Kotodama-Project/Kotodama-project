# 外部エージェントと協働する動的ハブ

2026-10-12の設計候補。READMEの「会話から意図・仕事・成果・学習へつなぐ」を、
利用者が普段使う常駐エージェントからも利用できる形へ広げる。
外からは一つのKotodama agentとして接し、内部では仕事に必要な役割を組み立てる。
この文書は要求と実装順を定義するもので、接続済みサービス、稼働するハブ、Task台帳ではない。
最初の限定実装は[Project情報契約とread-only view](PROJECT-HUB-VIEW.md)を参照する。

## 継続作業の入口

作業の担当・進捗・未完事項は[Project hub作業Issue #385](https://github.com/Kotodama-Project/Kotodama-project/issues/385)
へ集約する。製品意図は[owner intent](OWNER-INTENT-COMPANY-AGI.md)、設計はこの文書、
作業選択は[PROJECT-MAP](PROJECT-MAP.md)と[委任索引 #117](https://github.com/Kotodama-Project/Kotodama-project/issues/117)
が入口になる。Issueには今回の記録作業と次の実装担当の責務、実装順、受入条件がある。

次のagentはIssueの全コメント・関連PRを読み、最新mainと対象componentを確認する。
最初の実装範囲はProjectの最小情報契約・既存ownerへの対応・read-only統合viewと変更候補の検査。
GUI/会話共通操作、動的割当、実接続、最適化はその後の段階として扱う。
一周ごとにPR/commit・実行した検証・未検証・次の一手を同じIssueへ返す。
この文書の編集や文書PRのmergeを、Project hub全体の完成として記録しない。

## 既存実装からの出発点

調査対象は `c63e63291cd561c0ed2764b311935bd4f90b14a3` のsource checkout。
公開Task契約とmaintainer側のTask運用実体を区別する。
このcheckoutには `docs/PROJECT-TASK-OPERATIONS.md` と `projects/kotodama-project/` はない。
新しいTask正本を作らず、実行する際に選択済みownerへ解決する。

## 元の構想との対応

基準は[元のCompany AGI要件](OWNER-INTENT-COMPANY-AGI.md)と
[移行Epic #24の2026-10-12追記](https://github.com/Kotodama-Project/Kotodama-project/issues/24#issuecomment-6110701517)。
BecomeOneは移植元・実験kernel、Kotodamaは製品の統合先という関係を維持する。
移植後のprivate consumerは公開版とdigestへ固定し、公開coreからprivate実装を参照しない。
移植済み契約を再実装せず、[既存architecture](architecture/README.md)へ接続する。

| 元の要件 | ハブへ保持するもの |
|---|---|
| 会話からSource、Requirement、Plan、Work、検証、学習へ | agent経由の依頼も同じ因果関係と訂正履歴へ結ぶ |
| 一つのGoal Completion Owner | 外部agentが増えても、目的の完了を判断するownerを増やさない |
| append-only causal ledger | 訂正は旧記録の消去ではなく新eventとsupersession。統合viewはそこから導出する |
| OKFは知識のread model | 元資料・権限・取引台帳の代わりにしない。訂正と取消で投影を再構築・無効化する |
| RoutingとContext Resolution | ルート選択と最小Context Pack形成を分離し、どちらにも効果実行・自己承認を持たせない |
| DefinitionとInvocationの分離 | 再利用する役割定義と、毎回のgrant・期限・model・証拠の束縛を分ける |
| Goalを満たすまでの改善loop | 実行回数やテスト件数ではなく元の受入結果へ戻り、不足なら有限の修正へ進む |
| 単体利用と組織利用の共存 | 一人の小さな利用に全社基盤を必須にせず、組織では選択済みownerを使う |
| Voice / GrillU | 雑談・相談・要件化を区別。必要な不明点だけ確認し、発話停止と仕事取消を分ける |
| 検証された能力だけ移植 | [#169](https://github.com/Kotodama-Project/Kotodama-project/issues/169)の評価に従い、必要な差分とconsumer受入だけを進める |

元のmodel/subscription方針と課金API除外を、この設計から変更しない。
外部APIを接続方式の候補に載せることは、課金呼出しや新providerの採用ではない。
exact modelや利用可能枠は現行方針・実アカウントで解決し、古いmodel名を既定値としてコピーしない。
元の因果台帳は目標architectureであり、現在のTask ownerを即座に置換する提案ではない。

| 必要な能力 | 再利用するもの | この設計で追加する範囲 |
|---|---|---|
| 原意・訂正・制約の保持 | [Task v2入力](TASK-OBJECTIVE-CONTRACT.md)、`runtime/task_swarm/task_planning.py` | 外部handoffにも同じ版・入力digestを束縛する |
| 要件から仕事へ分解 | [知識入力producer](KNOWLEDGE-TASK-INPUT.md)、`tools/kotodama_kb/task_input.py` | 能力不足を検出して役割と実行先を選ぶ。現行の明示frontierから始める |
| 並行作業・修正・検証 | [closed loop](TASK-SWARM-CLOSED-LOOP.md)、`runtime/task_swarm/closed_loop_contract.py` | 計画変更・外部agent・再開の接続。現行plan v1の1〜3 jobsを無断で拡張しない |
| 横の通信 | `runtime/task_swarm/mcp_server.py` のpeer list/send/receive/ack/reply/status | 外部通信への変換と配送証拠。既存peer用MCPを公開ハブと同一視しない |
| 混雑と排他 | [有限queue](TASK-SWARM-PARALLEL.md)、[Git Steward](GIT-STEWARD-AND-WORK-CELLS.md) | provider別の能力・実行枠と接続。既存writerの排他を保持する |
| agentの生存と担当 | [lifecycle契約](PUBLIC-AGENT-LIFECYCLE-REGISTRY.md) | 実instance・lease・provider sessionの結合。実registryは未成立 |
| 必要な知識だけ渡す | [知識基盤](KNOWLEDGE-BASE.md)、[学習再利用](TASK-LEARNING-REUSE.md) | 接続先別のcontext予算と実入力の照合。学びの採用は既存ownerに返す |
| 日常の窓口 | [Dots方針](OPENAI-ALIGNMENT.md)、既存Dots plugin | 既存窓口の受入を先行し、別の製品もadapterで参加できる形にする |

STATUSや過去文書とsourceに差がある場合、実装可否は対象commitのコードと対象検証で確認する。
候補の存在を実接続・実モデル品質・会社のCurrent Truthと呼ばない。

## 外には一つ、内部は役割を分ける

```text
人 / 個人の常駐agent / 他組織agent
                 ↕
    Kotodama入口（認証・能力提示・Task参照）
                 ↕
    既存ownerへ解決 → 要件に基づく計画と割当
                 ↕
    役割A ← 許可されたpeer通信 → 役割B
                 ↕
       独立review → ownerへ成果と不足を返す

各役割 → 必須文脈 + 選択資料 → MCP / 許可されたAPI
各更新 → 既存Source・Task・知識・検証の担当owner
```

対外窓口は内部worker数に依存しない。同じ依頼への照会、追加情報、訂正、取消、成果取得を
一つの継続した仕事として提供する。外部agentの会話IDとKotodama Task IDは別々に保持する。
表示名・モデル名・同じ会社の製品であることから、identityや同じsessionを推定しない。

## プロジェクトを中心にした利用体験と情報定義

2026-10-12の追加意図は[owner intent](OWNER-INTENT-COMPANY-AGI.md)に要約して保持した。
以下の情報項目と操作例は、その意図を具体化する設計提案であり、実装済みschemaではない。

Kotodama agentは各社の個人agentと横に並ぶ協働相手になる。プロジェクトを任された場合には
内部をオーケストレーションするが、外部agentすべての親になる必要はない。
利用者は好きな入口を使い、agentや会話が変わってもプロジェクトの原意・仕事・成果が続く。

ここでのProjectは「継続する目的と、その達成のための判断・仕事・情報を束ねる単位」。
chatは対話、Sessionは作業文脈、Taskは実行単位であり、Projectはそれらの継続した関係を持つ。
複数のTask・Session・成果が一つのProjectへ属し、各Taskは選択済みのownerを保つ。
複数Projectで成果を再利用するときは参照と共有範囲を明示し、暗黙に情報を混ぜない。

### 作成時と作業中に必要な情報

既存の[project template](../templates/hierarchy/project.md)にあるoutcome、boundary、owner、
acceptance、phase、依存、証拠、rollbackを基礎にする。移植済みtemplateのbytesを直接変更せず、
後続の情報契約で次の拡張と既存fieldの対応を定義する。

| 情報群 | 持つ情報 | いつ必要になるか |
|---|---|---|
| 識別と責任 | 安定Project ID、名前、owner、revision、参加者の役割 | 作成時。IDは生成し、名前変更で変えない |
| 意図と成果 | なぜ行うか、誰のためか、元の依頼参照、欲しい成果 | 最小brief。原文と要約を区別し、訂正を追記 |
| 範囲と成功条件 | 対象・対象外、必須制約、受入条件、優先順位 | 着手する仕事に必要な粒度で確定 |
| 未知と判断 | 不明点、仮説、選択肢、決定理由、判断する人 | 発見時。未確定を推測で埋めない |
| 人とagent | 参加主体、担当能力、対外窓口、完了責任者、review担当 | 招待・割当時。所属と操作権限を分ける |
| 文脈と資料 | Source ID・版、出典、閲覧範囲、鮮度、必須資料 | 取得・配布時。全本文をProjectへ複製しない |
| 実行計画 | 要件・phase・Task参照、依存、担当、採用した実行方式 | 計画時と訂正時。別Task台帳を作らない |
| 資源と操作範囲 | 期限、利用枠、費用上限、実行場所、使える道具、自動実行範囲 | 効果を伴う着手前。Project所属からgrantを推定しない |
| 成果と検証 | artifact、版、要件との対応、readback、review、未解決点 | 提出・確認時。生成と採用を区別 |
| 継続と学習 | 現在地点、次の一手、停止理由、再開参照、再利用する学び | 中断・再開・完了時。未検証の学びは候補 |
| 最適化方針 | 品質・速さ・費用・人の介入の優先度、比較基準、変更可能範囲 | 既定案を提示し、必要に応じて調整 |

作成の必須入力は「何を実現したいか」と責任主体を基本とし、認証済み利用者から責任主体を
解決できれば入力を繰り返させない。Project名や整理案はagentが提案できる。
「未入力」「不明」「該当なし」を区別し、作成できる条件と実行できる条件を分ける。
足りない情報は既存資料から探し、その仕事に影響する不明点だけを質問する。
雑談を自動的にProjectへ昇格させず、明示した作成依頼または既存の自動作成方針へ結ぶ。

### GUIと自然言語で同じ仕事を動かす

主な画面はProjectの「目的と条件」「進行中の仕事」「成果」「必要な判断」。
利用者には、次に何が進むか、何が止まっているか、どこを変えられるかを見せる。
agentのgraphや細かな実行記録は、必要なときに開ける詳細表示にする。

| 利用者の指示 | GUIでの対応 | 同じProjectで起こること |
|---|---|---|
| 「この企画をプロジェクトにして」 | 新規作成とbrief入力 | 安定IDと原意参照を持つdraftを作る |
| 「調査と試作を並行して」 | 仕事の分割・担当設定 | 依存と能力を確認し、計画候補を更新 |
| 「費用を抑えて、品質は維持して」 | 実行方針の変更 | 必須受入条件を保ち、ルート・並行度の候補を変更 |
| 「この条件を追加して」 | 目的と条件の編集 | revision更新、影響範囲の表示、必要な再計画 |
| 「ここの担当を変えて」 | 担当の変更 | 旧実行の状態を確認して引継ぎ、文脈と権限を再束縛 |
| 「ここまでの成果を見せて」 | 成果一覧 | 要件との対応、採用済み・確認待ち・不足を表示 |
| 「この仕事を止めて」 | 対象Taskの停止 | 対象を限定して取消。Project全体停止と区別 |

両入口は同じ更新契約・revision検査・認可を使う。GUIからの訂正が会話にも反映され、
会話からの変更がGUIにも現れる。古い画面の操作やmessage再配送による上書き・二重実行を防ぐ。
方式は単独、専門家への委任、並行、段階実行から選べ、agentの推奨理由と変更の影響を表示する。
「任せる」は既存範囲内の選択を委任する意味とし、外部共有や予算上限を自動で広げない。

### プロジェクト単位の最適化

最適化は、まず必須品質・期限・権限・費用上限を満たす経路に絞り、その中で利用者の優先度に
応じて選ぶ。品質重視、速さ重視、費用重視などのpresetは同じprofileへの入力にする。
単一のscoreだけで判断せず、成果の受入率、修正回数、待ち時間、計測できる費用を比較する。

改善可能な変数は役割分割、担当能力、資料選択、tool/skill、並行数、再試行、review配置。
変更案には理由・比較対象・期待効果・停止条件を持たせる。元の成功条件を下げる変更は
最適化として扱わない。Projectの作業を完了するloopと、進め方を改善するloopに予算を分け、
改善実験が本来の仕事を延々と遅らせないようにする。Project間の学びは既存の採用・共有条件を通す。

### 最初の体験の受入

「小さなイベントを企画して」という指示からProject draftを作り、目的・成果・不明点を
短く提示する。調査と制作を分担し、GUIで予算条件を訂正すると、会話側と必要な仕事に新版が
反映される。途中で担当agentを替えても原意と証拠が残り、成果を条件ごとに確認できる。
再開時には同じProjectの現在地点から進む。これは合成シナリオ案で、予約や支払は含めない。

最初の実装sliceは、この情報契約を既存Project/Task参照へ対応付け、read-only統合viewと
変更候補の検査を作る。その後、同一の操作をGUIと会話から扱う縦断実装へ進む。
GUI、永続Project service、最適化engineはこの文書では未実装。

## 通信方式の選択

[MCP仕様](https://modelcontextprotocol.io/specification/latest)と
[A2Aの役割](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)を2026-10-12に確認した。
実装時は可変なlatest URLだけでなく、採用版とSDK・対応機能を固定する。

| 接続 | 使う場面 | 契約 |
|---|---|---|
| MCP | agentからKotodamaの道具・文脈を利用する | resource/toolの発見と呼出し。長時間処理や通知は相互の対応能力を確認 |
| A2A | 独立した外部agentへ仕事を渡し、継続・成果を交換する | Agent Card、Task、Message、Artifactの変換。相手の実対応が前提 |
| 製品の公式API | 独自のagent/task/session操作が公開されている | APIのidentity、scope、版、制限をadapterが保持 |
| 内部peer transport | 同じTask内の親子・横連携 | 現行owner bindingとpeer allowlistを再利用 |
| 手動handoff | 自動接続の公開仕様や権限を確認できない | 入力と結果を人が渡す。自動連携として表示しない |

MCP/A2Aを導入するだけで、全製品のagent作成や直接通信が可能になるわけではない。
モデルAPIへの呼出しは、利用者が持つ常駐agentの記憶・computer・ログインを操作しない。
外部製品の常駐agent新設と、Kotodama内部の短命worker起動も別の操作にする。

adapterの能力は `discover / submit / observe / message / cancel / fetch_artifact` ごとに
supported、unsupported、unverifiedを記録する。認証方法、protocol版、最終確認日、接続テストの
証拠参照を併記し、未知の機能は選択しない。製品ごとの比較表は公開repoへ置かない。

最初のMCP候補は、既存ownerに委譲する `context.get`、`task.get`、`task.propose`、
`task.correct`、`task.cancel`、`artifact.get`。これらは**未実装の候補名**であり、
既存peer toolsや外部の標準method名ではない。読取と変更要求を分離し、同じ認可を再利用する。
新規依頼からのTask作成は既存ownerのadmissionを必須とし、入口独自のTask DBを作らない。

## 要件を失わない台帳の扱い

「一つの台帳を見れば分かる」は既存正本への統合viewとして実現する。
要件、Task、agent lifecycle、検証、採用はそれぞれのownerが更新し、ハブは参照と変更要求を渡す。
要件の照会は少なくとも次の対応を返す。

```text
requirement ID + revision + Source span
  → 元の意図 / 現在の訂正 / 祖先制約 / 未知 / 受入条件
  → 担当job・agent / 成果参照 / criterionごとの検証 / 未解決点
```

この記法はviewの要求であり、別の永続schemaではない。既存IDを再利用し、解決できない参照は
欠落として返す。要約だけから原意を復元したことにしない。

1. 着手前に現行Task revision、Source、要件、grantを読む。
2. workerへ原意、最新訂正、全必須制約、未知、受入条件を渡し、実入力digestを記録する。
3. 追加資料は仕事に必要なspanだけを選ぶ。必須文脈が予算に入らなければ分割候補か不足を返す。
4. workerは成果・根拠・要件変更案を返す。要件変更案と作業進捗は別に扱う。
5. ownerは現在revisionを条件に更新する。競合は再読・再計画へ戻し、後勝ち上書きをしない。
6. 訂正が入れば影響するjobを無効化する。旧revisionの結果で新しい要件を完了にしない。
7. 全必須criterionに担当成果の証拠と独立reviewがそろってから、ownerへ完了候補を返す。

作業で分かった事実や進捗は許可範囲で自動更新する。成功のために受入条件を緩める、
原意を削る、権限を増やす変更は自動的に採用しない。既存の変更権限で扱える範囲は進め、
範囲外の判断だけをownerへ返す。更新理由、旧版、新版、影響する仕事を辿れるようにする。

## 必要時の生成と上下・横の連携

まず現在のworkerで要件を覆えるか調べ、不足する能力と独立性だけを追加する。
「仕事があるから必ずagentを増やす」規則にはしない。各workerには一つの明確な担当、
受入条件、期限、利用可能な道具、親、取消先を与える。

親は分解・割当・統合を担い、子は成果・不足・質問を返す。横の通信は必要な相手だけに開き、
情報交換から他agentの権限や担当が勝手に変わらないようにする。
所属の木、実行依存のDAG、通信可能なgraphは別々に表す。横通信の循環を仕事の循環と混同しない。

plannerが作る分解は候補として検査する。全要件coverage、循環、参照解決、上限、
同時書込みの競合、reviewer独立性が成立してから既存ownerが実行を受け入れる。
第一段階は既存の明示frontierと最大3仕事を使い、自由文からの再帰生成は後続とする。

メッセージにはTask/revision、run/attempt、送信者・受信者、親message、種別、
context digest、成果参照、idempotency key、期限を結び付ける。
ACKは配送確認であり、成果の正しさやTask完了ではない。
配送は重複し得るものとして受信側で重複排除し、順序逆転・旧attempt・期限切れを検査する。
応答不明な外部操作は再送で二重実行せず、providerの状態照会で照合する。

生成は権限と実行枠の予約後に行い、完了・取消・期限切れで回収する。停止未確認なら
枠と不明状態を保持する。親の再起動時は既存runを照合し、同じ子を無条件で作り直さない。
leaseやattemptの更新は既存ownerの排他処理へ結び付ける。

## 変数として変更できる中身

役割、手順、model、provider、資料選択、計画、並行度はversion付きprofileとして扱う。
profileは任意コードや文字列テンプレートの実行ではなく、型・範囲・参照が検証される宣言にする。
次は**将来のprofile例**で、現在のconfigへ貼っても実行できない。

```json
{
  "profile_version": 1,
  "profile_id": "research-small",
  "revision": 1,
  "roles": ["research", "synthesis", "independent_review"],
  "routing": {"required_capabilities": ["research"], "fallback": "pause"},
  "limits": {"max_workers": 3, "max_parallel": 2, "max_depth": 2, "max_replans": 1},
  "context": {"selection": "required_then_relevant", "max_bytes": 262144},
  "communication": {"parent_child": true, "peer": "allowlist"},
  "changes": {"apply_at": "next_attempt", "require_expected_revision": true}
}
```

現行runtimeの上限、owner grant、profile設定のうち最も狭い値を適用する。
reviewの枠と費用も予約対象に含める。`max_depth`は検査上限で、再帰実行の実装済み宣言ではない。
deadline、token、金額はTaskごとの予算参照に束縛し、計測できないproviderで厳密な金額制御を
保証しない。profile既定値だけで予算や新たな権限を付与しない。

| 変更対象 | 適用方法 |
|---|---|
| 役割・skills・model・資料選択 | 次attemptから新revisionを固定し、実入力と選択理由を記録 |
| 原意・制約・受入条件の訂正 | ownerのTask revision更新、旧結果無効化、再計画 |
| 並行数の減少 | 新規開始を抑制。実行中workerは停止確認まで計上 |
| 取消・アクセス失効 | 実行境界と結果返却で再確認。旧profileでも継続を許さない |
| provider障害 | 必要能力とデータ共有許可が一致する検証済み経路だけへ切替 |
| 学んだ手順・promptの変更 | 学習候補→独立評価→ownerによる採用→次のprofile版 |

設定を戻しても失効した権限や無効化された成果は復活させない。
現在実行の版と次に使う版を利用者から照会できるようにする。

## 実装順と観測可能な受入

| 段階 | 作るもの | 完了条件 |
|---|---|---|
| 1 | 既存ownerへの参照解決と統合view | 一つの依頼から原意・訂正・担当・証拠を辿れる。別Task台帳が増えない |
| 2 | profile検査と能力に基づく有限planner | 1要件と3要件で必要な役割が変わる。未割当・不明能力・予算不足は起動前に分かる |
| 3 | 同じTaskへの内部生成・peer・再開 | 二重配送と再起動でも二重jobを作らない。取消後の結果を採用しない |
| 4 | 一つの実接続adapterとMCP入口 | 同じ依頼の提出→訂正→照会→取消→結果readbackを実アカウントで確認 |
| 5 | A2Aと追加adapter | 接続先を変えても要件・権限・出典・継続状態を保持。非対応機能を表示 |
| 6 | 評価に基づくprofile改善 | 同じ受入課題で品質・時間・費用を比較し、悪化時に前版へ戻せる |

一つの受入演習は「調査して提案する」仕事を二つに分解し、途中で必須条件を訂正する。
両workerが新版を読み、横からの旧情報で条件が戻らず、criticが不足条件を検出し、
修正後の成果と全criterionの証拠が同じownerに返ることを確かめる。
必須資料欠落、別tenant、失効、reviewerの自己審査、停止未確認、予算枯渇も同じ経路で扱う。

品質指標は要件の検証coverage、訂正の反映漏れ、再開時の重複実行、完了までの時間、
利用者の修正回数、受入成果あたりの費用とする。coverageの件数だけで意味的な達成を判定しない。
profile変更や学習で改善したという主張には同一課題での比較結果を必要とする。

設計全体の受入は未完。限定実装の検証は上記Project view文書へ分ける。新たなruntime、provider接続、
自動agent生成、A2A server、台帳更新は未実装であり、公開状態は `NO_GO_UNPUBLISHED` のまま。
