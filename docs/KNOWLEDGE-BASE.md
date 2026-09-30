# Kotodama Knowledge Base

> Status: **candidate-only design and control-plane contract**  
> Machine-readable owner: [`../governance/knowledge-registry.json`](../governance/knowledge-registry.json)

Kotodama の Knowledge Base は「大量の Markdown や RAG 用チャンクを置く場所」ではありません。

目的は、**人間と Agent が、その仕事に必要な正しい情報へ、正本・由来・鮮度・権限・競合状態を失わず到達できること**です。

## 1. Knowledge の基本モデル

```text
Raw Source / Source Evidence
  ↓
Candidate interpretation
  ↓
Provenance / freshness / authority / contradiction check
  ↓
Verified candidate
  ↓
Authorized Promotion
  ↓
Canonical Current Truth
  ↓
Projection / Context bundle / Search index
```

重要なのは、検索で見つかった文章と Current Truth を同一視しないことです。

- **Source Evidence** — 発言、Issue、文書、test、runtime observation などの元証拠
- **Candidate** — Source から導いた解釈・要約・構造化候補
- **Canonical owner** — その fact family の現在の正本を持つ唯一の場所
- **Projection** — README、Discord、dashboard、検索 index など、人間/Agent向けの見え方
- **Current Truth** — authority を持つ Promotion を経て採用された状態

Projection は便利ですが、正本を置き換えません。

## 2. Fact family

知識をファイル単位だけで管理すると、同じ意味の情報が README、STATUS、Issue、DB、Discord に増殖します。

そこで Kotodama では **fact family** を単位にします。

初期 registry では少なくとも以下を分離します。

- project goal / KGI / phases
- current public state
- Public Beta execution sequence
- public orientation
- knowledge operations
- agent portfolio
- audit policy
- governance contracts / templates
- documentation / runbooks
- runtime candidates
- implementation tools
- verification suite
- examples / fixtures
- repository configuration

各 family は次を持ちます。

```text
id
canonical_path
human_projection_paths
classification_patterns
freshness policy
owner role
required provenance
```

これにより「どこを直せば正しいのか」と「どこは projection なのか」を Agent も判断できます。

## 3. Canonical owner のルール

### One canonical owner per fact family

同じ fact family に競合する正本を増やしません。

例:

- Strategic Goal/KGI → `governance/okf.json`
- Current public reality → `STATUS.md`
- Public Beta implementation sequence → `ROADMAP.md`
- Agent portfolio → `governance/agent-registry.json`

README は重要な入口ですが、すべての情報の SSOT にはしません。

### Canonical source を Agent が勝手に上書きしない

Knowledge Curator は、

- stale finding
- contradiction finding
- missing provenance
- candidate patch

を作れます。

しかし、authority が必要な fact の Promotion や Current Truth 更新は別 gate です。

## 4. Provenance

将来的な知識 record は、最低限次を保持します。

```text
fact_family
source / source_revision
observed_at
producer
interpretation_method
authority
status
valid_from / expires_at
supersedes
conflicts_with
sensitivity / audience
verification_receipt
promotion_decision
```

RAG の chunk でも、この provenance を落とさないことを原則にします。

「LLM が要約したから provenance が消えた」は許容しません。

## 5. Freshness

正しい情報でも古ければ危険です。

初期 P0 では deterministic に確認できるところから始めます。

- `governance/*.json` → `reviewed_at`
- `STATUS.md` → `Updated:`
- manual-only family → stale を自動断定しない

freshness SLA を超えた場合は、まず **finding** です。

```text
stale detected
  ↓
canonical source / supporting evidence を確認
  ↓
更新候補を作る
  ↓
必要なら authorized review
  ↓
canonical update
```

古いという理由だけで Agent が内容を推測して書き換えません。

## 6. Contradiction

特に危険なのは、複数の source が違うことを言っている状態です。

Severity-1 の例:

- evidence なしに Public Beta / Voice / runtime が live と書かれる
- 同じ fact family に複数の canonical owner がある
- revoke 済みの consent / authority を active と扱う

この場合:

1. Promotion を止める
2. 競合 source を両方保持する
3. contradiction finding を作る
4. authority を持つ人 / policy に解決を handoff する
5. 解決 receipt を残す

**Knowledge Curator は severity-1 contradiction を自動解決しません。**

## 7. Context Compiler

Agent に「全データ」を毎回渡すことは、正確性にも cost にも不利です。

Context Compiler は task ごとに bounded context を作ります。

```text
Task / Work Order
  ↓
required fact families
  ↓
permission / sensitivity filter
  ↓
canonical source
  + relevant Source Evidence
  + competing candidates
  + freshness
  + constraints
  ↓
Bounded Context Bundle
```

Context bundle の原則:

- canonical source を識別できる
- source revision を持つ
- stale / candidate / contradiction を隠さない
- permission を超えたデータを入れない
- task に不要な履歴を無制限に追加しない
- generated summary から原典へ戻れる

## 8. Repository inventory

P0 では repository 自体を最初の Knowledge corpus として扱います。

```bash
python tools/audit_control_plane.py --format markdown
```

監査は read-only で、

- repository の全ファイル
- classification patterns
- fact family
- canonical owner
- freshness

を照合します。

`governance/knowledge-registry.json` では **98%以上の classification coverage** を P0 gate とします。

新しいファイルを追加したのにどの knowledge family に属するか不明な場合、CI が gap を発見できるようにします。

## 9. Agent による Knowledge 整備

### Knowledge Curator

担当:

- stale detection
- duplicate / near-duplicate detection
- contradiction detection
- missing provenance detection
- broken projection / link detection
- candidate canonical patch
- candidate context index update

### Evidence Auditor

Knowledge Curator の結論もそのまま信用しません。

- 根拠と claim が一致するか
- local candidate を live と呼んでいないか
- verification receipt が本当に対象 bytes / revision に束縛されているか

を独立に確認します。

### Quality Red Team

意図的に難しいケースを作ります。

- 古い情報と新しい情報を同時に与える
- canonical と candidate を混ぜる
- authority のない source を入れる
-同名の Agent / document / version を入れる

それでも Context Compiler / Knowledge Curator が正しい境界を維持できるか評価します。

## 10. P1 で追加するもの

P0 は registry と deterministic inventory です。P1 では実際の Knowledge Platform へ進みます。

- source digest / revision binding
- semantic duplicate detector
- contradiction candidate detector
- freshness receipt
- fact-level provenance graph
- sensitivity / permission model
- bounded context bundle schema
- retrieval eval
- correction feedback
- Current Truth promotion binding

その後に DB / vector / graph / full-text の実装を選びます。

**ストレージ製品を先に SSOT と決めない**ことが重要です。契約と fact ownership を先に固定し、その後ろに交換可能な adapter を置きます。

## 11. 成功条件

Knowledge Base の成功は「文書数」や「embedding 数」ではありません。

- KGI-03 Knowledge reliability
- KGI-05 Human structuring load
- contradiction escape rate
- stale fact family ratio
- retrieval correction rate
- context token / byte volume

で測ります。

最終的には、人間が「どのファイルが最新だっけ」と探し回らず、Agent も古い情報を自信満々に使わない状態を作ります。
