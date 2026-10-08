# Official Cloudflare OS bounded runtime candidate

This directory pins the first Kotodama review baseline for the official
[Cloudflare OS](https://github.com/cloudflare/cloudflare-os) project.

The selected baseline is the exact current
[deployment starter](https://github.com/cloudflare/cloudflare-os-starter) and
the core gitlink that starter actually names. The separately observed core
repository head is intentionally not substituted for that gitlink. The two
revisions differ, so an upstream drift review is required before changing the
baseline.

Issue #12の2026-10-08の別候補は
[`security-2026-10-08/README.md`](security-2026-10-08/README.md)にあります。
依存graphとOAuth bindingのcomponent検査は成功しましたが、Windows local workerdの
全suiteは共通baselineでも失敗しており、採用・全remediationの完了ではありません。

## pnpm配布物の署名と公開元

[`pnpm-supply-policy.json`](pnpm-supply-policy.json) はpnpm 11.9.0の固定archive、
registry鍵文書、期待する `pnpm/pnpm` のrelease workflow／tag／source commitを
束縛する候補policyです。registryの鍵IDは公開されたopaque IDとして使い、DERからの
再導出を主張しません。鍵文書は公開registryから取得した観測であり、独立したtrust rootの
採用判断は未実施です。

Node 24とPython 3.12を信頼するローカル検証環境で、取得済みの公開入力を指定します。
GH CLI 2.96.0は公式releaseのchecksumに照合したx64版（Windows／Linux）だけを
policyのbinary hashで許容し、検証中はそのbytesを専用の一時ディレクトリへ固定します。

```text
python -B tools/verify_pnpm_supply.py --metadata <pnpm-11.9.0-registry.json> --keys <registry-keys.json> --archive <pnpm-11.9.0.tgz> --bundle <slsa-bundle.json> --gh-executable <verified-gh-binary> --node-executable <node24>
python -B -m unittest tests.test_pnpm_supply_verifier -v
```

registryのECDSA P-256署名とartifact digestを照合し、GH CLIでSigstore/SLSA署名、
期待する証明書identity／issuer／source ref・commit／github-hosted runnerを確認します。
公開bundleはregistryのattestations応答からSLSA v1のbundleを一つ選んだJSONです。
`--cert-identity` がworkflowとtagを含むため、相互排他的な `--signer-workflow` は併用しません。
GH CLIの出力から証明書とsubjectをもう一度照合し、内容を含まないdigestと結果だけを返します。
CLIは公開trust materialの取得に通信を使うことがあります。provider tokenやGitHub認証は
引き継がず、proxy／CA設定とOS実行設定だけを渡します。archiveをinstall・実行しません。

[`pnpm-supply-verification-2026-10-08.json`](pnpm-supply-verification-2026-10-08.json)
は今回の実検証の観測です。元のlocal-runtime-evaluationは書き換えません。
署名・identityの成功はpolicy trustの採用、独立reviewの受入、upstream採用、配備、Public Betaを
意味しません。出力の該当gateはすべてfalseのままです（Issue #13）。

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
