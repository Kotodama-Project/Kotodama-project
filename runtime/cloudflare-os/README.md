# Official Cloudflare OS bounded runtime candidate

This directory pins the first Kotodama review baseline for the official
[Cloudflare OS](https://github.com/cloudflare/cloudflare-os) project.

The selected baseline is the exact current
[deployment starter](https://github.com/cloudflare/cloudflare-os-starter) and
the core gitlink that starter actually names. The separately observed core
repository head is intentionally not substituted for that gitlink. The two
revisions differ, so an upstream drift review is required before changing the
baseline.

## 固定された上流差分のレビュー記録

[`upstream-drift-review.json`](upstream-drift-review.json) はIssue #11の固定2版、
99ファイル（+19,090 / -1,627）のreader記録です。別readerが79ファイルのdiff読解を
申告し、generated declarations 19件とlockfileは部分確認として残しています。
schema、件数、gap、blob IDと行数を検査できる構造にしたもので、validatorは読解の意味・
reviewer本人・独立性承認・実行結果を証明しません。元のlocal-runtime-evaluationは保持します。

```text
python -B tools/validate_cloudflare_upstream_review.py
python -B tools/validate_cloudflare_upstream_review.py --core-repo <public-core-clone>
python -B -m unittest tests.test_cloudflare_upstream_review -v
```

共通のhash-locked Python依存が必要です。`--core-repo` は既存Git objectだけを読み、
固定2版の全path／blob／行数を照合します。fetch、checkout、source編集は行いません。
指定しない場合はrecordの契約検査だけです。どちらも採用pin、provider、Public Betaを変えません。
toolchain更新、traceの保持・予算、Context/scheduler自動導入の権限、observer scope互換、
snapshot replay、generated再現性の受入は未完了です。独立性承認とre-pinはownerの判断です。

Validate the source pin, content-free Gatekeeper projection contract, and saved
local runtime evaluation receipt:

```powershell
python tools/validate_cloudflare_os_candidate.py
python -m unittest tests.test_cloudflare_os_candidate -v
python tools/validate_cloudflare_os_local_runtime_evaluation.py
python -m unittest tests.test_cloudflare_os_local_runtime_evaluation -v
python tools/validate_cloudflare_os_security_candidate.py
python -m unittest tests.test_cloudflare_os_security_overlay -v
python -S -B tools/validate_cloudflare_quality.py
python -m unittest tests.test_cloudflare_quality_budget -v
```

These validation commands read local candidate files and run synthetic
metadata-only tests. They do not clone or execute Cloudflare OS, install
dependencies, use a credential, call a provider API, enable billing, upload a
Worker or Dynamic Worker, or publish anything.

The saved evaluation separately records a completed content-free local run:
1060 upstream tests passed with 7 explicit skips, all 26 workspace package
projects received build coverage, and the accepted runtime returned three
stable headers-only HTTP 200 responses in `LOOPBACK_ONLY` mode. Cleanup left
zero evaluation processes and listeners. See
[`local-runtime-evaluation.json`](local-runtime-evaluation.json) and the
[human-readable evaluation report](../../docs/CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md).

This is `PASS_LOCAL_RUNTIME_WITH_GAPS`, not provider or production readiness.
The original local-runtime receipt retains six P1 findings, including its
observed upstream `nanoid` High and pending independent drift review. Its
successor security-overlay candidate now maps the pinned Git workspace blob to
two parent-scoped overrides: `nanoid` 3.3.18 and
`@puppeteer/browsers` 3.0.4, which removes the newly reviewed vulnerable
`extract-zip` path in favor of integrity-bound `modern-tar` 0.7.7. Exact
`pnpm@11.9.0` regeneration, scripts-disabled frozen install, zero-High
production audit, all 26 builds, and 279 focused tests passed locally (4
provider-dependent tests skipped). The transformer does not synthesize or edit
a lockfile, and matching bytes alone cannot establish who generated them.
Independent review and provider deployment/remediation remain required.

Cloudflare OS is an early-access AI productivity environment, not a traditional
computer operating system. Kotodama selects it as the shared frontend for
knowledge, conversation, Tasks and agents, using its workspace/Gadget/Gatekeeper
foundation. Operations return to Kotodama's existing governed owners, which
retain Human Intent, Decision, Work Order, Promotion and Current Truth.
BecomeOne is the migration donor and later a consumer pinned to the public
Kotodama version and content digest. The frontend-to-owner path remains a
design direction; native versus embedded UI and live integration are unproven.
Proxmox retains the protected local runtime/data plane; Context Gateway retains
query authority. A Gatekeeper result enters Kotodama as a candidate and cannot
promote Current Truth by itself. Its metadata-only projection preserves the
public/protected data class and refuses Context admission/corpus binding
mismatches.

`NO_GO_UNPUBLISHED` remains in force.

## 固定版の品質予算（#15）

[`quality-budget.json`](quality-budget.json) は上流sourceを含まない数値とdigestの予算です。
2026-10-07にstarterのcore gitlink `bf7f762` をNode 24.14.0 / pnpm 11.9.0で
scripts-disabled frozen installし、oxlintとfrontendのtsc/Vite buildを実行しました。
security overlayは適用していません。Git blobのLF lock digestを使い、古いruntime記録の
CRLF digestとは区別します。依存の意味的な変更はありません。

警告64件を14個のpackage/rule/origin bucketと個別fingerprintへ結び、すべて上流sourceの
警告として記録しました。generated/vendorの警告をsource枠へ混ぜたり、新しい警告と
同じ件数で交換したりしても拒否します。no-shadow、consistent-function-scoping、
no-extraneous-class、no-this-aliasは、固定版を変更しないlocal評価の既知の品質債として
2026-11-07までの一時例外にします。providerや公開に対する例外ではありません。
この予算変更自体を独立reviewへ付け、期限後は再検討まで検査が失敗します。

frontendはJS 26 files / 4,484,205 bytes、CSS 2 files / 296,339 bytesです。
JSの通常上限は500,000 bytes、indexとworkspace routeの大きい2chunkだけを個別の
bytes/gzip/countで固定します。合計とfile数にも上限があり、各予算はPR baseより増やせません。
新しいbucketや増額が必要なら、予算を黙って上書きせず別のowner判断として扱います。

依存install後の空のdistからのfrontend buildは約30.8秒でした。ローカルstatic shellを
Chromeで3回読み込んだload eventは332 / 300 / 211ms（四捨五入）です。HTTPはno-store、
同じbrowser process、外部接続はfixtureのCSPで拒否、backendは合成401です。
画面はLoading/再接続表示で、ログイン・編集・WAN・cold V8 cache・実利用の速さは未検証です。
時間は観測値として残し、変動するlatencyを数値予算の成功やprovider受入に読み替えません。

再計測したoxlint JSONと同じcore checkoutのdistは次のように検査します。

```text
python -S -B tools/validate_cloudflare_quality.py --core-repo PINNED_CORE --lint-json LOCAL_OXLINT_JSON --dist PINNED_CORE/packages/workshop-frontend/dist
```

validatorはsource pin、tracked差分、lock、与えられた診断と実asset bytesを照合します。
buildやreviewを自分で実行した証明は発行せず、数値範囲内であることだけを返します。
