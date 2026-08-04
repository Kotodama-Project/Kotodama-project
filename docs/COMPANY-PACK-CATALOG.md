# Company Pack Catalog

Company Pack Catalogは、KotodamaのCompany Template packを読むための
read-only navigation projectionです。manifest、9 Blocks、9 Governed Records、
3 MOCsの関係を、機械可読JSONまたは短いMarkdownで一覧できます。

Catalogは、テンプレートを使い始める人が次の3つを同じ順序で確認できるように
します。

1. どのBlockを、どの順序で読むか
2. 各Blockの入力・出力と対応するRecord artifactは何か
3. Company Operations、Public Release Review、Incident / Recoveryの各MOCが
   canonical flowのどの位置を辿るか

## Read next: ideal -> current -> smoke

- **Ideal:** [Company Template](../templates/company/README.md)で会社の境界を
  定め、[Blocks](../templates/blocks/README.md)と[Governed Records](../templates/records/README.md)
  で仕事と証拠の形を選び、[MOCs](../templates/mocs/README.md)で目的に合う
  読み順を選びます。
- **Current:** [Company starter](../examples/company-starter/README.md)とこの
  Catalogで、公開Packに実際に同梱されたBlock・Record・MOC・flow位置を
  read-onlyで一覧します。
- **Smoke:** [Schema / Validator / Test Matrix](SCHEMA-VALIDATOR-MATRIX.md)と
  [Starter Walkthrough](STARTER-WALKTHROUGH.md)の外部接続なしRunbook smoke、
  および[Catalog entry regression](../tests/test_company_pack_catalog_entry_navigation.py)
  で、この導線と構造境界を確認します。repository rootから
  `python -m pytest tests/test_company_pack_catalog_entry_navigation.py -q`を
  実行できます。

この入口は`read-only/candidate-only`、`NO_GO_UNPUBLISHED`です。Catalog、
validator、smokeのPASSは、runtime起動、Human approval、Promotion、Current
Truth、Public Beta GOを作りません。

## 最初に選ぶ

初めてCompany Templateを読む場合は、runtimeを起動せず、次の順番で
確認します。

1. **Company Pack Catalog**でCompany Template、Blocks、Governed Records、
   MOCsの対応と、現在のPack構造を一覧する。
2. [Starter Walkthrough](STARTER-WALKTHROUGH.md)で、理想の使い方と現在の
   local / synthetic、read-only/candidate-onlyの境界を確認する。
3. 実行環境の候補が必要な場合だけ、[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)
   で`compose_minimum`または`proxmox_segmented`のprofileを選ぶ。

この順序はnavigationの案内であり、install、deploy、provider接続、Voice /
Discord E2E、Promotion、Current Truth、Final Human GOを実行しません。Catalog
やvalidatorのPASSは構造を読めたという意味だけで、公開アクセスは常に
`NO_GO_UNPUBLISHED`です。

## Runbook smoke

Catalogから導入順そのものを確認したい場合は、外部接続なしの一時
directoryで実行する [Schema / Validator / Test Matrix](SCHEMA-VALIDATOR-MATRIX.md)
のRunbook smokeと、対応する
[test_public_starter_runbook_smoke.py](../tests/test_public_starter_runbook_smoke.py)
を使います。

repository rootから次を実行できます。

~~~powershell
python -m pytest tests/test_public_starter_runbook_smoke.py -q
~~~

~~~bash
python3 -m pytest tests/test_public_starter_runbook_smoke.py -q
~~~

このsmokeは、guided pathでは
`CANDIDATE_FOR_GOVERNED_REVIEW`から保存済みbundleの`MATCH`までを、plain
pathでは`CUSTOMIZATION_REQUIRED`を`BUNDLE_REFUSED`として停止する境界を
確認します。plain pathの拒否結果を成功bundleとして保存したり、Human approval、
runtime、Promotion、Current Truthを作ったりしません。どちらも
`read-only/candidate-only`であり、公開状態は`NO_GO_UNPUBLISHED`です。

## Template層への直接リンク

Catalogから詳細へ移動するときは、次の順で層を辿ります。これは同じ
Company governance chainを読むためのnavigation-only導線であり、各リンク先の
starterやREADMEが新しいSSOT、実行権限、Promotion、Current Truthを作ることは
ありません。

| 層 | 何を読むか | 直接リンク |
|---|---|---|
| Company Template | 会社の境界、owner、profile、導入順 | [Company Template](../templates/company/README.md) |
| Blocks | 入力・出力・authority・verificationの小さな部品 | [Blocks](../templates/blocks/README.md) |
| Governed Records | Block出力を証拠鎖へ残すRecord契約 | [Governed Records](../templates/records/README.md) |
| MOCs | 目的別の読み順と入口 | [MOCs](../templates/mocs/README.md) |
| 実例 | 9 Blocks・9 Records・3 MOCsのJSON starter | [Company starter](../examples/company-starter/README.md) |

詳細な使い方と現在の境界は、[Template Guide](TEMPLATE-GUIDE.md) →
[Starter Walkthrough](STARTER-WALKTHROUGH.md) → [Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md)
の順に確認します。runtime profileを比較する必要がある場合だけ、最後に
[Installation Lifecycle](INSTALLATION-LIFECYCLE.md)を読みます。全リンクは
read-only/candidate-onlyの公開previewを案内し、状態は常に
`NO_GO_UNPUBLISHED`です。

## Quick start

repository rootから、公開exampleをそのまま表示します。

~~~powershell
python tools/catalog_company_pack.py examples/company-starter
python tools/catalog_company_pack.py examples/company-starter --format markdown
~~~

~~~bash
python3 tools/catalog_company_pack.py examples/company-starter
python3 tools/catalog_company_pack.py examples/company-starter --format markdown
~~~

JSONが自動処理向け、Markdownが人間の最初の確認向けです。両方とも同じ
pack bytesから決定的に生成され、pack自身へ書き込みません。

作業copyを作った後は、対象を指定します。

~~~powershell
python tools/create_company_pack.py my-company work/my-company
python tools/catalog_company_pack.py work/my-company --format markdown
python tools/validate_template_pack.py work/my-company
~~~

~~~bash
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/catalog_company_pack.py work/my-company --format markdown
python3 tools/validate_template_pack.py work/my-company
~~~

先にvalidatorを通す必要はありません。Catalogは内部で同じ構造validatorを
実行し、PASSでないpackを安全に空のINVALID_PACKとして返します。privateな
manifest id、locator、エラー本文は無効出力へ再掲しません。

## JSONの読み方

トップレベルには、次の境界付き情報だけが含まれます。

| Field | 意味 |
| --- | --- |
| kind / version | Catalog契約の識別子 |
| status | 構造検証が通ったPASS、またはINVALID_PACK |
| pack_id / profiles | manifestから読み取った候補packの識別子とprofile |
| counts / validation | Block、Record、MOC、validator対象数とエラー件数 |
| flow | canonical sequenceの1-based位置、目的、入出力、Record artifact |
| blocks | Blockのpath、authority境界、denied actions、receipt要件 |
| records | artifact、canonical owner、creator/verifier、retention policy参照 |
| mocs | navigation-only MOC、projection、参照、flow位置 |
| claims | Catalogが意図的に作らない5つの主張 |
| public_beta | 常にNO_GO_UNPUBLISHED |

claimsの5項目は常にfalseです。特に次をtrueにする機能はこのCLIの責務外です。

- Catalog自体をCompany SSOTにする
- Human approvalやCapability Grantを検証済みとする
- runtimeやprovider E2Eを検証済みとする
- Promotionを実行・承認済みとする
- Current Truthを書き換える

## MOCの位置の意味

primary MOCであるCompany Operationsはcanonical flowの1から9を示します。
secondary MOCは同じBlock鎖の部分列です。manifest idはpack入口として位置1へ
投影し、重複する位置は一度だけ表示します。したがって、Public Release Review
やIncident / Recoveryは、新しい実行フローや別SSOTを作らず、既存の読み順の
どこから入るかを示します。

CatalogのMOC行は、MOCのauthorityがnavigation_onlyであることを保持します。
目的別のMOCに実行権限、monitor、復旧済みCurrent Truthを追加するには、別の
governed Work OrderとVerification Receiptが必要です。

## 現在と理想の分離

理想のCompany OSでは、CatalogのflowをSource EvidenceからIntent Candidate、
Decision、Work Order、Change Candidate、Verification Receipt、Promotion、
Current Truthへ接続します。しかし、公開starterとこのCLIが示すのは、その
構造と参照だけです。

実際に試せる現在の範囲は、次のとおりです。

- exampleまたは自分の作業copyをローカルで一覧する
- Block / Record / MOCの対応を確認する
- validator、customization checker、guided planner、review bundleへ進む
- exact candidate bytesを後続のreviewへ渡す

次の状態はCatalogからは導出できません。

- Human Intent、Decision、Work Orderの承認
- 実際の権限付与、外部provider接続、Voice / Discord E2E
- Compose / Proxmoxの起動、restart、restore、削除receipt
- Promotion、Current Truth、Final Human GO
- Public Beta accessや公開Discord invite

したがって、CatalogのPASSは「構造を読み取れた」という意味だけです。
Public Betaは、このリポジトリの他のcandidateと同じくNO_GO_UNPUBLISHEDです。

## 失敗時の扱い

packが不正な場合は、終了code 1、status INVALID_PACK、空のflow / blocks /
records / mocsを返します。validationには検証済みファイル数とエラー件数だけを
残し、secretらしい値やprivate locatorを標準出力へ出しません。usage errorは
終了code 2で、Catalog JSONを出力しません。

JSON Schemaはschemas/company-pack-catalog.schema.jsonです。出力を保存して
別ツールへ渡す場合は、Draft 2020-12 validatorでschema検証を行い、対象packの
revisionとCatalogのbytesを同じcandidateへ束縛してください。保存したCatalog
だけを後からCurrent Truthの根拠にしてはいけません。

Schemaは`status`と内容の整合も確認します。`PASS`ではpack id、profile、flow、
Block、MOC、structural status、error countが成功形でなければなりません。
`INVALID_PACK`ではpack id、profile、flow、Block、Record、MOCを空にし、
structural statusを`FAIL`、error countを1以上にします。validatorがRecordを
任意に省略できるPackは、Catalogでも`PASS`・`records: []`として安全に一覧でき
ます。これらは構造状態の境界であり、承認やruntimeの証明ではありません。

未知の`--format`値や余分な引数は、終了code 2、固定usage、固定の
`invalid command-line arguments`で拒否します。入力値そのものをusageやエラーへ
反映しないため、secret-likeな値を渡してもCatalog本文やprivate locatorは出力され
ません。

## 関連手順

- Template Guide: Company Template、Blocks、Records、MOCsの編集方針
- Starter Walkthrough: initializer、customization、review bundleの順序
- [Public Preview Self-check](PUBLIC-PREVIEW-SELF-CHECK.md): validator、Catalog、customization、false-claim境界の一括read-only確認。JSONまたは`--format markdown`の固定サマリーを選べます
- Template Pack Validation: 構造・参照・禁止経路のvalidator境界
- Company Pack Guided Next Steps: 現在地と理想の次の一手
- Candidate-bound Review Workflow: exact bytesと独立reviewの束縛
