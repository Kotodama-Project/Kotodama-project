# CI と必須チェック

固定fixtureの実行時間・メモリ・欠測を比較する手順は、[性能計測CLI](PERFORMANCE-BENCHMARK.md)を参照してください。

公開リポジトリの GitHub Actions と、main の branch protection が要求するチェックの一覧です。CI の PASS は local / static な証拠であり、install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。

## Workflow 一覧

mainへのpushで検証runが作られなかった場合は、現在のmain SHAを記録して
`gh workflow run repository-validation.yml --repo Kotodama-Project/Kotodama-project --ref main`
で同じ検証を手動起動できます。入力で検査を省略する選択肢はありません。
runの`headSha`が確認対象のSHAと一致し、全jobが完了したことを読戻してください。
別SHAの緑やrunが存在しない状態を、そのmain commitのPASSにしません。

| Workflow（表示名） | ファイル | 起動 | 目安の所要 | 必須 | 内容 |
|---|---|---|---|---|---|
| Repository validation（job: Repository checks → **Trusted repository validation**） | `.github/workflows/repository-validation.yml` | PR、main への push、手動 | checks は最大 25 分、集約は全依存の終了後 | **必須**（集約が成功を要求） | Discord・swarm と並列に tracked credential hygiene、README の one-command smoke、runtime candidate validator、actionlint、hash-locked pip install、immutable workflow reference check、`python -m unittest discover -s tests`（docs lint を含む）、`git diff --check` と clean tree。Trusted job は全3経路の成功を確認 |
| Repository validation（job: **test (ubuntu-latest)**・**test (windows-latest)**） | `.github/workflows/repository-validation.yml` | PR、main への push、手動 | 2〜3 分 | **必須**（`Trusted repository validation` も成功を要求） | `runtime/discord-template` の `pnpm test` と `pnpm check`。Linux は固定 digest の Docker image で検証隔離の実 probe を行う |
| Task swarm validation（Linux 2 shards・Windows 4 shards → Complete Task swarm coverage） | `.github/workflows/task-swarm.yml` | 必須チェックから `workflow_call`、手動 | 各実行最大20分、集約最大5分 | **必須**（`Trusted repository validation` が全shardと集約の成功を要求） | hash固定依存、全Task swarm pytest、各OSで1回のoffline demoとbenchmark。全件一覧・工程結果・分割の過不足を検査。Linuxは固定native CLIの合成permission probeも実行し、model/APIは呼ばない。ubuntu-latestではbwrap uid mapが拒否されたため22.04を明示 |
| Git Steward validation（job: Git Steward (ubuntu-latest)・(windows-latest)） | `.github/workflows/git-steward-validation.yml` | Git Steward・Python launcher・このworkflowの変更を含むPR、mainへのpush | 最大5分 | 任意 | Node 24でcoordinatorと業務演習の59 Node testsを実行。依存install、全Python suite、provider操作は含まない |
| Cloudflare candidate validation | `.github/workflows/cloudflare-candidate-validation.yml` | PR、main への push | 1〜2 分 | 任意 | Cloudflare edge / 公式 Cloudflare OS 候補の content-free validator |
| Cloudflare edge preview candidate | `.github/workflows/cloudflare-edge-preview.yml` | 手動（workflow_dispatch） | 未実行 | 任意 | environment `cloudflare-preview`（required reviewers、self review 禁止）での preview upload 候補。必要な secret が揃っておらず、これまで一度も実行されていません |
| Dependency review | `.github/workflows/dependency-review.yml` | main への PR | 数秒 | **必須** | 依存追加の脆弱性レビュー |
| Release candidate（job: Build, attest, and draft the release） | `.github/workflows/release.yml` | `v*` tag の push | 数分 | 任意 | smoke report と source archive を作り、provenance attestation を付けて draft の prerelease を作る。公開は人が行う |
| CodeQL（default setup） | GitHub 側の設定 | PR、main、週次 | 1〜2 分 | 任意 | actions / javascript-typescript / python / csharp |

必須チェックは `Trusted repository validation`、`test (ubuntu-latest)`、`test (windows-latest)`、`Dependency review` の 4 件で、`strict: true`（PR branch が main に追いついていること）です。`Trusted repository validation` は並列実行した Repository checks、Discord matrix、呼び出した Task swarm matrix の全3経路に依存し、一つでも failure / skipped / cancelled / 未実行なら成功しません。matrix 待ち後に全Python検査を始める直列依存を除き、3経路を並列に開始できる構成です。実際の全体所要はrunnerの待機時間を含め、短縮幅は更新headのhosted CIで測ります。Discord は各 OS で 1 回だけ実行します（従来の直接起動と reusable 呼出しによる 4 jobs から 2 jobs へ削減）。必須チェック名と検証内容は維持します。`gh api repos/Kotodama-Project/Kotodama-project/branches/main/protection` で読み戻せます。

全Python検査の進行中に15分の上限でcancelした[hosted実行](https://github.com/Kotodama-Project/Kotodama-project/actions/runs/37198502503/job/111425839551)を受け、Repository checksの上限を25分にします。検査を減らさずrunnerの所要差に余裕を持たせ、成功の条件は維持します。軽いTrusted集約jobは15分の上限を保持します。

## Task swarm の有限観測

[#396](https://github.com/Kotodama-Project/Kotodama-project/issues/396) は
[#331](https://github.com/Kotodama-Project/Kotodama-project/issues/331) の観測部分です。
既存の pytest command、`python_files=test_task_swarm_*.py`、Linux/Windows、依存 lock、
demo、benchmark、20分上限、必須 gate を維持します。このobserver自身は並列化や性能閾値を追加しません。
pytest の最終 durations/JUnit だけでは中断前の集合を残せないため、明示した小さい
`tools.pytest_ci_observer` plugin が pytest の通知を保存します。

`events.jsonl` は collection 順序と重複 occurrence、各 test/工程の開始、
setup/call/teardown の duration・outcome、skip/xfail 理由、成功を含む subtest を記録します。
subtest の message/parameters は固定 pytest が表示する値であり、任意 object の意味的に
安定した ID を作るものではありません。総件数だけで実行同値を主張しません。
先頭には run/job/attempt、PR head と実 checkout/merge SHA、lock/observer SHA、Python・OS・
runner image と主要 package version を記録し、host 名や環境変数全体は保存しません。

生イベントは毎回 file へ書き、同じ JSON を `KOTODAMA_PYTEST_EVENT ` 行として
Actions console へ flush します。test が工程内で停止しても、その直前までの記録を
`gh run view RUN_ID --log` から参照できます。`always()` の artifact upload は失敗・取消時も
私有 runner temp の成果物を7日間保存する設定です。job の強制終了や runner 消失で upload
自体が実行されなかった場合は、既に届いた console が partial evidence です。
GitHub の log 欠測・切断も完全な観測とは呼びません。通常の pytest 出力は従来どおり
Actions log に残り、この adapter は test stdout/stderr の追加 spool を作りません。

stream と追加 console はそれぞれ最大16 MiB、1 event は64 KiB、最大20,000 events、
最終文書は8 KiBです。容量超過は記録を不完全にし、残りの test や元の exit code を
変更しません。pytest 成功後の独立した完全性検査が、最終文書の欠落、partial、切断、
digest/collection/工程結果の不一致を拒否するので、欠測した観測で必須 gate は成功しません。
`final.json` の `complete` は観測集合の完結であり、test の合否は別の `pytest_exit_code` です。
signal handler を追加せず、pytest の失敗・中断コードと外部 terminate をそのまま伝えます。

保存済み artifact の確認は Task swarm の固定依存環境で実行します。

```text
python -B tools/pytest_ci_observer.py PATH_TO_OBSERVATION_DIRECTORY
```

`observer_hook_seconds_before_final_write` は metadata 取得と event の encoding/write/flush
内の経過時間だけです。import、最終書込、検査、upload、観測による test への影響を含む
全費用は未測定です。工程時間にも hook の費用が入り得ます。CPU、peak RSS、queue 時間は
unknown とし、単発の fixture や OS 間の所要差を高速化の受入・SLO に転用しません。
次の最適化は同じ固定 source/environment の実行・skip・subtest 集合を照合して評価します。

### 子processの期限切れ診断

#420で失敗を観測した復旧・learning CLIの8 occurrenceだけに、`tools.pytest_ci_process_probe`を明示して
適用します。closed-loop復旧の`none`、executor CLIの`13-False`と`23-False`、learning CLIの
明示承認とanchor replay、単一constructorとhome path正規化を確認する実CLI回帰、dependency復旧のterminal再開と2 resumerを対象にします。
既存の20秒/30秒/60秒の`subprocess.communicate`期限と失敗の伝播を維持します。
`subprocess.run`のtimeout後の終了・回収はPythonの元の実装が担います。
直接`Popen.communicate`を使う2 resumerの既存挙動も維持し、timeout後の自動回収を追加したとは扱いません。
期限直前とtimeout時に、rootのPID・exit状態・CPU/RSS/I/O
counterとWindowsのstdout/stderr reader threadの生存だけを記録します。引数・環境変数・
標準出力の本文やファイル内容は記録しません。rootの終了とpipe EOF待ちは区別できますが、
特定の子孫がhandleを保有することや、SQLite待ち・CPU遅延の根本原因はこの観測だけでは証明しません。

追加artifact `task-swarm-process-OS-INDEX-RUN-ATTEMPT` は最大128 KiB・64 child呼出の
`events.jsonl`と別枠の有限summaryを7日間保持します。既存の全occurrence照合とは別の診断で、欠測・容量超過は
summaryの`complete=false`またはsummary欠落として扱います。観測でtestの成否を変えず、
追加samplingの費用を記録し、test全体への観測負荷は未測定のままです。再実行成功だけで
#420を解決済みとは扱いません。

### Learning CLIの初期化計測

`python -B tools/measure_learning_reuse_cli.py` は、既存の合成実CLI受入testを
通常module起動とconstructor時間だけを観測する起動で実行します。
元のassertionと各20秒の期限を維持し、操作名・回数・時間・終了codeだけを表示します。
timeoutは失敗として残し、別fixtureの観測modeまで実行してから非zeroで終了します。
CIではWindows/Linuxの独立job（各10分）で実行し、全件shardとその20分上限を変更しません。
観測付きmain起動と通常module起動は区別し、時間差だけをtimeout原因の証明にしません。

## Task swarm の全件分割と集約

Windowsでは全件実行が20分で中断したため、CIに限って4個の独立jobへ分割します。
Linuxも全件pytest成功後のpost-check中に20分で中断したため2個へ分割します。
各OSの全件とshard 0のdemo・benchmarkを引き続き要求し、製品の実行並列度、
テスト、skip条件、依存lock、各jobの20分上限は変更しません。
各jobは同じ `python -m pytest -q -p no:cacheprovider -o 'python_files=test_task_swarm_*.py' tests`
で全件をcollectionし、明示した `tools.pytest_ci_shards` が全件一覧の0始まりの順番を
shard数で割った余りで担当を選びます。同名のnodeidも別occurrenceとして保持し、
担当内の順序は維持します。各OSのshard 0は、selectorもobserverも載せない別の
collect-only実行で独立した全件一覧を記録します。追加の `-k` 等の絞り込みは拒否します。

従来のobserverは担当分の各工程をそのまま記録します。別の有限sidecarは全件一覧、
担当occurrence、source・lock・selectorのdigest、run/attemptとOSを束縛します。
全jobの後に集約が、現在のcheckoutに対してLinux 2個・Windows 4個の成果物を照合し、
独立一覧との一致、全件が各OSで一度ずつ実行されたこと、pytestと各jobの成功を要求します。
欠落・重複・別source・別run・途中終了・失敗を成功にしません。既存のskipやsubtestは
工程記録へ残ります。demoとbenchmarkは各OSのshard 0で1回ずつ必須実行し、その成功も
集約に束縛します。`Trusted repository validation` はこの集約を含むswarm全体に依存します。

artifactは `task-swarm-shard-OS-INDEX-RUN-ATTEMPT` で7日間保存します。
`reference/`（shard 0）、`partition/`、`observation/`、`completion.json`を分け、
各sidecarは最大2 MiB、全件一覧は最大5,000 occurrencesです。observerの容量は従来どおりです。
欠測時は公開consoleをpartial evidenceとして扱います。分割による実際の所要は現在headの
hosted実行で確認し、過去の工程時間の割当計算を新しい実行時間や速度SLOとは呼びません。

再実行はworkflowの全jobを対象にします。失敗jobだけを再実行すると、成功済み区画の
artifactは前attemptに残るため、同じattemptの5区画を要求する集約が拒否します。
過去attemptの成果物を混ぜたり、集約条件を緩めたりして成功にしません。

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

### cloud agent の初期準備

Linux と Python 3.12 がある環境では `bash tools/dev/setup_agent_env.sh` を実行し、
`source work/agent-env/activate.sh` で準備した環境を使います。PythonのCI patch版は
3.12.10です。スクリプトは実際のpatch版を表示し、版の違いをCI一致と主張しません。
Node 24が無ければSHA-256固定の24.14.0、CorepackはSHA-512固定の0.34.6を
workspace内へ導入し、packageManager指定のpnpm 11.19.0をCorepackで取得します。
Pythonの共通・Task swarm依存は両方のhash付きlock、Discordはfrozen lockから
scriptsを無効にして導入します。providerへの接続やモデル呼出しはありません。

`.claude/settings.json` のSessionStartはstartup/resume時に同じ入口を呼びます。
`CLAUDE_CODE_REMOTE=true` のcloudだけで実行し、`CLAUDE_ENV_FILE` があれば
activationを次のshellへ渡します。ほかのagent環境ではsetup欄へ上のコマンドを登録し、
実行shellでactivationしてください。環境側の設定はこのPRでは変更しません。
[公式のcloud hook仕様](https://code.claude.com/docs/en/cloud-environments#install-dependencies-with-a-sessionstart-hook)
に従います。

初回はnodejs.org、registry.npmjs.org、pypi.org、files.pythonhosted.orgへの通信が
必要です。通信不能や不足toolは `INCOMPLETE` と該当段階を表示し、終了0でsessionを
継続します。secretファイル・ambient provider tokenは使いません。proxy/CA設定だけは
既存ネットワークに従って引き継ぎ、値やpackage managerの生出力を表示しません。
git・ffmpegとPython自体は環境側で準備します。lock・実行版が同じなら再installを省き、
Pythonの整合性を再確認します。生成物は無視済みの `work/` と `node_modules/` です。
READYは依存準備の結果です。以下の全検査は別に実行してください。Task swarmの実CLI
permission probeには、CIの固定fixtureと対応Linux sandboxが別途必要です。

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

全体の unittest には Git Steward の試験（`tests/test_git_steward_runtime.py`）が入り、Node 22.13 以上と Git を使います。無いときは skip せずに失敗します。Linuxの`Repository checks`はSHA固定済みsetup-nodeでNode 24を用意します。追加の任意workflowは、関連pathだけを対象にWindows/LinuxでNode suiteを実行します（#131の記録済み判断）。必須チェックは増やさず、全Python検査も重複させません。実Windows runnerでの成功はhosted実行が完了するまで未検証です。

`runtime/task_swarm` の変更（Python 3.12）:

```text
python -m pip install --require-hashes -r requirements-task-swarm-ci.txt
python -m pytest -q -p no:cacheprovider -o 'python_files=test_task_swarm_*.py' tests
python tools/task_swarm.py demo --root work/offline-demo --allow-local-fixture
```

`runtime/discord-template` の変更（Node 24、pnpm 11.19.0）:

```text
pnpm install --frozen-lockfile --ignore-scripts
pnpm test
pnpm check
```

## 失敗したときの直し方

### 件数と検証範囲

全体の unittest と専用 pytest は役割が異なります。共通 lock には pytest / MCP SDK を
追加せず、pytest 専用の modules は必須 Task swarm job へ委譲します。委譲の
`ModuleSkipped` も unittest の件数に含まれるため、集計件数だけを成功した実ケース数や
運用品質として扱いません。各結果の実行・skip・対象集合を記録します。

Task swarm の tests は `tests/test_task_swarm_*.py` に置きます。pytest の filename
設定でその集合だけを collection し、無関係な tests を import してから捨てる処理を省きます。
変更前後の100 node IDsは一致し、Linux / Windows の全 matrix を引き続き要求します。
静的文書・schema・合成CLI・bounded runtimeのPASSは、実provider、常時接続や
モデルの推論品質の証拠ではありません。

テストを軽くするときも、全 mutation と実CLIの入口・終了コード・入力拒否・内容を出さない
診断を保ちます。同じ production `main(argv)` のfile/parser/validator経路を直接呼ぶ検査と、
実 child process の境界検査を分け、代表例のpayload/終了コード一致とguard欠落の負例を確認します。
署名・nonce・snapshotのfixtureは独立性を保ち、実行時間は機械に依存する参考値とします。

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

## Discord matrix の実行上限

Discord jobは依存・音声encoderの準備を含め20分で打ち切ります。Windowsの
source-binding実CLI fixtureは起動に最大30秒（他OSは15秒）を許し、終了を観測する
15秒の上限と既存のsource/権限検査は維持します。実CLIを起動する各caseは90秒で打ち切り、準備・起動・検査・cleanupを含む外側の上限が30秒の起動待ちより先に発火しないようにします。600件を超える試験群で観測した
Windowsの起動待ちと10分job打切りに対する余裕で、runtimeの本番timeoutや許可を
変更するものではありません。失敗や取消を成功として扱わず、全必須checkを要求します。
