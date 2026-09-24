# Template Catalog

このディレクトリは、Kotodama Company OSを段階的に再利用するための公開starterです。

| Category | Purpose | Current status |
|---|---|---|
| [Company](company/README.md) | 会社・チーム全体の構造と導入順 | validated JSON governance starter available |
| [Blocks](blocks/README.md) | 小さな実行・判断・検証部品 | Markdown design example |
| [MOCs](mocs/README.md) | 目的別の入口と読み順 | Company / Public Release / Incident & Recovery examples |
| [Records](records/README.md) | Block出力を証拠鎖へ残す記録契約 | 9種のJSON schema-backed starter available |
| [Hierarchy](hierarchy/README.md) | project → phase → requirement → plan → task の候補階層 | A017 re-authored candidate; license/provenance admission blocked |
| [Runtime profiles](company/README.md#runtime-profile-contracts) | Compose minimum / Proxmox segmentedの導入・検証・復旧境界 | [Installation Lifecycle](../docs/INSTALLATION-LIFECYCLE.md)でprofile選択と境界を確認し、sanitized lifecycle contracts and runbooksへ進む |
| [Runtime candidates](../runtime/README.md) | profileをsecret-freeな実行候補へ接続する | Compose data-plane skeleton available; live receipt absent |

## 使う順番

理想のCompany OSでは、次の順番で「会社の境界」から「検証できる仕事」へ
組み立てます。各層は前の層を置き換えず、同じ証拠鎖へ接続します。

| 層 | 理想で決めること | 現在の公開Previewでできること |
|---|---|---|
| Company Template | Vision、Boundary、owner、profile、採用する能力 | `examples/company-starter`を作業copyへ複製し、組織固有の候補へ編集 |
| Hierarchy | project、phase、requirement、plan、taskの親子関係と証拠・rollback境界 | [A017 hierarchy candidate](hierarchy/README.md)をcopyし、標準ライブラリvalidatorで検査。Issue #25の解決まではadmission不可 |
| Blocks | 入力・出力、authority、拒否条件、verification、rollback | 9 Blockの設計とschema/validatorを読み、flow接続を検査 |
| Governed Records | Block出力の必須field、canonical owner、保持・検証境界 | 9種のJSON-backed Record契約を確認し、候補bytesを検証 |
| MOCs | 目的別の入口と読み順。新しい正本や権限は作らない | Company Operations / Public Release / Incident & Recoveryをread-onlyで辿る |
| Runtime profile | Compose/Proxmox境界、activation、recovery、停止条件 | lifecycle runbookとsecret-freeな実行候補を読む。live runtimeは含まない |

迷ったら、まずCompany Templateの境界を編集し、次に必要なBlockだけを
選び、対応するRecordを確認し、MOCで目的に合う読み順を選びます。その後、
  [Catalog](../docs/COMPANY-PACK-CATALOG.md)、validator、customization checker、guided planner、Review Bundleの
順に候補を狭めます。`MATCH`やvalidator `PASS`は、Human Decision、権限付与、
Promotion、Current Truth、runtime activation、Public Beta GOを意味しません。

## Read next: ideal -> current -> smoke

- **Ideal:** [Company Template](company/README.md)で会社の境界を決め、
  [Blocks](blocks/README.md)、[Governed Records](records/README.md)、
  [MOCs](mocs/README.md)の役割と読み順を確認する。
- **Current:** [Company Pack Catalog](../docs/COMPANY-PACK-CATALOG.md)で
  公開starterの実際のBlock・Record・MOC対応を一覧し、
  [Company Pack Guided Next Steps](../docs/COMPANY-PACK-NEXT-STEPS.md)で
  現在地と次の一手を確認してから、
  [Schema / Validator / Test Matrix](../docs/SCHEMA-VALIDATOR-MATRIX.md)で
  契約・validator・回帰testの対応を確認する。
- **Smoke:** [Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md)の作業copy手順と
  [Public Preview Self-check](../docs/PUBLIC-PREVIEW-SELF-CHECK.md)を外部接続なしで
  実行する。

この入口は`read-only/candidate-only`です。Catalog、validator、smokeのPASSや
MATCHは承認、runtime activation、Promotion、Current Truthを作らず、公開状態は
常に`NO_GO_UNPUBLISHED`です。

## MOCを目的で選ぶ

MOCは、同じCompany governance chainを目的別に読み始めるための地図です。
公開starterでは、次の3つのMarkdown例を用途で選べます。

| MOC | 使うとき | shipped example |
|---|---|---|
| Company Operations | Source IntakeからPromotion Decisionまで全体を読む | [Company Operations MOC](mocs/company-operations-moc.md) |
| Public Release Review | 公開候補のDecision、Work、検証、Promotion候補を確認する | [Public Release Review MOC](mocs/public-release-moc.md) |
| Incident / Recovery | boundedな停止・変更・検証の部分列を読む | [Incident / Recovery MOC](mocs/incident-recovery-moc.md) |

3つとも同じcanonical flow（same canonical flow）を辿る
`navigation-only` projectionです。MOCが新しいSSOT、実行権限、Promotion、
Current Truthを作ることはありません。`Voice Operations`や`Venture /
Customer Discovery`は理想・将来候補であり、公開starterのshipped MOCでは
ありません。公開previewの状態は常に`NO_GO_UNPUBLISHED`です。

## 最短の確認手順

Template Catalogから初めて試す場合は、まず公開starterを変更せずに一覧し、
次に上書きしない作業copyを作ってから、customization、Catalog、validatorの
順で確認します。すべてlocal / syntheticな候補操作です。既存のtargetを上書きしません。

### Quick Start: immutable example -> generated candidate

The shipped `examples/company-starter` directory is the **immutable published baseline**.
Inspect that baseline separately, then keep every follow-up check on the
generated `work/my-company` candidate.

~~~powershell
python tools/catalog_company_pack.py examples/company-starter --format markdown
python tools/check_company_pack_public_preview.py examples/company-starter --format markdown
python tools/validate_template_pack.py examples/company-starter
New-Item -ItemType Directory -Force work | Out-Null
python tools/create_company_pack.py my-company work/my-company
python tools/check_company_pack_customization.py work/my-company
python tools/validate_template_pack.py work/my-company
python tools/catalog_company_pack.py work/my-company --format markdown
python tools/check_company_pack_public_preview.py work/my-company --format markdown
python tools/plan_company_pack_next_steps.py work/my-company --format markdown
~~~

~~~bash
python3 tools/catalog_company_pack.py examples/company-starter --format markdown
python3 tools/check_company_pack_public_preview.py examples/company-starter --format markdown
python3 tools/validate_template_pack.py examples/company-starter
mkdir -p work
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/check_company_pack_customization.py work/my-company
python3 tools/validate_template_pack.py work/my-company
python3 tools/catalog_company_pack.py work/my-company --format markdown
python3 tools/check_company_pack_public_preview.py work/my-company --format markdown
python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown
~~~

各コマンドの詳しい入力・出力と、次のreview候補は [Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md) を参照してください。
[Public Preview Self-check](../docs/PUBLIC-PREVIEW-SELF-CHECK.md) は同じ候補を
validator、Catalog、customization、false-claim境界の一つのread-only結果へ
まとめます。`PASS`や`MATCH`は承認、runtime activation、Promotion、Current
Truth、Final Human GOを作らず、公開状態は常に`NO_GO_UNPUBLISHED`です。

## Planned catalog

```text
templates/
  human-intent/
  decision/
  work-order/
  capability-grant/
  verification-receipt/
  promotion/
  discord/
  voice/
  clone-birth/
  agent-foundry/
  venture/
  proxmox/
  n8n/
```

上記のplanned directoryは、schema、validator、test、runbookが揃ってから順次追加します。現在存在しないdirectoryを実装済みとは扱いません。

詳しい考え方は[テンプレート利用ガイド](../docs/TEMPLATE-GUIDE.md)を参照してください。

## 理想と現在

理想のCompany OSでは、Company Templateを複製してHuman Intent、Block、
Governed Record、MOC、runtime profile、adapterを組織の境界へ合わせます。
現在の公開面では、Company starterを作業copyへ複製し、Catalog・validator・
customization checker・guided plannerで構造と残件を確認するところまでを
read-only/candidate-onlyで試せます。

実際にvalidatorへ通せるJSON packは[Company starter example](../examples/company-starter/README.md)にあります。上記Markdown例そのものをvalidator済みと読み替えないでください。

MOCの入口例:

- [Company Operations](mocs/company-operations-moc.md): governance chain全体
- [Public Release Review](mocs/public-release-moc.md): 公開候補のDecisionからPromotion Decisionまで
- [Incident / Recovery](mocs/incident-recovery-moc.md): bounded recovery candidateとreceipt

3つともnavigation-onlyです。別のSSOT、実行権限、公開GOを作りません。

最短の導入手順は[Starter Walkthrough](../docs/STARTER-WALKTHROUGH.md)にあります。`tools/create_company_pack.py`を使うと、元exampleと既存targetを上書きせず、pack IDとMOC参照を再束縛し、22文書を`draft`にして検証できます。3つのoptionをall-or-noneで指定する[guided initializer](../docs/GUIDED-COMPANY-PACK-INITIALIZATION.md)は、公開starterの19静的fieldを手編集せずに閉じます。続く[`check_company_pack_customization.py`](../tools/check_company_pack_customization.py)は、placeholder置換、governed review、別途必要なevidenceを混同せず列挙します。公開starterの`19/46/5`は例示値であり、別Packではcheckerとsaved reportの実数を使います。[Public Preview Self-check](../docs/PUBLIC-PREVIEW-SELF-CHECK.md)はvalidator、Catalog、customization、false-claim境界を一つのread-only結果へまとめます。[guided planner](../docs/COMPANY-PACK-NEXT-STEPS.md)は同じreportを現在地・理想flow・分類別件数・次コマンドへ集約します。placeholderを閉じた候補は[`build_company_pack_review_bundle.py`](../tools/build_company_pack_review_bundle.py)でexact SHA-256 / byte sizeへ固定し、[`verify_company_pack_review_bundle.py`](../tools/verify_company_pack_review_bundle.py)で再照合できますが、MATCH自体はapprovalではありません。

保存したbundleから先は、[Review Request](../docs/REVIEW-REQUEST.md) →
[Review Response](../docs/REVIEW-RESPONSE.md) →
[Decision Handoff](../docs/REVIEW-DECISION-HANDOFF.md)の順で、Pack固有の
件数を再入力せずcandidateへ束縛できます。これらはレビューの入力形と
readbackを整える契約であり、Human Decision、Promotion、Current Truth、
runtime、Public Beta GOを生成しません。
