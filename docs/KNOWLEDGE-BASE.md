# Kotodama ナレッジベース

Kotodama のナレッジベースは、リポジトリ内外の正本を置き換える Wiki ではありません。人とエージェントが、同じ公開可能な知識を段階的に読み、出典・鮮度・矛盾・担当・Goal/KGIとの関係まで辿れるようにする、**再構築可能な読取投影**です。

入口は [`knowledge/index.md`](../knowledge/index.md) です。形式は Open Knowledge Format（OKF）v0.2 の Markdown＋YAML frontmatter を採用し、その上に Kotodama 固有の安全・運用プロファイルを追加しています。

## Goal

人とエージェントが、同じ正しい情報を必要な範囲で参照し、元の意図・現在位置・担当・制約・根拠・未解決・次の行動を失わずに仕事を進められる状態をつくります。

ナレッジベース単体の目的は「文書数を増やすこと」ではなく、次の経路を成立させることです。

```text
権限のある一次情報
  → 出典付きの知識候補
  → 独立レビュー
  → 人・エージェント向けの索引と関係グラフ
  → Task/Sessionに必要な限定コンテキスト
  → 実際の成果と修正
  → 影響範囲だけ再構築
```

## 現在の状態

この実装で追加されるもの：

- OKF v0.2形式の公開安全な知識バンドル
- Goal、現在地、KGI/KPI、権限境界、ライフサイクル、担当、更新、検索、コンテキストの初期Concept
- 出典、生成者、検証者、鮮度期限、知識状態、Goal/KGI/initiative参照を持つKotodamaプロファイル
- Markdown/YAML、出典、リンク、脚注、ID、分類、自己検証、孤立Conceptを検査するCLI
- deterministicな `catalog.json` と `graph.json`
- 透明な字句検索と、Goal/KGI/initiativeを入力にした限定コンテキスト生成
- CIでの検証と生成物の差分検査

この実装だけでは成立しないもの：

- Human Intent、Task、Decision、Current Truth、ACLの第二正本
- private/internal/restricted/secret情報の公開リポジトリへの取り込み
- logical roleを実行主体へ束縛するruntime identity、grant、lease、work order
- private sourceの自動巡回、ACL取消の全派生先への実伝播
- embedding、vector DB、rerankerの採用または性能達成
- Public Beta、公開、production deployment、Human GO

したがって、初期Conceptは `draft` / `candidate` / `projection_only` です。構造検証に成功しても、内容が人間確認済みになったとは扱いません。

## 情報モデル

### OKF標準フィールド

各ConceptはMarkdown本文とYAML frontmatterを持ちます。

- `type`：Conceptの種類
- `title` / `description` / `tags`：人とエージェント向けの発見情報
- `sources`：由来となる一次情報・資料
- `generated`：現在の内容を生成した主体と時刻
- `verified`：生成者とは別の検証主体と時刻
- `status`：`draft` / `stable` / `deprecated`
- `stale_after`：この時刻以降は再確認が必要となる絶対時刻

### Kotodama拡張

`kotodama` frontmatterは次を保持します。

- `id`：ファイルパスと一致する安定Concept ID
- `classification`：公開バンドルでは `public_candidate` のみ
- `authority`：常に `projection_only`
- `knowledge_state`：`candidate` / `confirmed` / `conflicted` / `unknown` / `deprecated` / `revoked`
- `owner_role` / `reviewer_role`：整備責任と独立レビューを分離
- `goal_refs` / `kgi_refs` / `initiative_refs`：作業目的への追跡経路
- `context_priority`：限定コンテキストでの優先度
- `agent_use`：発見可能性、出典を開く必要、decision/runtime authorityを持たないこと

`status` は文書のライフサイクル、`knowledge_state` は知識の確からしさ・扱いです。古いConceptが即座に誤りになるわけではありませんが、重要な古いConceptを「ready」として黙って注入しません。

## 正本と投影の分離

| 対象 | 正本または決定主体 | ナレッジベースの役割 |
|---|---|---|
| 人の意図・訂正 | 既存Human Intent authority | 出典付きに要約し、正本へ戻れるようにする |
| Task状態 | 既存Task record/event ledger | 現在位置へのリンクを持つ。Task状態を複製しない |
| Decision / Current Truth | 既存decision・promotion経路 | 候補・根拠・競合を表示する。自己昇格しない |
| ACL / reader / reviewer | 既存access policy authority | 現在の許可を前提に取得する。権限を付与しない |
| 実行権限 | work order / grant / lease | 参照情報を返すだけで、実行を許可しない |
| catalog / graph / search | Conceptから再生成 | 発見と探索を助ける。内容の正しさを決めない |

## エージェント構成

### AI-LIBRARIAN

出典の版、Concept、リンク、索引、鮮度、矛盾、失効、検索評価を管理します。必要時に取込、ページ整備、索引、評価を子作業へ分けられますが、親が統合結果に責任を持ちます。

### AI-AUDITOR

生成者・実装者とは別のruntime主体として、原資料との一致、失われた制約、分類、競合、ライフサイクル、代替手法を確認します。自己検証や未実行をPASSにしません。

### AI-CHIEF

既存owner、Goal/KGI、優先順位、依存、重要な通知先を解決します。知識の編集担当と権限決定主体を混同しません。

### AI-BUILDER / AI-ANALYST

Builderは限定されたparser、projection、test、repairを実装します。Analystは検索品質、fresh-sessionでの修正率、proxyと実成果の関係、費用・遅延・副作用を測ります。

これらはlogical contractです。名前が存在するだけではagentが起動、常駐、認証、権限取得したことになりません。

## 監査指標

```bash
python tools/knowledge_base.py audit --root . --format markdown
```

現在のCLIは次を報告します。

- Concept数、error数、warning数
- 出典coverage
- freshness coverage
- 独立verification coverage
- human review coverage
- structural retrieval eligibility（構造上取得できる割合。decision readinessではない）
- orphan、missing source、broken link、stale、conflict件数

これらは制御指標です。値が高くても、元の依頼が達成されたことや `KGI-INTENT` が達成されたことを単独では証明しません。

### 候補KGI

以下は運用候補であり、現時点の正式な数値目標ではありません。

1. 必須知識ready率：active workに必要なConceptが出典付き・fresh・閲覧可能・独立確認済みである割合
2. 修正伝播率：訂正・失効後に影響投影がSLA内で無効化・再構築された割合
3. fresh-session復元率：別Sessionで、文脈欠落による重大修正なしに仕事を再開できた割合
4. grounded retrieval成功率：評価質問の必須Conceptと一次情報がcontext budget内に入る割合

正式採用には、owner、母数、計測元、baseline、target、deadline、anti-gaming guardが必要です。

## CLI

### 構造・安全境界を検証

```bash
python tools/knowledge_base.py validate --root .
```

出力は次の3判定を混同しません。

- `OKF_CONFORMANT`：OKF v0.2の最小conformance（parse可能なfrontmatter、非空`type`、reserved file構造）
- `KOTODAMA_PROFILE_PASS`：出典、公開分類、owner/reviewer分離、link/source等を含むKotodama producer policy
- `DECISION_READY`：`validate`では常に`NOT_EVALUATED`。actorとpurposeを明示した別auditが必要

OKF v0.2では`type`だけが常時必須で、optional field、未知type、broken cross-link、missing indexだけを理由に非準拠とはしません。Kotodamaのより厳しい拒否はprofile判定にだけ反映します。

```bash
python tools/knowledge_base.py validate --root . --json
python tools/knowledge_base.py readiness \
  --root . \
  --actor human:reviewer \
  --purpose "review project direction" \
  --concept project/goal \
  --format markdown
```

`readiness`は文書のstable/confirmed/verification/source/freshnessを検査しますが、accessやdecision authorityを付与できません。現行public candidateにはauthoritativeなactor/purpose access resolverがないため、解決されるまでは`NEEDS_RESOLUTION`を返します。

監査JSONはこの指標名変更に伴い`schema_revision: v2`です。旧`retrieval_readiness_ratio`は意味が強すぎるため互換aliasを残さず、`structural_retrieval_eligibility_ratio`へ置き換えています。

検査対象：

- OKF frontmatterと必須 `type`
- Kotodama profile/schema
- Concept IDとファイルパスの一致
- 公開バンドルの分類
- owner/reviewerの分離と自己検証
- repository内sourceの存在とpath traversal
- Conceptリンク、index、脚注とsource ID
- 孤立Concept
- stale、conflict、unknown、unverifiedの可視化

### deterministic projectionを生成・確認

```bash
python tools/knowledge_base.py build --root .
python tools/knowledge_base.py build --root . --check
```

`catalog.json` はConceptの発見用metadata、`graph.json` はConcept、source、Goal、KGI、initiativeの関係を保持します。どちらも再生成でき、authorityは持ちません。

### 検索

```bash
python tools/knowledge_base.py query --root . "意図 KGI"
python tools/knowledge_base.py query --root . "失効 更新" --json
```

初期実装は説明可能な字句検索です。vector検索を採用する前のbaselineとして使います。順位理由、trust、state、freshness、sourceを一緒に返します。

### 限定コンテキスト

```bash
python tools/knowledge_base.py context \
  --root . \
  --goal OUT-INTENT \
  --initiative INIT-KNOWLEDGE-REFRESH \
  --max-concepts 8
```

Goal/KGI/initiative/tagに直接接続したConceptと必須governanceを、profileの上限内で返します。stale critical、conflicted、unknown、deprecated、revoked、非公開Conceptはready contextへ入れず、`needs_resolution`として示します。

## 更新手順

1. 既存の正本・担当・classification・現在のrevisionを確認する。
2. `knowledge/` 内の影響Conceptだけを更新する。
3. `sources`、本文のsource footnote、`generated.at`、`stale_after`を揃える。
4. 意味が未確認なら `candidate` または `unknown`、競合があれば `conflicted` にする。
5. `knowledge/log.md` に更新理由を残す。
6. `validate`、`build`、`build --check`、対象query/contextのreadbackを行う。
7. 別のauditorが原資料と出力を確認する。
8. Current Truthやruntimeへ反映する場合は、ナレッジベース外の既存promotion/authority経路を使う。

## フェーズ

### Phase 1：Repository knowledge foundation（今回）

OKF bundle、profile、初期Concept、catalog/graph、audit/query/context、CIを追加します。

### Phase 2：実データの棚卸しとsource registry接続

既存Source、Decision、Task、Session、Evidenceの安定IDとrevisionをConceptへ接続し、二重正本を作らずに影響関係を解決します。

### Phase 3：評価セットと実検索品質

実際の authorized taskからrequired/forbidden concept fixtureを作り、字句、graph、embedding、rerankerを同じ条件で比較します。

### Phase 4：差分取込・失効伝播

source revision、訂正、ACL loss、削除、Decision変更をeventとして受け、影響Concept・index・contextだけをstale化・再構築します。

### Phase 5：runtime context gateway統合

Task/Session/role/grantに応じたcontextを一つの窓口から配信し、表示版・agent入力版・source digest・実行結果を対応させます。

### Phase 6：継続最適化

retrieval品質、実成果、費用、遅延、調整負担、安全性を監査し、better methodをbounded trialとrollback付きで採用します。

## CI

既存のRepository validationに次を追加します。

```bash
python tools/knowledge_base.py validate --root .
python tools/knowledge_base.py build --root . --check
```

加えて `tests/test_knowledge_base.py` が、公開分類、authority境界、deterministic output、query、bounded context、stale criticalの拒否を検証します。
