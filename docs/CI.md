# CI と必須チェック

公開リポジトリの GitHub Actions と、main の branch protection が要求するチェックの一覧です。CI の PASS は local / static な証拠であり、install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。

## Workflow 一覧

| Workflow（表示名） | ファイル | 起動 | 目安の所要 | 必須 | 内容 |
|---|---|---|---|---|---|
| Repository validation（job: **Trusted repository validation**） | `.github/workflows/repository-validation.yml` | PR、main への push | 約 10 分 | **必須** | tracked credential hygiene、README の one-command smoke、runtime candidate validator、actionlint、hash-locked pip install、immutable workflow reference check、`python -m unittest discover -s tests`（docs lint を含む）、`git diff --check` と clean tree |
| Discord runtime candidate（job: test (ubuntu-latest) / test (windows-latest)） | `.github/workflows/discord-runtime.yml` | PR、main への push | 1〜2 分 | 任意（必須化を検討中） | `runtime/discord-template` の `pnpm test` と `pnpm check` |
| Cloudflare candidate validation | `.github/workflows/cloudflare-candidate-validation.yml` | PR | 1〜2 分 | 任意 | Cloudflare edge / 公式 Cloudflare OS 候補の content-free validator |
| Cloudflare edge preview candidate | `.github/workflows/cloudflare-edge-preview.yml` | 手動（workflow_dispatch） | 未実行 | 任意 | environment `cloudflare-preview`（required reviewers、self review 禁止）での preview upload 候補。必要な secret が揃っておらず、これまで一度も実行されていません |
| Dependency review | `.github/workflows/dependency-review.yml` | PR | 数秒 | 任意 | 依存追加の脆弱性レビュー |
| CodeQL（default setup） | GitHub 側の設定 | PR、main、週次 | 1〜2 分 | 任意 | actions / javascript-typescript / python / csharp |

必須チェックは `Trusted repository validation` の 1 件で、`strict: true`（PR branch が main に追いついていること）です。`gh api repos/Kotodama-Project/Kotodama-project/branches/main/protection` で読み戻せます。

## ローカルで同じ確認をする

文書だけの変更:

```text
python -S -B tools/lint_docs.py
python -S -B tools/smoke_company_pack_review_chain.py
git diff --check
```

tools / schema / tests の変更:

```text
python -S -B tools/check_tracked_secret_hygiene.py
python -m pip install --require-hashes -r requirements-ci.txt
python -B tools/check_workflow_references.py
python -m unittest discover -s tests -v
```

`runtime/discord-template` の変更（Node 24、pnpm 11.19.0）:

```text
pnpm install --frozen-lockfile --ignore-scripts
pnpm test
pnpm check
```

## 失敗したときの直し方

- **docs lint が FAIL**: 出力の `errors` にファイルと理由（リンク切れ、未解決アンカー、README の行数超過、入口文書での内部語）が出ます。`tools/lint_docs.py` の docstring に規則があります。
- **`tests.test_public_status_roadmap_sync` が FAIL**: `STATUS.md` を変えたら `Updated:` の日付を更新します。過去の revision を「current」と書かないでください（履歴は `docs/HISTORY.md`）。
- **Dependabot の PR が `Trusted repository validation` で FAIL**: 以前は tests が action の SHA を文字列で固定していました。#82 が「action 名 + 40 桁 SHA + version comment」の検査へ緩和します。それまでは pin を更新する commit を PR に積んでください。
- **tracked credential hygiene が FAIL**: 出力は path、行番号、detector 名だけです。値は revoke / rotate してから履歴の扱いを別途決めます（`SECURITY.md`）。
- **`git status --porcelain` が空でない**: テストが生成物を残しています。生成物を書き戻す変更は、その generator の実行結果を commit に含めてください。

## 変更するときの約束

- 新しい workflow は原則として `repository-validation.yml` の step か、`paths` を絞った軽い job として提案します。独立した cron や全件 unittest の重複実行は増やしません。
- Actions は full commit SHA と `# vX.Y.Z` コメントで固定します（`tools/check_workflow_references.py` が検査）。
- `runtime/discord-template/.github/workflows/ci.yml` はテンプレート同梱用で、このリポジトリでは実行されません。
