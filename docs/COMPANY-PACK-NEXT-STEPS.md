# Company Pack Guided Next Steps

`check_company_pack_customization.py`は、Company Packに残る静的置換、governed review、外部evidenceを一件ずつ正確に返します。`plan_company_pack_next_steps.py`はそのreportをSSOTとして再利用し、人間が最初に知りたい**現在地、理想の流れ、分類別の残件、次の一手**へ集約します。

このplannerはcheckerを置き換えません。値を書き換えず、reviewを完了扱いにせず、authorityやGOを作りません。

## Run

initializerで作った作業copyに対して実行します。

```powershell
python tools\create_company_pack.py my-company work\my-company
python tools\plan_company_pack_next_steps.py work\my-company --format markdown
```

```bash
python3 tools/create_company_pack.py my-company work/my-company
python3 tools/plan_company_pack_next_steps.py work/my-company --format markdown
```

defaultはautomation向けのdeterministic JSONです。

```powershell
python tools\plan_company_pack_next_steps.py work\my-company
```

同じPack bytesと同じtool bytesからは、同じUTF-8の1行JSONを返します。Markdownもconsole localeへ依存せずUTF-8で出力します。JSON schemaは[`company-pack-next-steps.schema.json`](../schemas/company-pack-next-steps.schema.json)です。

## 現在地の読み方

| Stage | 意味 | Recommended next |
|---|---|---|
| `STRUCTURAL_REPAIR` | pack validatorがFAILし、customizationを解釈していない | `validate_template_pack.py`で構造を直す |
| `STATIC_CUSTOMIZATION` | 構造PASSだがexample placeholderが残る | 元checkerのexact itemを見ながら置換する |
| `CANDIDATE_BINDING` | 静的placeholderは0件 | Packのvalidated file setをreview bundleへ固定する |

plannerが成功してplanを作れた場合、`CUSTOMIZATION_REQUIRED`でもexit codeは`0`です。Pack自体が不正な`INVALID_PACK`は`1`、CLI usage errorは`2`です。未知のformatや余分な引数は固定usageだけを返し、入力値をエラーメッセージへ反射しません。これはcustomization checkerのexit codeとは異なります。plannerの成功は「次の作業を安全に案内できた」という意味だけです。

## 分類別の見方

長いchecker reportを次のgroupへ件数集計します。各categoryのgroup合計は元reportのcountと必ず一致しますが、個別`id/path/reason`はplanner出力に含めません。

| Category | 主なgroup | 作業の境界 |
|---|---|---|
| `replacement_required` | Pack identity/status、Human Intent locator、Block authority window、Record retention policy | 候補Packの編集で閉じられる |
| `review_required` | canonical owner、runtime profile、Block owner role、Record owner/creator/verifier | 実authorityを持つ組織reviewが必要 |
| `evidence_required` | Human Intent真正性、owner acceptance、人物分離、retention、Human Decision | このlocal CLIでは閉じられない |

exact JSON pathとreasonが必要なときは、元checkerを実行します。

```text
python tools/check_company_pack_customization.py PACK_DIRECTORY
```

## 理想の流れ

plannerは次の順序を常に表示します。

1. `create_draft_copy`: 組織固有IDへ再束縛した`draft`を作る。
2. `replace_static_placeholders`: locator、期限、retention参照を置き換える。
3. `validate_candidate`: schemaとcross-file contractを検証する。
4. `bind_exact_review_candidate`: 現在のPackでvalidatorが確認したfile setの
   exact bytesをbundleへ固定する。公開Company starterでは22ファイル、
   `manifest.records`を省略したrecordless Packでは13ファイルというように、
   実際に参照された数へ束縛される。
5. `governed_review`: owner、profile、roleを実authorityの下で確認する。
6. `collect_external_evidence`: 真正性、受諾、人物分離、保持、Human Decisionの証拠を閉じる。
7. `separate_promotion`: 承認済みcandidateだけを別のPromotion processへ渡す。

公開starterの現在地は、この理想形の構造と作業導線を提供する段階です。実組織のreview、external evidence、runtime execution、Promotionは公開Pack内では実行していません。

## Boundary

- plannerはPackをread-onlyで検査し、fileを作成・変更・削除しません。
- invalid reportのvalidator error本文とmanifest値は再出力せず、`pack_id`も`null`にします。
- 構造PASS後のMarkdownに表示するPack IDはmanifestの非secret IDです。Pack IDに秘密名や個人情報を書かないでください。
- local module importではbytecode cacheを作らず、Packも変更しません。
- `CANDIDATE_BINDING`はapproval、runtime readiness、Promotion、Current Truthではありません。
- すべての`claims`はfalseで、`public_beta`は常に`NO_GO_UNPUBLISHED`です。

exact itemの意味は[Company Pack Customization Checklist](CUSTOMIZATION-CHECKLIST.md)、候補bytesを固定した後の手順は[Candidate-bound Review Workflow](REVIEW-WORKFLOW.md)を参照してください。保存bundleが`MATCH`したcandidateへ個別review itemを束縛するには[Company Pack Review Request](REVIEW-REQUEST.md)を使います。
