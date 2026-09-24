# Contributing / 貢献の手引き

Kotodama は Incomplete Public Preview です。狭い範囲の Issue と Pull Request を歓迎します。次の境界は変えません。

- local PASS を live、deployed、safe、complete、Public Beta、Human approval とは呼ばない。
- credential、private な host 名や絶対パス、参加者の情報、音声、文字起こし、private source の本文を公開面に入れない。
- 競合サービスの比較を公開リポジトリに書かず、Kotodama 自身の要求と機能として書く。
- Source Evidence、Intent Candidate、Human Decision、Work Order、Change、Verification、Promotion、Current Truth を混ぜない。

## 3 つの経路

| 変更 | 先にすること | 手元で通すもの |
|---|---|---|
| 文書だけ（README、docs/、STATUS、ROADMAP） | Issue は不要。小さな PR にする | `python -S -B tools/lint_docs.py`、`python -S -B tools/smoke_company_pack_review_chain.py`、`git diff --check` |
| 不具合の修正 | 再現手順を Issue（bug form）に書く | 該当テストと `python -S -B tools/check_tracked_secret_hygiene.py` |
| 新機能、adapter、設計 | Issue（proposal form）で範囲と完了条件を合意する | 下の全体の確認 |

## 全体の確認（tools、schema、tests、runtime を変えるとき）

Python 3.12 を使います。依存を入れる前に tracked credential gate を通します。

```text
python -S -B tools/check_tracked_secret_hygiene.py
python -m pip install --require-hashes -r requirements-ci.txt
python -B tools/check_workflow_references.py
python -m unittest discover -s tests -v
git diff --check
```

credential gate は HEAD、index、tracked な working tree の 3 つの snapshot を検査し、path、行番号、detector 名だけを報告します（値は出力しません）。PASS は GitHub 側の secret scanning、push protection、履歴の走査の代わりにはなりません。

`requirements-test.txt` が人が編集する入力で、`requirements-ci.txt` は pip-tools 7.6.1 で生成した hash 付きの lock です。両方を一緒に更新し、依存の audit 結果を PR に書きます。

```text
pip-compile --generate-hashes --output-file=requirements-ci.txt requirements-test.txt
```

Task swarm（`runtime/task_swarm`）は MCP SDK などの依存が多いため、共通 lock とは別の `requirements-task-swarm-ci.txt` を使います。入力は `requirements-task-swarm.txt` と `requirements-task-swarm-test.txt` で、Linux と Windows の両方で使えるよう uv 0.12.17 の universal 解決で生成します。

```text
uv pip compile --universal --generate-hashes --python-version 3.12 --output-file requirements-task-swarm-ci.txt requirements-task-swarm-test.txt
```

`runtime/discord-template` を変えるときは Node 24 と pnpm 11.19.0 で次を通します。

```text
pnpm install --frozen-lockfile --ignore-scripts
pnpm test
pnpm check
```

テストの実行後に working tree が clean であることを確認します。CI の内容は [docs/CI.md](docs/CI.md) にあります。

## Pull Request の約束

- 1 PR は 1 論点にします。目安は 400〜800 行、15 files までで、超えるときは分割計画を本文に書きます。
- タイトルは `type: 要約` にします。type は `feat` / `fix` / `docs` / `test` / `chore` / `ci` の英語、要約は日本語でも英語でも構いません。squash merge でそのまま main の履歴になります。
- 本文は PR template の 4 節（目的、変更点と変えていないこと、実行した検証、未検証・影響範囲）を埋め、対応する Issue があれば `Closes #N` を書きます。実行しなかった確認は「未実行」と書きます。
- provider への書込、credential の変更、公開設定、破壊的操作を、コードだけの変更に混ぜません。
- branch 名は `type/短い説明` か `codex/<topic>-<日付>` にします。merge 後の branch は自動で削除されます。
- 生成物（`requirements-ci.txt` など）は手で直さず generator で更新します。
- 別の PR の branch を base にする stack は 2 段までにし、base が merge されたら main へ付け替えます。

## レビューと merge（現在の運用）

- 必須チェックは `Trusted repository validation` です。
- 現在は単独メンテナの運用で、人間の承認は GitHub 上で必須になっていません。Codex の自動レビューが PR に付くため、merge はそのレビューが投稿され、指摘を処理してから行います。人による独立レビューが成立した PR は本文にそう書き、成立していない PR を「独立レビュー済み」とは書きません。
- draft PR は 14 日以上更新がなければ `status/parked` を付けて close し、要点を Issue に残します。
- 担当は `.github/CODEOWNERS` にあります。

## 言語と用語

日本語を正本にし、英語の要約を併記できます。用語は [README.md](README.md) の用語表と `CONTEXT` の定義に合わせます。境界を表す語（`NO_GO_UNPUBLISHED`、candidate-only、Promotion、Current Truth）は意味を変えずに使います。

## English summary

Narrow issues and pull requests are welcome. Keep the evidence and authority boundaries: never describe a local pass as live, deployed, or approved; never add secrets, private identifiers, participant data, audio, transcripts, or private source bodies. Documentation-only changes need `python -S -B tools/lint_docs.py`, the smoke, and `git diff --check`; code changes need the full local check list above (Python 3.12, hash-locked dependencies, `python -m unittest discover -s tests -v`). One topic per pull request, `type: summary` titles, the four-section template, and `Closes #N` when an issue exists. The repository is maintained by a single maintainer; automated review comments arrive on each pull request and are handled before merge.
