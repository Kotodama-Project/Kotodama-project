# CI と必須チェック

公開リポジトリの GitHub Actions と、main の branch protection が要求するチェックの一覧です。CI の PASS は local / static な証拠であり、install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。

## Workflow 一覧

| Workflow（表示名） | ファイル | 起動 | 目安の所要 | 必須 | 内容 |
|---|---|---|---|---|---|
| Repository validation（job: **Trusted repository validation**） | `.github/workflows/repository-validation.yml` | PR、main への push | 約 10 分 | **必須** | tracked credential hygiene、README の one-command smoke、runtime candidate validator、actionlint、hash-locked pip install、immutable workflow reference check、`python -m unittest discover -s tests`（docs lint を含む）、`git diff --check` と clean tree |
| Repository validation（job: **test (ubuntu-latest)**・**test (windows-latest)**） | `.github/workflows/repository-validation.yml` | PR、main への push | 2〜3 分 | **必須**（`Trusted repository validation` も成功を要求） | `runtime/discord-template` の `pnpm test` と `pnpm check`。Linux は固定 digest の Docker image で検証隔離の実 probe を行う |
| Task swarm validation（job: swarm / validate (ubuntu-latest)・(windows-latest)） | `.github/workflows/task-swarm.yml` | 必須チェックから `workflow_call`、手動 | 2〜5 分 | **必須**（`Trusted repository validation` が成功を要求） | `requirements-task-swarm-ci.txt` の hash 付き install、`pytest -k task_swarm`、offline demo（モデル呼出しなし） |
| Cloudflare candidate validation | `.github/workflows/cloudflare-candidate-validation.yml` | PR、main への push | 1〜2 分 | 任意 | Cloudflare edge / 公式 Cloudflare OS 候補の content-free validator |
| Cloudflare edge preview candidate | `.github/workflows/cloudflare-edge-preview.yml` | 手動（workflow_dispatch） | 未実行 | 任意 | environment `cloudflare-preview`（required reviewers、self review 禁止）での preview upload 候補。必要な secret が揃っておらず、これまで一度も実行されていません |
| Dependency review | `.github/workflows/dependency-review.yml` | main への PR | 数秒 | **必須** | 依存追加の脆弱性レビュー |
| Release candidate（job: Build, attest, and draft the release） | `.github/workflows/release.yml` | `v*` tag の push | 数分 | 任意 | smoke report と source archive を作り、provenance attestation を付けて draft の prerelease を作る。公開は人が行う |
| CodeQL（default setup） | GitHub 側の設定 | PR、main、週次 | 1〜2 分 | 任意 | actions / javascript-typescript / python / csharp |

必須チェックは `Trusted repository validation`、`test (ubuntu-latest)`、`test (windows-latest)`、`Dependency review` の 4 件で、`strict: true`（PR branch が main に追いついていること）です。`Trusted repository validation` は同じ workflow の Discord matrix と呼び出した Task swarm matrix に依存し、どちらかが failure / skipped / cancelled / 未実行なら成功しません。Discord は各 OS で 1 回だけ実行します（従来の直接起動と reusable 呼出しによる 4 jobs から 2 jobs へ削減）。必須チェック名と検証内容は維持します。`gh api repos/Kotodama-Project/Kotodama-project/branches/main/protection` で読み戻せます。

## Release の SBOM と provenance を確認する

Release workflow は `requirements-ci.txt`、`requirements-task-swarm-ci.txt`、
`runtime/discord-template/pnpm-lock.yaml` から、それぞれ CycloneDX 1.6 JSON の
SBOM を作ります。既存の hash-locked PyYAML を使い、追加の依存や action はありません。
全 platform・marker の distribution 候補を含む lock inventory であり、実際に
install された部品、依存 graph、ライセンス、脆弱性の不存在は証明しません。
各 SBOM の metadata は入力 lock の相対 path と SHA-256 を保持します。

手元で生成するときは Python 3.12 と共通 lock の依存を用意してから実行します。
保存済み SBOM は上書きしません。

```text
python -B tools/build_release_sbom.py --release v0.2.0-preview --output-dir work/release-sbom
```

`sbom-python-ci-<tag>.cdx.json`、`sbom-python-task-swarm-<tag>.cdx.json`、
`sbom-discord-<tag>.cdx.json` を source archive、smoke report とともに
SHA256SUMS と draft release に含めます。既存の build provenance action は
この 3 ファイルと checksum manifest も subject とします。これは build provenance
であり、専用の SBOM predicate による部品と archive の関係の attestation ではありません。

draft release から成果物を取得した reviewer は、各 SBOM と checksum manifest を
以下の形で確認します（tag とファイル名は対象 release に置き換える）。

```text
gh attestation verify sbom-discord-v0.2.0-preview.cdx.json --repo Kotodama-Project/Kotodama-project --signer-workflow Kotodama-Project/Kotodama-project/.github/workflows/release.yml --source-ref refs/tags/v0.2.0-preview
gh attestation verify SHA256SUMS-v0.2.0-preview.txt --repo Kotodama-Project/Kotodama-project --signer-workflow Kotodama-Project/Kotodama-project/.github/workflows/release.yml --source-ref refs/tags/v0.2.0-preview
```

期待する signer はこの repo の `release.yml`、source ref は確認対象の正確な
`refs/tags/v*` です。POSIX では `sha256sum -c SHA256SUMS-<tag>.txt`、PowerShell
では `Get-FileHash <artifact> -Algorithm SHA256` を manifest と照合します。
SBOM metadata の lock digest も取得した source archive 内の lock と照合します。
署名者の運用方針と tag push / publish は owner の判断です。今回の local 生成は
provider attestation や draft release の受入を証明しません（Issue #166 / #122）。

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

`runtime/task_swarm` の変更（Python 3.12）:

```text
python -m pip install --require-hashes -r requirements-task-swarm-ci.txt
python -m pytest -q -p no:cacheprovider tests -k task_swarm
python tools/task_swarm.py demo --root work/offline-demo --allow-local-fixture
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
- **Dependabot の PR が FAIL**: action の更新は、#82 以降「action 名 + 40 桁 SHA + version comment」の検査で通ります。hash 付き lock の中の依存だけを上げた PR（例: pydantic なしの pydantic-core）は `pip install --require-hashes` の依存解決で失敗します。その場合は取り込まず、入力の requirements から CONTRIBUTING の手順で lock を作り直します。exact version で連動する `httpx2` / `httpcore2` の minor・patch 更新は一つの Dependabot group にまとめます。共通 lock と Task swarm lock の共有依存は同じ version に保ち、検査は特定の transitive version ではなく、入力の直接依存・全 entry の hash・共有依存の一致を確認します。
- **tracked credential hygiene が FAIL**: 出力は path、行番号、detector 名だけです。値は revoke / rotate してから履歴の扱いを別途決めます（`SECURITY.md`）。
- **`git status --porcelain` が空でない**: テストが生成物を残しています。生成物を書き戻す変更は、その generator の実行結果を commit に含めてください。

## 変更するときの約束

- 新しい workflow は原則として `repository-validation.yml` の step か、`paths` を絞った軽い job として提案します。独立した cron や全件 unittest の重複実行は増やしません。
- Actions は full commit SHA と `# vX.Y.Z` コメントで固定します（`tools/check_workflow_references.py` が検査）。
- Python の依存は hash 付き lock から入れます。共通の `requirements-ci.txt`（pip-compile）に加え、MCP SDK など依存の多い Task swarm だけは `requirements-task-swarm-ci.txt`（`uv pip compile --universal`、Windows 専用依存も marker 付きで同じ lock に入る）を使い、共通 lock を小さく保ちます。
- `runtime/discord-template/.github/workflows/ci.yml` はテンプレート同梱用で、このリポジトリでは実行されません。
