# Kotodama

**会話を、監査可能な意図・仕事・成果・学習へ。**

Kotodama は、人間が普段どおり話し、相談し、アイデアを共有するところから、その中にある意図を AI と人間が一緒に理解し、要件、判断、仕事、成果物、検証証拠へ接続する **Local-first Company OS** を目指すプロジェクトです。

私たちが作ろうとしているのは、単独の Discord Bot、文字起こしサービス、Markdown テンプレート集、エージェントを並べただけの自動化基盤ではありません。Discord の Voice・テキスト、Issue、文書、業務データを会社への入口として、人間と AI が目的、文脈、権限境界、証拠を共有しながら、会社を立ち上げ、仕事を進め、価値を提供し、学習できる環境です。

> [!IMPORTANT]
> このリポジトリは **Incomplete Public Preview** です。公開している Company starter、schema、validator、runtime/evidence candidate は試せますが、Public Beta の利用受付、Discord 招待、公開 Voice Bot はまだ提供していません。公開アクセスを開くための Final Human GO も完了していません。最新の境界は [Project Status](STATUS.md) を確認してください。

## North Star

> 人間の意図を最上位の基準として、会話から意図を抽出し、監査可能な仕事・成果物・学習へ変換する。

会話は重要な Source Evidence です。しかし、会話や AI の推測だけで会社の Current Truth を書き換えることはありません。提案、決定、実装、検証、採用を分離することで、速く作りながら、後から次を確認できる状態を作ります。

- なぜこの仕事を始めたのか
- どの発言や資料を根拠にしたのか
- 誰が何を決め、何を許可したのか
- どの候補 bytes を、どの方法で検証したのか
- 何が採用され、何がまだ候補なのか
- いつ、どの条件で停止・rollback するのか

## なぜ Kotodama を作るのか

会社の仕事は、会話の中から始まることが多い一方、その意図はチャット、議事録、Issue、個人の記憶へ散らばります。自動化を追加しても、目的と実装がずれたり、誰が許可したのか分からなくなったり、local test を本番稼働と誤認したりすれば、会社の能力にはなりません。

Kotodama は、この分断を一つの証拠鎖でつなぐことを目指します。

```text
会話・音声・Issue・文書
    ↓
何を実現したいのかを検知
    ↓
不足している要件だけを確認
    ↓
目的・制約・成功条件・停止条件を整理
    ↓
実行可能な仕事へ分解
    ↓
実装・調査・制作・運用
    ↓
成果物と検証証拠
    ↓
人間または定められた policy が採用を判断
    ↓
会社の知識・能力・Current Truth へ反映
```

## Founder Intent と開発原則

Kotodama の設計は、次の意図を同時に満たす方向で進めています。

- **Human Intent first** — 開発や自動化そのものを目的にせず、人間の目的、受益者、制約、成功条件、停止条件を上位に置く
- **Build first** — 安全で可逆な候補実装は承認待ちだけで止めず、まず動く小さな縦切りを作る
- **Evidence matched claims** — local test だけで live、deployed、safe、complete、Public Beta と呼ばない
- **Local first** — 音声、文字起こし、会社データ、証拠を可能な限り local trust boundary に置く
- **Simple interaction, explicit governance** — 利用者の操作は軽くしつつ、同意、権限、訂正、保持、監査、停止を省略しない
- **One canonical owner per fact family** — Discord、DB、Git、ダッシュボードへ競合する正本を増やさない
- **Replaceable adapters** — Voice、LLM、workflow、storage provider を一つの実装へ固定せず、契約の後ろで交換できるようにする

「まず作る」と「証拠なしに完成と呼ばない」は対立しません。Kotodama では、実装開始は速く、昇格と公開の主張は慎重に行います。

## Discord の中に会社を作る

Kotodama における Discord は、Bot の設置場所ではなく、人間と AI が共に働く **Office / Input Surface / Projection** です。

- 日常会話や Voice でアイデアを共有する
- 仕事を依頼し、必要な要件だけを詰める
- AI の活動、進捗、成果、問題を見る
- 人間と AI が同じ場所で協働する
- 新しい人、Resident Clone、専門エージェントを迎える
- 判断候補や実行結果を、元の会話へ分かりやすく返す

ただし、Discord 自体を Company SSOT にはしません。メッセージや transcript は Source Evidence であり、Human Decision、Capability Grant、Verification Receipt、Promotion、Current Truth は Discord から独立した統治層で扱います。

## 理想のユーザー体験

Kotodama が目指す体験は、長い仕様書を最初に書くことではありません。

1. 人間が Discord、Voice、Issue、文書で普段どおり相談する
2. Kotodama が目的、受益者、制約、成功条件、停止条件の候補を抽出する
3. 重要な曖昧さだけを GrillU が一問ずつ確認する
4. 確認済みの候補を、権限と停止条件を持つ Work Order へ変換する
5. AI または人間が bounded execution lane で仕事を進める
6. 成果物、test、観測、rollback 情報を Verification Receipt に束縛する
7. authority を持つ人または policy が、候補の採用・拒否を判断する
8. 結果と学習が会社の Office と正本へ戻る

この完全な体験はまだ Public Beta として提供していません。現在の公開リポジトリでは、その中核となる Company governance flow と検証ツールを先に試せます。

## Voice — 最初に価値を体感する入口

Voice は付属機能ではなく、Kotodama の思想を最短で体感できる最初のプロダクト面です。目指しているのは、音声を一つの文章へ変換するだけの仕組みではありません。

```text
Private Discord Voice Channel
→ 話者ごとの音声取得
→ consent / retention gate
→ local ASR
→ 話者・時刻・発話内容の対応
→ 話者別 transcript と全体 context
→ 15分単位で private channel へ返す
→ Intent / ToDo / Goal / Decision Candidate
→ GrillU または Verified Handoff
```

既存の local / Proxmox Voice 処理系と話者別処理の候補はありますが、この公開リポジトリに public Voice runtime、実音声、transcript corpus、private Discord identifier は含みません。公開保証された Voice service ではありません。

### 15分 Voice rotation

15分は内部 timeout ではなく、利用者が会話を続けながら価値を受け取るための製品体験です。

- 会話中の無音や退出だけに依存せず、自然な 900 秒境界で区切る
- それまでの内容を、話者と時刻を保ったまま private channel へ返す
- 次の rotation を途切れさせずに開始する
- 退出・再参加後も listener と rotation が回復する
- 同意と保持期限に従って raw audio、chunk、transcript を削除し、receipt を残す

#### 利用者が受け取る15分の境界

15分 rotation は、内部処理の区切りではなく、会話を続ける利用者へ返す
成果の契約です。理想の製品体験と現在の Public Preview を、同じ項目で
読み分けられるようにします。

| 項目 | 理想の製品体験 | 現在の Public Preview |
|---|---|---|
| 境界 | 自然な 900秒境界で、それまでの発話を一つの区間として確定する | 実音声での 900秒 rotation は未証明 |
| 投稿 | 話者・時刻付き transcript を private channel へ投稿し、次の区間を開始する | public Voice Bot と Discord 投稿は未提供 |
| 継続 | listener / rejoin を維持し、退出・再参加でも rotation を途切れさせない | 既存 local candidate はあるが、常時 listener / rejoin E2E は未証明 |
| 保持 | raw audio、chunk、transcript を retention policy に従って削除し、retention/delete receipt を残す | raw audio・transcript corpus・公開削除 receipt は含まれない |

常時 listener、確実な rejoin、自然な 900 秒 rotation、Discord 投稿、期限内削除を同じ候補と時間窓で結んだ E2E は、まだ公開済みの証明ではありません。

### Voice-to-Verified-Handoff

Voice の品質は文字認識率だけでは決まりません。

- 誰が話したか
- いつ話したか
- どの発話を根拠にしたか
- どの Intent Candidate を抽出したか
- どの候補を人が確認・訂正したか
- そこから何が実行され、何が採用されたか

これらを追跡できることが重要です。話者別 audio / ASR を authority とし、mixed audio や merged transcript は比較・文脈用途として扱う設計を目指します。

> Kotodama Voice は、音声を文章へ変換するだけでなく、会話を検証可能な仕事へ接続する Voice-to-Verified-Handoff pipeline を目指します。

## GrillU — 一度に一つだけ深掘りする

GrillU は、利用者に長い仕様書を書かせる仕組みでも、自動承認する Discord Bot 機能でもありません。検知した Intent Candidate に重要な曖昧さがあるとき、次の一問だけを出すチャネル非依存の要件深掘り機能です。

```text
検知された Intent Candidate
→ 現在の Requirement State
→ 次の重要な質問を一つ
→ 最大3つの選択肢 + 保留 / 修正
→ Human response
→ 根拠付き Requirement State 更新
→ 次の質問、または Human-confirmed Requirement Candidate
```

回答は、はい / いいえ、1 / 2 / 3、この理解で OK、修正する、分からない、後で、のように軽くします。Human が内容を確認しても、それだけで Human Decision、Work Order、execution authority、Promotion、Current Truth にはなりません。

将来は Discord、Voice、Web、Mobile、Codex UI のどこからでも同じ Requirement State を扱える構造を目指します。GrillU contract と prototype は local candidate であり、この公開 preview の提供機能ではありません。

## Evidence Chain — 会話から Current Truth まで

Kotodama の正規鎖は次です。

```text
Source Evidence
→ Intent Candidate
→ Human Decision
→ Work Order
→ Capability Grant
→ Change Candidate
→ Verification Receipt
→ Promotion Candidate
→ Promotion Decision
→ Current Truth
```

| 段階 | 意味 | それだけでは作らないもの |
|---|---|---|
| Source Evidence | 会話、音声、Issue、文書などの出典付き入力 | 確定意図、実行権限 |
| Intent Candidate | 目的、受益者、制約、成功・停止条件の仮説 | Human Decision |
| Human Decision | authority を持つ人が範囲と条件を持って採否を決めた記録 | 実行そのもの |
| Work Order | 成果物、対象、期限、受入・停止条件を結ぶ実行契約 | 未記載の権限 |
| Capability Grant | identity、resource、action、期限、上限を限定した権限 | 無制限のアクセス |
| Change Candidate | まだ採用されていない可逆な変更候補 | Current Truth |
| Verification Receipt | exact bytes、test、観測結果を束縛した記録 | 真正性や Human approval の自動保証 |
| Promotion Decision | 候補を採用・拒否する authority-bound 判断 | 別候補への包括的 GO |
| Current Truth | 採用済みの現在状態 | Source の履歴消去 |

この鎖を短絡しないことが、速度を失わずに訂正可能性と監査性を保つ鍵です。

## Human Intent SSOT

人間の発言を一文だけ切り出して「確定意図」にすることはしません。Human Intent には、少なくとも次の要素が必要です。

- purpose / beneficiary
- vision / mission
- constraints / non-goals
- KGI / KPI または受入条件
- authority と対象範囲
- stop / rollback / review conditions
- 根拠となる Source と revision
- confirmed / proposed / unknown の区別

後から届いた訂正、撤回、精緻化は、古い提案より優先して追跡します。たとえば「Discord を SSOT にする」という初期表現は、現在は「Discord は Office、正本は governed Company OS」として精緻化されています。

## Company Template — 会社を再現できる部品

現在このリポジトリで最も具体的に試せるものが [Company starter](examples/company-starter/README.md) です。単なる Markdown 雛形ではなく、仕事を進める構造と検証可能な記録を組み合わせています。

| 部品 | 役割 | 公開 starter |
|---|---|---:|
| Blocks | 入力、出力、authority、拒否条件を持つ再利用可能な処理単位 | 9 |
| Governed Records | Block から生まれる監査可能な候補記録 | 9 |
| MOCs | 同じ canonical flow を目的別に辿る navigation map | 3 |
| Manifest | owner、profile、flow、禁止 action を束縛する入口 | 1 |
| Validators | 構造、参照、順序、禁止経路を機械検査する | dependency-free |
| Catalog | Block、Record、MOCの関係をread-onlyで一覧する | JSON / Markdown |
| Review Bundle | 全 22 JSON 文書の exact bytes を SHA-256 へ固定する | candidate-only |

### 9 Blocks

1. Source Intake
2. Intent Candidate
3. Human Decision
4. Work Order
5. Capability Grant
6. Change Execution
7. Verification Receipt
8. Promotion Gate
9. Promotion Decision

各 Block の出力は、対応する Governed Record へ一対一で接続します。Capability Grant のない Change、Human evidence のない Promotion Decision、flow 順序の短絡を validator が拒否します。

### 3 MOCs

- **Company Operations** — Source Intake から Promotion Decision までの canonical flow
- **Public Release Review** — 公開候補の確認に必要な部分列
- **Incident & Recovery** — 問題発生時の判断、変更、検証、復旧を辿る部分列

MOC は navigation projection です。MOC 自体が新しい SSOT や実行権限を作ることはありません。

まず全体の対応を一覧したい場合は [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) を実行してください。詳しい編集方法は [Template Guide](docs/TEMPLATE-GUIDE.md)、最短の体験は [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)、candidate-bound review は [Review Workflow](docs/REVIEW-WORKFLOW.md) を参照してください。

### 理想の使い方と、現在の Public Preview でできること

理想的には、Company Template は「ファイルをコピーして終わる雛形」ではなく、新しい会社の境界と仕事の流れを再現する入口です。

```text
Company Template を複製
→ Vision / Mission / Boundary を編集
→ 必要な Blocks と human role を選択
→ MOC で目的別の導線を決める
→ Manifest、owner、profile、capability、expiry を束縛
→ validator と customization checker
→ exact-byte Review Bundle
→ protected evaluation
→ activation candidate
```

現在の Public Preview では、このうち **複製、編集、Catalog、validator、customization checker、Review Bundle の作成と照合**を local / synthetic の範囲で実行できます。starter の `draft` 記録を確認し、Blocks がどの Governed Record を生み、MOC がどの順番で辿るかを読むことができます。

一方、`protected evaluation` と `activation candidate` は、候補の exact bytes、Work Order、権限、検証 receipt、rollback 条件を別途束ねる次の段階です。公開 README を読んだこと、validator が PASS したこと、Review Bundle が MATCH したことだけでは、会社の runtime を起動したり、権限を付与したり、Promotion や Current Truth を変更したりしません。

| 段階 | 理想 | 現在の Public Preview |
|---|---|---|
| Template | 会社の Vision、Boundary、owner、profile を持つ再利用可能な開始点 | `examples/company-starter` を複製して自分の候補へ編集できる |
| Blocks | 仕事の処理単位を組み替え、必要な能力と拒否条件を束ねる | 9 Blocks の schema、Record 対応、validator を読んで検査できる |
| MOCs | Company Operations、Public Release、Incident / Recovery を目的別に辿る | 3 MOCs の順序と参照を Catalog で read-only に確認できる |
| Records | Source、Decision、Work、Receipt、Promotion を証拠付きでつなぐ | 9 Governed Records の `draft` 候補を作り、構造を検査できる |
| Activation | protected evaluation 後に candidate-bound decision で採用する | runtime activation、公開招待、Public Beta GO は未提供 |

この区別により、理想の Company OS の設計を先に試しながら、現在実際に動く local candidate と、まだ証明されていない runtime / authority を混同しません。

## Context Platform — 会社の共有記憶

人物、Goal、ToDo、会話、ファイル、Issue、判断、証拠、エージェント状態を、許可された範囲で横断できる共有文脈が必要です。

```text
People / Goals / ToDos / Projects
Conversations / Documents / Source Records
Relations / Chunks / Embeddings
Consent / Retention / Capability Grants
Retrieval Receipts
```

目標は「一つの DB user が全データを読めること」ではありません。**一つの governed query plane から、その AI identity に許可された Authorized Corpus へ一貫して到達できること**です。エージェントが storage へ無制限な生 SQL で接続するのではなく、Context Gateway が corpus、purpose、retention、redaction、rate、receipt を検査する構造を目指します。

TiDB は People / ToDo / File / Conversation / relation / embedding を横断する Context Platform の第一評価候補ですが、採用済み、deployed、PostgreSQL replacement、Current Truth ではありません。この公開 preview に TiDB runtime は含まれません。

## Resident Clone と Clone Birth

Kotodama の onboarding は、設定画面を埋めるだけでなく、新しい協働主体が境界付きで「誕生する」体験を目指します。

```text
利用者との対話
→ 目的・過去 context・境界の確認
→ Agent Cell Candidate の選択
→ Voice Persona Candidate
→ capability と prohibited actions
→ 協力する agent / workflow
→ recovery / stop 条件
→ Resident Clone Candidate
→ reviewable receipt
```

Resident Clone は、利用者の仕事を引き受け、必要に応じて他のエージェントと協力する長期的な AI identity の候補です。Voice Persona は本人認証ではなく、Resident Clone も無制限の権限主体ではありません。目的、accessible corpus、capability、費用上限、期限、review、停止、recovery を持つ必要があります。

Clone Birth prototype と resident runtime / OpenClaw 接続候補は local candidate であり、この公開 preview から clone を作成・起動することはできません。

## Agent Foundry と AI Workforce

Kotodama は、固定されたエージェント一覧を install して終わる設計ではありません。実際の仕事の中で「この仕事には、どの専門 role / skill / agent cell が必要か」を判断し、候補を作り、検証し、採用する Agent Foundry を目指します。

各 agent cell には少なくとも次が必要です。

- role / purpose / owner
- accessible Authorized Corpus
- capability / prohibited actions
- environment / provider / tool boundary
- cost / rate / time limit
- expiry / review policy
- stop / recovery
- activity / verification receipt

AI は、自分自身の権限、評価基準、採用状態を勝手に変更できません。能力を増やすことと、authority を増やすことは別の Decision として扱います。

## AI-only と human-audited

Kotodama は、完全自動化か人間中心かの二択を取りません。同じ Source、Intent、Work Order、Change Candidate、Receipt を使い、lane ごとに Promotion policy を変えます。

| Lane | 例 | Promotion policy |
|---|---|---|
| AI-only candidate | local analysis、synthetic test、可逆な draft | policy 内で自動評価できる候補。権限外へは出ない |
| Human-audited | 内部変更候補、費用や利用者影響を持つ操作 | 人間が receipt と差分を確認して採否を決める |
| Human-controlled | 公開、契約、価格、請求、決済、個人情報、権限変更、不可逆操作 | candidate-bound Human Decision が実行前に必要 |

AI-only でも証拠と停止条件は省略しません。human-audited でも人間が全手順を手作業する必要はありません。

## AI Business Loop

長期的には、Kotodama を社内業務だけでなく、AI 主導の価値創出と収益化へ使います。

```text
Idea generation
→ independent challenge
→ market validation
→ offer design
→ build
→ distribution
→ fulfillment
→ finance
→ customer / community feedback
→ learning
```

すべてを同じ証拠鎖と権限モデルで扱い、AI-only と human-audited の lane を選びます。「稼げる」という一語でまとめず、revenue hypothesis、支払意思、契約、入金、contribution margin、継続可能な利益を分けて記録します。

この AI Business Loop は product direction です。公開 preview は事業運営、契約、請求、決済を実行しません。

## Local-first architecture

Local-first は、すべてを一台へ詰め込むことではありません。private data と authority を local trust boundary に保ち、外部 provider を明示的な adapter と grant の後ろへ置く考え方です。

| Surface / component | 役割 | 現在の扱い |
|---|---|---|
| Discord | Office、Input Surface、Projection | SSOT ではない |
| Voice Adapter | 話者別 capture / ASR / handoff contract | existing local candidate、public runtime なし |
| n8n | bounded workflow / AI call plane | local direction、公開 runtime なし |
| OpenClaw / resident runtime | Resident Clone の長期実行候補 | local integration candidate |
| PostgreSQL Company DB | operational fact family の候補 | Compose skeleton は公開、live E2E は未証明 |
| Evidence metadata Store | receipt、hash、provenance の候補 | Compose skeleton は公開、live E2E は未証明 |
| Context Gateway | Authorized Corpus への governed query plane | design / local candidate |
| TiDB | Context Platform の第一評価候補 | 未採用、未配備 |
| Proxmox | segmented local runtime の基準候補 | lifecycle contract 公開、live receipt なし |
| Compose minimum | 小さな導入 profile | secret-free skeleton / candidate 公開 |
| Cloudflare | optional public edge | optional、free-plan-first、必須ではない |

provider を利用する場合も、exact artifact、participant scope、purpose、provider/model、expiry、cancellation、retention を持つ transfer grant の後ろに置く方針です。

## Consent、privacy、retention

Voice channel への参加だけを、録音、外部転送、学習再利用、長期保持への包括同意とは扱いません。

- capture、transcription、provider transfer、reuse を別目的として扱う
- participant と時間窓へ同意を束縛する
- raw audio、chunk、transcript、derived record の保持条件を分ける
- 同意撤回、削除、停止、incident recovery を設計する
- public artifact へ secret、token、cookie、invite、private identifier、実音声を含めない
- synthetic / bot record を Human Decision evidence として使わない

現在の公開リポジトリには raw audio や transcript corpus を含みません。

## Security、authority、stop

アクセス可能であることと、実行を許可されていることは別です。Kotodama は capability を identity、resource、action、purpose、期限、上限、停止条件へ限定します。

公開、外部送信、本番 write、契約、価格確定、請求、決済、credential / permission 変更、不可逆削除は、高影響 action として候補と authority を明示的に束縛します。Public launch は、同じ candidate bytes に対する scope-matched E2E、独立検証、Final Human GO が揃うまで NO-GO です。

## 過去の表現から現在の設計へ

Kotodama は、初期の言葉を消すのではなく、後続の指示、実装、失敗、privacy 境界で精緻化してきました。

| 初期の表現 | 現在の解釈 |
|---|---|
| Discord を SSOT として一元化 | Discord は Office。正本は governed Company OS |
| AI がすべての権限と情報を握る | identity 別の bounded Capability Grant |
| 全員身内なので複雑にしない | UX は簡単にし、同意、訂正、削除、監査は省略しない |
| Voice channel 参加者は同意済み | historical proposal。現在は目的別 consent-bound policy を優先 |
| 音声を test corpus として再利用 | 後続の再利用・共有禁止指示を優先 |
| まず自分の声の clone を作る | Voice Persona Candidate を Clone Birth へ組み込む |
| Bot を作ってと言えば全部作る | GrillU → Requirement Candidate → bounded Work Order |
| AI だけで稼げる会社 | policy 内で AI が loop を進め、人間が監査・例外・高影響判断を担当 |
| まず動かして後から直す | build-first。ただし live、安全、完成の主張は証拠に合わせる |
| TiDB をできるだけ採用する | Context Platform 第一評価候補。PoC と fact-family 別 Decision 後に採否を決める |
| 未完成でも公開する | Incomplete Public Preview として、実証済みの面だけを公開する |

この表は経緯を説明する projection であり、単独で Human Decision や Current Truth を作るものではありません。

## 現在地 — 夢と実証範囲を分ける

### この Public Preview で利用できるもの

- プロジェクトの方向性、[status](STATUS.md)、[roadmap](ROADMAP.md)
- 9 Blocks、9 Governed Records、3 MOCs を持つ Company starter
- manifest / Block / Record / MOC schema と dependency-free validator
- 上書きを拒否する starter initializer
- placeholder、review、runtime evidence を分離する customization checker
- 全 22 JSON 文書を exact SHA-256 / byte size へ束縛する review bundle と verifier
- Compose minimum / Proxmox segmented の 6-phase installation lifecycle contract
- secret-freeな Company DB / Evidence Store の Compose skeleton
- credential を出力しない resolved Compose candidate
- local image の read-only availability preflight
- clean-install / migration evidence candidate contract
- OpenSSH attestation、one-use nonce、checkpoint、supplied chain/store equivalence の検証候補
- Human Decision 前の [Decision Record Candidate](docs/DECISION-RECORD-CANDIDATE.md)、private な [Intent Candidate Instance](docs/INTENT-CANDIDATE-INSTANCE.md)、[Source Record Instance](docs/SOURCE-RECORD-INSTANCE.md) の closed schema 契約
- R31 record / Source Content / access evidence を照合する read-only [Source Binding Verification Candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md)
- 将来の protected runner receipt の field を固定する unpopulated [Protected Source Binding Receipt Candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md)

### 既存実装または local candidate だが、公開保証ではないもの

- Proxmox 上の既存 Voice 処理系と話者別音声処理
- Voice-to-Verified-Handoff contract
- GrillU contract
- Clone Birth prototype
- Company OS vertical slice
- Context Gateway design
- TiDB Context Platform evaluation
- resident agent / OpenClaw integration candidate
- n8n を使う bounded workflow plane

### Public Beta 完成としてまだ証明されていないもの

- Voice Bot の常時 listener と確実な rejoin
- 自然な 900 秒 rotation と 15分 transcript 投稿
- retention 期限内の delete receipt
- 現行 deployed bytes と候補 bytes の parity
- distinct real people を含む 3-persona Voice E2E
- live Compose / Proxmox install、migration、restart、rollback、isolated restore
- protected reconciliation と独立した trust / person separation
- public Discord invite と public Voice Bot
- 対象候補へ束縛された Final Human GO

詳しい最新状態は [STATUS.md](STATUS.md)、公開アクセスまでの未完了 gate は [ROADMAP.md](ROADMAP.md) にあります。

## Public Preview と Public Beta

| | Incomplete Public Preview | Public Beta |
|---|---|---|
| 読める | direction、starter、schema、runbook、candidate tooling | preview の内容に加え、提供対象の利用説明 |
| 試せる | local / synthetic Company pack と validator | scope-matched な利用者体験 |
| Voice | 説明と local candidate の境界のみ | candidate-bound E2E を通過した提供面 |
| Runtime | planning / validation candidate | live receipt と rollback / restore evidence が必要 |
| Access | invite / public Bot なし | 明示された範囲だけを開く |
| GO | `NO_GO_UNPUBLISHED` | independent evidence と Final Human GO 後のみ |

公開 repository があることと、Public Beta access が開いていることは別です。

## 最初に選ぶ

最初はruntimeを起動せず、会社の構造と現在の境界を読むところから始めます。
目的に応じた最短の入口は次のとおりです。

| 目的 | 最初に読む | 次にできること |
|---|---|---|
| Company Template、Blocks、Records、MOCsの関係だけを確認する | [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) | [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)で理想/currentの差分を読む |
| starterを自分の候補へ複製し、localで検査する | [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md) | initializer、customization checker、validator、Review Bundleをread-only/candidate-onlyで実行する |
| runtime候補のprofileを選ぶ | [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md) | `compose_minimum`または`proxmox_segmented`を選び、preflightから始める |

validatorやrunbookの`PASS`は、install、deploy、provider接続、Voice E2E、Promotion、Current Truth、Final Human GOを意味しません。公開面の既定は`NO_GO_UNPUBLISHED`です。迷った場合はruntime profileを選ばず、Catalogから読み始めます。

## Quick Start — Company starter を試す

Python 以外の追加 dependency は不要です。repository root で次を実行します。

```powershell
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
python tools/validate_template_pack.py examples/company-starter
python tools/catalog_company_pack.py examples/company-starter --format markdown
python tools/check_company_pack_public_preview.py examples/company-starter
python tools/check_company_pack_public_preview.py examples/company-starter --format markdown
```

initializer は元 example や既存 target を上書きしません。pack ID と 3 MOC の参照を再束縛し、22 JSON 文書を `draft` に戻してから validator を実行します。

次に [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md) に沿って Human Intent reference、canonical owner、role、expiry、retention、profile を自分の候補へ置き換えます。

複数の確認を一度に再実行する場合は [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) を使えます。既定のJSONは自動処理向け、`--format markdown`は同じ結果を人間が最初に読むための固定サマリーです。どちらも pack の構造、Catalog、customization の分類、false claim の境界だけを read-only で確認します。

```powershell
python tools/check_company_pack_customization.py work/my-company
$BundlePath = 'work/my-company-review-bundle.json'
if (Test-Path -LiteralPath $BundlePath) { throw 'bundle target already exists' }
$BundleJson = python tools/build_company_pack_review_bundle.py work/my-company
if ($LASTEXITCODE -ne 0) { throw 'bundle was refused' }
[IO.File]::WriteAllText(
  $BundlePath,
  $BundleJson + "`n",
  [Text.UTF8Encoding]::new($false)
)
python tools/verify_company_pack_review_bundle.py `
  $BundlePath `
  work/my-company
```

`READY_FOR_GOVERNED_REVIEW` や bundle `MATCH` は、Human approval、execution authority、Promotion、Current Truth、Public Beta GO を意味しません。詳細は [Customization Checklist](docs/CUSTOMIZATION-CHECKLIST.md)、[Review Bundle](docs/REVIEW-BUNDLE.md)、[Review Workflow](docs/REVIEW-WORKFLOW.md) を参照してください。

## Runtime candidate を検査する

Compose minimum / Proxmox segmented の lifecycle contract と公開 skeleton は、次のコマンドで local validation できます。

```powershell
python tools/validate_installation_lifecycle.py `
  examples/installation-lifecycle/compose-minimum.json
python tools/validate_installation_lifecycle.py `
  examples/installation-lifecycle/proxmox-segmented.json
python tools/validate_compose_minimum_skeleton.py runtime/compose-minimum
```

これらは plan/schema/current shipped bytes の検査です。image pull、container 起動、migration、health、restart、backup、restore を実行せず、live receipt も作りません。

- [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)
- [Compose Minimum Runbook](docs/COMPOSE-MINIMUM-RUNBOOK.md)
- [Proxmox Segmented Runbook](docs/PROXMOX-SEGMENTED-RUNBOOK.md)
- [Resolved Compose Candidate](docs/RESOLVED-COMPOSE-CANDIDATE.md)
- [Image Availability Preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md)
- [Clean Install / Migration Evidence Candidate](docs/CLEAN-INSTALL-MIGRATION-EVIDENCE-CANDIDATE.md)

## Evidence tooling の境界

公開している attestation tooling は、段階ごとに証明範囲を限定しています。

| Tooling | 証明できる範囲 | 証明しないもの |
|---|---|---|
| Saved bundle verifier | bundle metadata、digest、current bytes の一致 | Human approval、完全な directory snapshot |
| Source Binding Verification Candidate | 保存済み R31 record / content / access evidence の strict parse、exact binding、terminal reread、非公開 R30 projection digest | full R31 schema、atomic snapshot、locator resolution、authenticity、consent、retention enforcement |
| Protected Source Binding Receipt Candidate | runner、clock、snapshot、locator、evidence、replay、deletion、independent handoff の closed field shape | protected execution、trusted time、signature、person separation、実削除、verified receipt |
| Image availability snapshot verifier | historical self-digest と candidate binding | authenticity、freshness、current daemon state |
| Clean-install evidence verifier | reported evidence の構造と hash binding | 実行の真正性、current runtime |
| Protected attestation verifier | OpenSSH signature と point-in-time policy | trusted clock、canonical trust root、execution truth |
| One-use evaluator | 同じ bound SQLite store 内での atomic nonce reservation | store continuity、外部 authoritative nonce source |
| Signed checkpoint | exact logical snapshot と immediate parent | authoritative full history、parallel branch 不存在 |
| Recursive chain verifier | 提示された path 全体と supplied store の logical equivalence | external anchor authority、actual restore execution |

関連文書:

- [Protected Compose Evidence Attestation](docs/PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)
- [One-Use Compose Attestation Evaluation](docs/ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)
- [Attestation Nonce Store Checkpoint](docs/ATTESTATION-NONCE-STORE-CHECKPOINT.md)
- [Attestation Nonce Store Checkpoint Chain](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)

## Validation

公開 CLI と validator は Python standard library だけで動きます。full contract suite は R29〜R33 の Draft 2020-12 schema を実 validator に通すため、固定した test-only dependency を先に導入します。

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

個別の構造検査、negative case、JSON の安全な出力規則は [Validation Guide](docs/VALIDATION.md) を参照してください。test PASS は、対象になった local bytes と契約の証拠です。Discord、provider、Proxmox、Docker daemon、本番 DB、実 Voice、Public Beta の E2E 証明へ拡張しません。

## Example Company の作り方

1. [Company starter](examples/company-starter/README.md) を initializer で複製する
2. Vision / Mission / Human Intent reference / boundary を編集する
3. canonical owner と runtime profile を決める
4. 必要な Blocks を同じ evidence chain の中で構成する
5. MOC で Company Operations、Public Release、Incident / Recovery の導線を確認する
6. validator と customization checker を実行する
7. exact bytes の review bundle を作る
8. authority を持つ人が、候補と未証明項目を確認する
9. 別の Work Order と runtime evidence を使って activation candidate を作る

starter の placeholder を埋めただけでは、Company の設立、runtime activation、法的権限、Human Decision、Promotion は完了しません。

## Roadmap

現在の優先順位は次です。

1. 公開 Company starter と evidence tooling を、再現可能で正直な preview として保つ
2. exact runtime candidate に対する clean install / migration / restart / rollback / restore evidence を作る
3. consent-bound Voice の listener / rejoin / 900秒 rotation / post / readback / delete を一つの E2E で証明する
4. speaker attribution から Intent / ToDo / Goal / Verified Handoff までを結ぶ
5. distinct real people、protected reconciliation、独立 review を揃える
6. 同じ candidate bytes に Final Human GO を束縛してから、限定された Public Beta access を開く

machine-readable な完了境界ではありません。最新チェックリストは [Roadmap to Public Beta](ROADMAP.md) を参照してください。

## Contribution

現在は Incomplete Public Preview です。Issue や Pull Request を作る前に、次を明確にしてください。

- どの利用者の、どの問題を解く変更か
- Source / Intent / Decision / Work Order chain のどこを扱うか
- 変更候補と、検証方法、rollback は何か
- public artifact に secret、private identifier、実音声、transcript corpus を含めていないか
- local PASS を live / deployed / production / Public GO と表現していないか
- 新しい SSOT を増やさず、既存の canonical owner を尊重しているか

公開 repository の contribution policy と license は整備途中です。大きな導入や再配布を前提にしないでください。

## 用語

| 用語 | 短い定義 |
|---|---|
| Authorized Corpus | 特定 identity が、明示目的・期間・操作で参照を許された情報集合 |
| Intent Candidate | 会話や資料から抽出した、まだ未確定の意図仮説 |
| GrillU | 一問ずつ曖昧さを閉じるチャネル非依存の要件深掘り機能 |
| Work Order | 成果物、対象、権限、受入・停止条件を結ぶ実行契約 |
| Capability Grant | identity と action を resource、期限、上限へ限定した権限記録 |
| Verification Receipt | exact input / candidate / test / result を束縛した追記型記録 |
| Promotion | 検証済み候補を authority-bound decision で採用する段階 |
| Company SSOT | current truth を record、event、authority、source へ遡れる統治体系 |
| MOC | 同じ canonical records を目的別に辿る navigation map |
| Resident Clone | 境界付きで利用者の仕事を担う長期 AI identity candidate |

## Document Map

### 最初に読む

- [Project Status](STATUS.md) — 現在公開しているものと未証明範囲
- [Roadmap to Public Beta](ROADMAP.md) — access を開く前に必要な gate
- [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) — Company Template / Blocks / Records / MOCsの対応
- [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md) — 最短の実行例
- [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) — validator / Catalog / customization境界の一括read-only確認
- [Template Guide](docs/TEMPLATE-GUIDE.md) — Blocks / Records / MOCs の編集
- [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md) — runtime profileを選ぶ前のread-only導線

### Company pack を review する

- [Customization Checklist](docs/CUSTOMIZATION-CHECKLIST.md)
- [Review Bundle](docs/REVIEW-BUNDLE.md)
- [Review Workflow](docs/REVIEW-WORKFLOW.md)
- [Review Evidence to Decision Handoff](docs/REVIEW-DECISION-HANDOFF.md)
- [Validation Guide](docs/VALIDATION.md)
- [Decision Record Candidate Contract](docs/DECISION-RECORD-CANDIDATE.md)
- [Intent Candidate Instance Contract](docs/INTENT-CANDIDATE-INSTANCE.md)
- [Source Record Instance Contract](docs/SOURCE-RECORD-INSTANCE.md)

### Runtime candidate を理解する

- [Runtime overview](runtime/README.md)
- [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)
- [Compose Minimum Runbook](docs/COMPOSE-MINIMUM-RUNBOOK.md)
- [Proxmox Segmented Runbook](docs/PROXMOX-SEGMENTED-RUNBOOK.md)
- [Resolved Compose Candidate](docs/RESOLVED-COMPOSE-CANDIDATE.md)

### Evidence trust boundary を理解する

- [Image Availability Preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md)
- [Clean Install / Migration Evidence Candidate](docs/CLEAN-INSTALL-MIGRATION-EVIDENCE-CANDIDATE.md)
- [Protected Compose Evidence Attestation](docs/PROTECTED-COMPOSE-EVIDENCE-ATTESTATION.md)
- [One-Use Compose Attestation Evaluation](docs/ONE-USE-COMPOSE-ATTESTATION-EVALUATION.md)
- [Attestation Nonce Store Checkpoint](docs/ATTESTATION-NONCE-STORE-CHECKPOINT.md)
- [Attestation Nonce Store Checkpoint Chain](docs/ATTESTATION-NONCE-STORE-CHECKPOINT-CHAIN.md)
- [Source Binding Verification Candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md)
- [Protected Source Binding Receipt Candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md)
- [Protected Execution Request / Handoff Candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) — opaque request shape only; no runner or private evidence
  Schema: `schemas/company-pack-protected-execution-request-handoff-candidate.schema.json`
  Read-only preflight: `tools/validate_company_pack_protected_execution_request_handoff.py`

## Evidence and provenance

この README は、Founder Intent、現行 governance model、公開 Company starter の current bytes、Project Status、Roadmap を、人間が最初に読める projection としてまとめています。README 自体は Human Decision、runtime receipt、canonical Promotion、Current Truth の代替ではありません。

数や機能の主張はこの repository に含まれる current files を基準にしています。local / private 実装に触れる箇所は、公開済み機能ではなく candidate または direction と明記しています。より新しい [STATUS.md](STATUS.md) と candidate-bound receipt がある場合は、そちらの狭い主張を優先してください。

## Current limitations

- Public Discord invite、public Voice Bot、Public Beta signup はありません
- Voice capture、ASR、15分 rotation、post、delete の公開 E2E はありません
- raw audio、transcript corpus、credential、private infrastructure identifier は公開しません
- Company starter は governance candidate であり、会社、契約、権限を自動作成しません
- Compose / Proxmox artifacts は planning / validation candidate であり、live deployment receipt ではありません
- Context Platform、TiDB、GrillU、Resident Clone、Agent Foundry、AI Business Loop は完成済み公開機能ではありません
- attestation tooling は、それぞれ明示した trust boundary を超えて runtime truth を証明しません
- Source Binding の local match は point-in-time candidate であり、protected snapshot、authenticity、consent、retention enforcement を証明しません
- Protected Source Binding Receipt は unpopulated schema-only 契約であり、runner、trusted clock、signature、replay、deletion、independent verification の実行証拠ではありません
- independent protected reconciliation と candidate-bound Final Human GO は未完了です
- Public Beta は **NO-GO / unpublished** のままです

## License

ライセンスはまだ決定していません。明示的な license が追加されるまで、閲覧可能であることは再利用・改変・再配布の許諾を意味しません。
