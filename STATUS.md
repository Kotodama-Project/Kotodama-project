# Project Status

Updated: 2026-08-09

| Surface | Status |
|---|---|
| Public repository | Published preview |
| Product direction and roadmap | Public |
| Company governance starter | Published and locally validated |
| Compose / Proxmox lifecycle contract | Published and locally validated |
| [Cloudflare edge preview candidate](runtime/cloudflare-edge/README.md) | Draft PR candidate; content-free local validation only, no version upload or deployment |
| [Official Cloudflare OS bounded runtime candidate](docs/CLOUDFLARE-OS-ADOPTION.md) | Draft PR candidate; exact source pin, six synthetic metadata projections, and content-free local runtime receipt; no provider execution |
| Compose minimum data-plane skeleton | Published candidate; offline config only |
| Resolved Compose candidate | Published credential-free configuration candidate |
| Local image availability preflight | Published read-only tool; saved verification is historical binding only |
| Clean-install / migration evidence candidate | Published unattested saved-binding contract; no live receipt |
| Protected one-use attestation evaluation | Published local candidate; atomic only within one bound SQLite store |
| Signed nonce-store checkpoint | Published protected-local tool; point-in-time and immediate-parent only |
| Recursive nonce-store checkpoint chain | Published protected-local candidate; supplied path/store equivalence only |
| Checkpoint-head anchor / restore-drill evidence | Published protected-local contract; signed reported binding only |
| Checkpoint segment transition / key rotation | Published protected-local contract; one presented boundary only |
| Segment transition candidate builder | Published protected-local CLI; deterministic new-file creation only, unsigned and unverified |
| [Source binding verification candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) | Included in this revision as a read-only local candidate; stable postcheck and R30 projection digest only |
| [Protected Source binding receipt candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md) | Included as an unpopulated schema-only private receipt contract; no protected runner or verified receipt |
| [Protected execution request / handoff candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) | Included as an opaque schema-only request shape; no execution accepted, executed, or private handoff |
| [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) | Included as a read-only aggregate of starter validator, Catalog, customization, and false-claim checks |
| [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) | Published `read-only/candidate-only` catalog; no runtime or approval; `NO_GO_UNPUBLISHED` |
| [Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md) | Published deterministic planner/runbook; candidate-only guidance only; `NO_GO_UNPUBLISHED` |
| [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md) | Published schema, validator, test, and runbook map; local/static evidence only |
| [Compose candidate runbooks](docs/RESOLVED-COMPOSE-CANDIDATE.md) | Published read-only candidate guidance with PowerShell/POSIX parity; no live image or runtime receipt |
| [Image availability preflight](docs/IMAGE-AVAILABILITY-PREFLIGHT.md) | Published read-only historical-binding guidance with PowerShell/POSIX parity; current-host availability remains unverified |
| [Company Pack review bundle](docs/REVIEW-BUNDLE.md) | Published candidate-only exact-byte binding and drift verifier; no approval or Promotion |
| [Company Pack Review Request](docs/REVIEW-REQUEST.md) | Published read-only request candidate; counts follow the saved Pack report |
| [Company Pack Review Response](docs/REVIEW-RESPONSE.md) | Published read-only response candidate; saved-request binding and item counts are dynamic |
| [Company Pack Decision Handoff](docs/REVIEW-DECISION-HANDOFF.md) | Published read-only handoff candidate; decision and selected outcome remain null |
| [Template Guide / Starter Walkthrough](docs/TEMPLATE-GUIDE.md) | Published ideal/current usage docs; starter counts are examples, not universal Pack invariants |
| [Company Pack CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) | Fourteen public entrypoints with fixed help boundaries and one candidate-only Smoke command |
| One-command review-chain smoke | Published standard-library-only local smoke; exact thirteen steps in a temporary workspace, no retained artifacts or GO |
| [5-minute tour](docs/FIVE-MINUTE-TOUR.md) | Clone-to-result first-visit path; external-free local smoke and bounded next choices only |
| README Company OS story map | Vision-to-Try-it reader map and eight-surface ideal/current boundary; documentation only |
| Live Compose / Proxmox installation | Not verified |
| Public Beta access | Not open |
| Public Discord invite | Not published |
| Public Voice Bot | Inactive |
| Raw audio or transcript corpus | Not published |
| Final Human GO | Not completed |

## Latest Cloudflare candidate result

The official Cloudflare OS candidate pins the current official starter and the
core gitlink that starter actually uses. The separately observed current core
head differs by 99 files and remains a mandatory independent-review boundary.
The Gatekeeper validator passes six content-free synthetic projections and
keeps provider, execution, Promotion, Current Truth, and Public Beta authority
false.

The saved [local runtime evaluation](docs/CLOUDFLARE-OS-LOCAL-RUNTIME-EVALUATION.md)
adds exact dependency/toolchain integrity, 1060 passing tests with 7 explicit
skips, all 26 workspace package projects covered by build checks, three stable
headers-only HTTP 200 responses in `LOOPBACK_ONLY` mode, and zero remaining
evaluation processes/listeners. The result is `PASS_LOCAL_RUNTIME_WITH_GAPS`.

P0/P1/P2 is 0/6/2. The open P1 set includes the independent drift review, one
high `nanoid` advisory, Windows-only compatibility mitigation, unproven
observability retention/readback, provider E2E, and package-manager attestation
signature. Dynamic Workers, Workers Paid entitlement, KV, R2, Browser Rendering,
Access, provider logs, private Context, backup, restore, Discord integration,
and production remain unproven. The edge Worker was not uploaded or deployed.
`NO_GO_UNPUBLISHED` remains unchanged.

## Latest runtime result

最新の CT200 Voice cutover attempt は、read-only reconciliation 後に `BLOCKED_NO_EFFECT` と判定されました。候補ファイルの deploy は 0、外部 provider API の作用も 0 でした。

これは安全に停止したことの証拠であり、Voice runtime が公開稼働していることの証明ではありません。

## Latest public template result

R179 is the current public documentation revision and the latest
Company OS orientation surface, bound to the published R178 fixed point at
public `main` commit `23e954d4f5bb0dbf4450d768d6b37c2895c97b0b`, tree
`25986611496feeebfed1d58ddf4b008d7f965457`. README now gives a near-top
`Vision -> Experience -> Architecture -> Current Reality -> Try it` reader map
and an eight-surface Company OS map connecting Office/Input, Voice,
Intent/GrillU, Governance/Evidence, Company Pack, Context Platform,
Workforce/Runtime, and Business/Learning. Every surface separates ideal role
from its current public boundary and links the existing detailed section
instead of duplicating it. This is documentation/static-regression evidence
only. It does not add public Voice, Discord access, runtime, provider,
authority, Promotion, Current Truth, Final Human GO, or Public Beta access;
`NO_GO_UNPUBLISHED` remains unchanged. The story-map regression is
[`test_readme_company_os_story_map.py`](tests/test_readme_company_os_story_map.py),
and the orientation regression remains
[`test_public_status_roadmap_sync.py`](tests/test_public_status_roadmap_sync.py).

R178 remains historical as the first-visitor tour revision and the
Template/Company/Blocks/Records/MOCs/starter orientation surface, bound to the
published R177 fixed point at public `main` commit
`d5d6187c7e5e7b6c4fe44e4b60a8aa096d4e8dc0`, tree
`efeffdaa7147fd83d763398c1c205f3708a67630`. The new
[5-minute tour](docs/FIVE-MINUTE-TOUR.md) gives a first-time visitor exact
PowerShell/POSIX `git clone` -> repository root -> one-command smoke steps,
explains the PASS/REFUSED report contract, and routes only to bounded public
next choices. It does not install packages, persist review artifacts, or route
the reader into runtime/provider/Discord/deploy mutation. The actual smoke
still runs the exact thirteen existing Company Pack steps, deletes its
temporary workspace, and keeps every authority/runtime/GO claim false. This
remains `read-only/candidate-only`; `NO_GO_UNPUBLISHED`, consent/privacy,
protected review, identity/authority/approval, runtime, Voice/Discord,
provider, Promotion, Current Truth, Final Human GO, and Public Beta boundaries
remain unchanged. The reader regression is
[`test_five_minute_tour.py`](tests/test_five_minute_tour.py), and the
orientation regression remains
[`test_public_status_roadmap_sync.py`](tests/test_public_status_roadmap_sync.py).
R178 is documentation/static-regression evidence only.

R177 remains historical as the latest
Template/Company/Blocks/Records/MOCs/starter orientation surface, bound to the
published R176 candidate at public `main` commit
`722345885b8767ee89a28e10f06db2de1ee73ace`, tree
`4282baf4efc394ffa786720f3bfca68d3caf78c0`. The
[Company Pack CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) now indexes
fourteen public entrypoints. Its Smoke entry runs the exact thirteen existing
Company Pack CLI steps inside a temporary workspace, removes that workspace,
persists no intermediate artifacts, and emits one closed candidate-only JSON
report. Run it with
`python -S -B tools/smoke_company_pack_review_chain.py` or
`python3 -S -B tools/smoke_company_pack_review_chain.py`. This remains
`read-only/candidate-only`; `NO_GO_UNPUBLISHED`, protected review,
identity/authority/approval, runtime, Voice/Discord, provider, Promotion,
Current Truth, Final Human GO, and Public Beta boundaries remain unchanged.
The orientation regression is
[`test_public_status_roadmap_sync.py`](tests/test_public_status_roadmap_sync.py).
R177 is documentation/static-regression evidence only.

R176 remains historical as the one-command review-chain smoke revision at
public `main` commit `722345885b8767ee89a28e10f06db2de1ee73ace`, tree
`4282baf4efc394ffa786720f3bfca68d3caf78c0`. R175 remains historical as the
fourteen-entrypoint Company Pack CLI Reference revision. R174 remains
historical as the review-chain help-boundary revision. R173 remains historical
as the core Company Pack help-boundary revision. R172 remains historical as the
Template/Company/Blocks/Records/MOCs/starter orientation surface, bound to the
published R171 candidate at public `main` commit
`c4a15b0e91a3bacd9125a24e1111521b467c174c`, tree
`ec7b2f200b427b2f4ff6dc3cf228fe4a19c8dd08`. R172 synchronized STATUS and
ROADMAP with R171's [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md)
post-PASS path: [Company Pack Guided Next Steps](docs/COMPANY-PACK-NEXT-STEPS.md)
then Review Bundle -> Review Request -> Review Response -> Decision Handoff.
Its external-free smoke is
[`test_public_starter_runbook_smoke.py`](tests/test_public_starter_runbook_smoke.py),
run as `python -m unittest tests.test_public_starter_runbook_smoke -v` or
`python3 -m unittest tests.test_public_starter_runbook_smoke -v`. That revision
remains `read-only/candidate-only`; `NO_GO_UNPUBLISHED`, runtime,
Voice/Discord, provider, Promotion, Current Truth, Final Human GO, and Public
Beta boundaries remain unchanged. R172 is historical
documentation/static-regression evidence only.

R171 remains historical as the Self-check review-chain next-step revision at
public `main` commit `c4a15b0e91a3bacd9125a24e1111521b467c174c`, tree
`ec7b2f200b427b2f4ff6dc3cf228fe4a19c8dd08`. R170 remains historical as the
Validation Guide customization/bundle stop-semantics revision at commit
`05a5292a129192b4c0524000f9497af7cdb7e28f`, tree
`fd614bc1fd958b3b7a57fddec0492ceb2897c9c0`. R169 remains historical as the
Template Guide candidate-runbook revision at commit
`e6db0ac14a5defd4649cb16e0331eb01c797fa3c`, tree
`167637f9d64f06164358d8ea80575a7b4bc2e6cd`. R168 remains historical as the
README Company Template/Blocks/MOCs usage-map revision at commit
`9a3eb71f6d77212c1a0dad0c851b2ebccbd613f6`, tree
`20a3a0e83612ac24bd97ef5ed72ebb6c24615649`. R167 remains historical as the
Starter Walkthrough smoke-command and STATUS/ROADMAP orientation revision at
commit `f84aaf8c91bddee858a320ba7e2629b5381c793c`, tree
`0b700d4a73d975377a705fd3d0a0b7678f34e893`. R166 remains
historical as the Starter Walkthrough and STATUS/ROADMAP orientation revision
at public `main` commit `030a2e14aa15ca3f201b96105743c48eeeee54cb`, tree
`08c4f8b9a784b1a30d82bf68b7316b5e3b32e6b9`; its R165 Validation parity and
R164/R163/R162 provenance remain below. R165 remains
historical as the Validation full-suite cross-shell parity revision at public
`main` commit `b3db55ca241c18fd795a2c5b341ef3d629dcf477`, tree
`036e8b1421c88e1e66fa3394c4f35e9d93ecf6b7`; its POSIX command was documented
as `python3 -m pip install -r requirements-test.txt` ->
`python3 -m unittest discover -s tests -v`, but not executed in the Windows
validation environment. R164 remains
historical as the Company Pack Catalog smoke-command parity revision at public
`main` commit `02cf18e6696e61839ecb866ce8d720b1fba8c582`, tree
`dff3c0b2e8990daa85650ef591158c94593c6b40`. R163 remains historical as the
STATUS/ROADMAP orientation to R162's MOC surface at public `main` commit
`b7979b2946a262ef6d024512606ecb80b4ab6845`, tree
`f316557224384c2d7a7a51ac3b314cff0bc236c2`; its R162 provenance and
navigation-only boundaries remain below. R162 remains
historical as the MOC smoke command parity and Markdown-to-JSON link-integrity
revision at public `main` commit
`aca4d22772e84cf7da103b97872c94a04c67ac31`, tree
`008f43ff3f929c990717799fd2bb1b1a52419485`; its commands were
`python -m unittest tests.test_mocs_entry_navigation -v` and
`python3 -m unittest tests.test_mocs_entry_navigation -v`; its POSIX `python3` command was
documented but not executed in the Windows validation environment. R161
remains historical as the Schema / Validator / Test Matrix full review-chain
revision at public `main` commit
`106173b689870be06bb83ed23a144c76ad850b33`, tree
`042c28d389881884af1e8bcde65eca521036db22`. R160 remains historical as the
Company Pack Catalog Quick start revision at public `main` commit
`c70ce092d2303321380bd411410baefd40dfd4fb`, tree
`be9514b9ed1664ef18ed365e40edfdccd96a6e0f`. R159 remains historical as the
Template entry full-chain revision at public `main` commit
`5639e25eb6458733db0687d605496f747939f944`, tree
`fe3a0dfb66e687060cb23efc39d9db68216aee24`. R158 remains historical as the
Company starter full-chain revision at public `main` commit
`eb7f52220eb6e17005a985473dec4b8f62216f46`, tree
`dbf9ccfb47c59b79a865151144cd83f85e065dff`. R157 remains historical as the
README candidate-path revision at public `main` commit
`9107637fa25681ffc3c144aa09a10496ee644a2c`, tree
`116d23e1679b8e8d25ad84a0a0865423f698263b`. R156 remains historical as the
STATUS/ROADMAP provenance revision at public `main` commit
`b9baa3df9d982f9e2a24ea4c0612afba4043acae`, tree
`6649d86fab5018c0812de3197220899d8bb3c5bf`. R155 remains historical as the
first-read Catalog/Next Steps/Matrix entry-navigation revision at public
`main` commit `97dca324e28777d4618abf53804f47db995e5abc`, tree
`9e4ad41d7f79ef6d2d9096ebccaad276ff03615c`. R154 remains
historical as the STATUS/ROADMAP synchronization to R153 at public `main`
commit `f12246af5954735c393108d42b8d2ce873d51406`, tree
`ae1319d42dc1d68fe860d5fbb7aed503e4db63df`. R153 remains historical as the
README Document Map **Review-chain artifact map** entry at public `main`
commit `92b574129ada8d9af2fc2a95e29cdd92590a5dd8`, tree
`b8d981464e18c31e448b3b57d3bb758ad6f67ae2`; it points to
`STARTER-WALKTHROUGH.md#review-chain-artifact-map` and exposes the Review
Bundle, Review Request, Review Response, and Decision Handoff artifact states
and next handoffs. R152 remains
historical as the STATUS/ROADMAP synchronization to R151 at public `main`
commit `371641e16b3857115be3a52ee32a12117c3bd7f1`, tree
`a6acc28e2455275d294463591f8ffece13ce542f`. R151 remains historical as the
artifact-map entry-surface revision at public `main` commit
`7633f0d4996c1bd210fb68b65fb12ff81c7fe4b7`, tree
`5bcb3b231e1377b3505e51385b57feb04f607361`. R150 remains
historical as the R149 STATUS/ROADMAP synchronization at public `main`
commit `e15655db50da8106eeb9976f2b2d6c92f4884b43`, tree
`476d36bf3faaf8b9ccb9f8b11e5e6a56680b358a`; R149 remains historical as the
artifact-map publication at public `main` commit
`ea23f3a31ae68025bf23889beea878d3062adefa`, tree
`0fa942044a2140b243b4a03c831c511b9938332b`. It introduced the Review-chain
artifact map for Review Bundle, Review Request, Review Response, and Review
Decision Handoff, with the Company Pack Catalog entry and before or after the
external-free smoke guidance. The R149 regressions are
[`test_starter_walkthrough_runbook_docs.py`](tests/test_starter_walkthrough_runbook_docs.py)
and [`test_company_pack_catalog_entry_navigation.py`](tests/test_company_pack_catalog_entry_navigation.py).
R148 remains
historical as the first-read review-chain entry wording revision at public
`main` commit `a0c050aa6c7c7f40302e3cd9afffad65a61a3ae5`, tree
`01e5183e3a0c63369afdc437dfb360bf2d070455`. R147 remains historical as the
full review-chain smoke revision at public
`main` commit `ef3fb24451b1600fadfeb8f6405051d0bb00a676`, tree
`dd413a232c9765f84f75bf8c06fe4e3b3ebcbb49`. R147 adds the **full
review-chain smoke** after the starter Bundle: Review Request, Review Response,
and Review Decision Handoff are saved and freshly verified in one temporary,
external-free pack. The executable regression is
[`test_public_starter_runbook_smoke.py`](tests/test_public_starter_runbook_smoke.py),
with the runbook links in README, Starter Walkthrough, Schema / Validator / Test
Matrix, and Company Pack Next Steps. R147 is documentation/static-regression
evidence only; the published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`. R146 remains historical as the STATUS/ROADMAP
synchronization to the R145 schema review-chain revision at public `main`
commit `1abcfd8f835f7d52627c194aacd8a62efb87875b`, tree
`2c8579fa242357dcc28a6d73c95011e1446b6846`; R145 remains historical as the
schema matrix review-chain revision at public `main` commit
`21a4a23586ebfd653a56d7c4b82a778d3791d6ed`, tree
`7a151d62026f4381c4c2734bcbc841797ee9f554`. R144 remains historical as the
Company Pack direct review-chain navigation revision at public `main` commit
`a0ab89f6b5f09deedb695dd478cce9ef421fef77`, tree
`9ed3f7e1cb5884893044e9d5a464c21f758f77ac`. R143 remains historical as the
Company Pack review-chain documentation revision. R141 remains historical as
the Company Pack Guided Next Steps and Installation Lifecycle revision at
public `main` commit `ebcdd003d062c6bc90b5ea546da3d430911bda74`, tree
`ec765b5f824a92d2efdc065b4a225d7779a6e9d2`, with
[`docs/COMPANY-PACK-NEXT-STEPS.md`](docs/COMPANY-PACK-NEXT-STEPS.md) and
[`docs/INSTALLATION-LIFECYCLE.md`](docs/INSTALLATION-LIFECYCLE.md) covered by
[`test_company_pack_next_steps_entry_navigation.py`](tests/test_company_pack_next_steps_entry_navigation.py)
and [`test_installation_lifecycle_docs.py`](tests/test_installation_lifecycle_docs.py).
R140 remains historical as the
Installation Lifecycle guided-next-steps revision at public `main` commit
`2ad60c6eb24a33e125f658ff0be52a3d53b27fa3`, tree
`55fc6ab347409ffb4444390c67b25fe9b548997f`. R139 remains historical as the
Company Pack guided path revision at public `main` commit
`f1bc6e79159fb175bbd8f575a9e09e8cb724245c`, tree
`3fdd381b3902e6f57c271f8d5fa7a3932ad4adb0`. R133 remains historical as the
README Document Map layer-wording revision at public `main` commit
`15a94c9f041c04994ab1ae00630ae0ea58387276`, tree
`538badff2d305e7b567b312e1ae918579050b44c`. R133 clarified that Status and
Roadmap are orientation, followed by five ideal Company Template layers, while
Catalog onward remains current read-only/candidate-only. The changed surface was
[`README.md`](README.md), covered by
[`test_readme_company_template_usage.py`](tests/test_readme_company_template_usage.py).
R132 remains historical as the
README Guided Next Steps entry-navigation revision at public `main` commit
`9f1b3ee5556740abab803f49164bad02bdeda3ae`, tree
`7f9d2ed059cd48e7240d9904e41221e219c47276`; R131 remains historical as the
STATUS/ROADMAP synchronization to R130 at public `main` commit
`0e772cdd4a4a95ad97fee3f60555fb52ebad3f8b`, tree
`b6ffb79781c50bbc07ba7e22405d31e12148be28`. R130 remains historical as the
Company Pack Next Steps entry-navigation revision at public `main` commit
`1667007004f92ac65e0124355fda9b71d81d7e6b`, tree
`aebd38c2012b745333e66348232dc88804181b65`. R130 adds a stable
ideal/current/smoke first-stop in
[`docs/COMPANY-PACK-NEXT-STEPS.md`](docs/COMPANY-PACK-NEXT-STEPS.md), covered by
[`test_company_pack_next_steps_entry_navigation.py`](tests/test_company_pack_next_steps_entry_navigation.py),
linking the ideal Company Template, Blocks, Governed Records, and MOCs layers
to the current Company Pack Catalog / Starter Walkthrough and the planner
schema/regression smoke path. R130 is documentation/static-regression evidence
only; the published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`. R129 remains historical as the STATUS/ROADMAP provenance
synchronization to R128 at public `main` commit
`4d29fca3f8005c9758b78889adab04b2f9614512`, tree
`a178210e7356108a020edd7b9784e24735250105`. R128 remains historical as the
Company Pack Catalog entry-navigation revision at public `main` commit
`752fa4b46246110757f01294b559c39412a0b4be`, tree
`60ee3062bcd472562e01f03708cb1fd58c32f7f7`. R128 adds a stable
ideal/current/smoke first-stop in
[`docs/COMPANY-PACK-CATALOG.md`](docs/COMPANY-PACK-CATALOG.md), covered by
[`test_company_pack_catalog_entry_navigation.py`](tests/test_company_pack_catalog_entry_navigation.py),
linking the ideal Company Template, Blocks, Governed Records, and MOCs layers
to the current Company starter/Catalog and the Matrix/Walkthrough/regression
smoke path. R128 is documentation/static-regression evidence only; the
published surface remains read-only/candidate-only and `NO_GO_UNPUBLISHED`.
R127 remains historical as the MOC entry-navigation revision at public `main`
commit `b05db80ec979129d176408870a4f4e4857e43ded`, tree
`ac02e58afb505e8ae4be15c5ad5eda80ae57f318`, with
[`templates/mocs/README.md`](templates/mocs/README.md) and
[`test_mocs_entry_navigation.py`](tests/test_mocs_entry_navigation.py).
R126 remains historical as the STATUS/ROADMAP synchronization to R125.
R125 remains historical as the Company Starter entry-navigation revision at
public `main` commit `a5d052d425c9236a5cdb118a796b936ba74232aa`, tree
`bca093039d31b3b0f7c595ec91d8224f7419bd7c`. R125 adds a stable
ideal/current/smoke first-stop in
[`examples/company-starter/README.md`](examples/company-starter/README.md),
covered by [`test_company_starter_entry_navigation.py`](tests/test_company_starter_entry_navigation.py),
linking the Company Template layers, Company Pack Catalog, Schema / Validator /
Test Matrix, Starter Walkthrough, and Public Preview Self-check. R124 remains
historical as the root Template Catalog entry-navigation revision at public
`main` commit `26946de5655835dfdff75a6aef2b8f344d7b7e78`, tree
`2778816782efb41029657a9788463fbe1569f681`; R123 remains historical as the
STATUS/ROADMAP synchronization to R122. R122 remains historical as the
Blocks/Records navigation revision at public `main` commit
`677bd15bec0fdfd22410b237916d05be0d1ca02c`, tree
`299a0248734daec3974b80ff174b4540995f4c47`. R122 added ideal/current/smoke
guidance and a stable Read next path in
[`templates/blocks/README.md`](templates/blocks/README.md) and
[`templates/records/README.md`](templates/records/README.md), with the
[`test_blocks_records_navigation.py`](tests/test_blocks_records_navigation.py)
regression. The [Company Pack Catalog](docs/COMPANY-PACK-CATALOG.md) still
links the [Schema / Validator / Test Matrix](docs/SCHEMA-VALIDATOR-MATRIX.md)
Runbook smoke, the [`test_public_starter_runbook_smoke.py`](tests/test_public_starter_runbook_smoke.py)
path, and the [`test_company_pack_catalog_runbook_smoke_entry.py`](tests/test_company_pack_catalog_runbook_smoke_entry.py)
entry, while the README Quick Start and [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)
retain the same executable smoke. The guided path reaches bundle at
`CANDIDATE_FOR_GOVERNED_REVIEW` -> `MATCH`, while
the plain path remains `CUSTOMIZATION_REQUIRED` and fail-closed with
`BUNDLE_REFUSED`. The published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`; R121 remains historical as the Matrix-to-Catalog smoke
entry, R120 remains historical as the STATUS/ROADMAP provenance
synchronization to R119, and R119 remains historical as the Company Pack
Catalog Runbook smoke entry at public `main` commit
`b878464eca0571fe293222d372cf417c9e9e1573`, tree
`f5aa3a3fa405c0e5fed4d984921d6ad44dca0bd3`. R118 remains historical as the
Template Guide first-read smoke entry, R117 remains historical as the
STATUS/ROADMAP provenance synchronization, R116 remains historical as the
README Runbook smoke entry at public `main` commit `2a5a65cdbefc0e1fc33c88771a95443ed52d5960`, tree
`456d5a990ae030699246959e12daf0a4a9cbb6d1`,
R115 remains historical as the Starter Walkthrough smoke entry, R114 remains
historical as the STATUS/ROADMAP provenance synchronization, R113 remains
historical as the starter smoke matrix revision, R112 remains historical as the
STATUS/ROADMAP provenance synchronization, R111 remains historical as the
schema/validator test matrix revision, and R110 remains historical as the stable
MOC index revision, R109 remains historical as the STATUS/ROADMAP label cleanup,
R108 remains historical provenance, and R107 remains historical provenance.
R37 introduced
the read-only [Public Preview Self-check](docs/PUBLIC-PREVIEW-SELF-CHECK.md) with a deterministic `--format markdown`
summary. R45 added the saved-bundle to Review Request boundary, R46
added the dynamic Review Response boundary, R47 added the dynamic Decision
Handoff boundary, and R48 clarified that the starter's `19/46/5` values are
examples; another Pack follows its actual checker, saved report, and
review-chain counts. R50 added the eight-entry-point navigation
synchronization: each entry point explains ideal/current usage and links the
read-only Review Request, Review Response, and Decision Handoff path. R52
added the explicit ideal/current Company Template usage flow to README. R54
added the practical ideal/current Template Catalog usage sequence and links.
R55 hardened standard unittest discovery for that Catalog regression. R56 added
the first-read order and bounded runtime profile selection for
`compose_minimum` and `proxmox_segmented`. R58 added the README first-stop guide
that sends readers through Catalog, Starter Walkthrough, and Installation
Lifecycle only when a runtime profile is needed. R62 added the Company Pack
Catalog first-stop sequence with the same bounded order and no-runtime
boundary. R64 added template-pack path canonicalization, R65 added
installation-lifecycle purpose schema/validator parity, and R66 added Compose
binding integer schema/validator parity. These surfaces do not add runtime
authority or access, and
activation, Promotion, Current Truth, and Public Beta remain outside the
published preview.

R68 added the README Voice rotation ideal/current contract for the 900-second
boundary, speaker/timestamp private-channel post, listener/rejoin continuity,
and retention/delete receipt. This is documentation only; real Voice rotation
remains unproven, and no capture, ASR, Discord post, deletion receipt, runtime
authority, Promotion, Current Truth, or Public Beta access was added.
R70 aligned the resolved Compose candidate's bytes semantics with Draft 2020-12:
finite non-negative integer-valued JSON numbers are accepted while booleans,
fractions, negatives, and non-finite values remain rejected. A Docker-free
synthetic candidate passes both validators. This is validator/test hardening
only; it does not add Compose runtime, image, provider, deployment, restart,
credential/permission, Promotion, Current Truth, or Public Beta access.

R72 added installation-lifecycle fixed-boolean schema/validator parity, and R73
added Compose security fixed-boolean schema/validator parity. R74 added
resolved Compose nested boolean schema/validator parity: numeric 0/1 aliases
are rejected by both schema and stdlib validator while integer-valued binding
bytes remain accepted. These are validator/test hardening changes only; they do
not add Compose runtime, installation, deployment, Voice runtime, Discord post,
provider, authority, Promotion, Current Truth, or Public Beta access.

R76 clarified the ideal/current MOC boundary: Voice Operations and Venture /
Customer Discovery are conceptual future candidates, while the public starter
ships exactly three navigation-only MOCs. This is documentation/test hardening
only; no runtime, authority, Promotion, Current Truth, or Public Beta access
was added.

R78 clarified the ideal six-phase installation lifecycle versus the current
sanitized public candidate. The published profile examples, schema, validator,
runbooks, and synthetic examples expose no target-bound runtime receipt,
image acquisition, start/restart, migration, restore, or provider connection.
The command/path regression binds the documented Windows/POSIX validator and
Compose/Proxmox runbook references to shipped files. This is documentation/test
hardening only; no runtime, Voice, provider, authority, Promotion, Current
Truth, Final Human GO, or Public Beta access was added.

R80 clarified the ideal Company Template -> Blocks -> Governed Records -> MOCs
-> validator -> review -> runtime candidate flow and separated it from the
current local/synthetic, read-only/candidate-only starter path. Installation
Lifecycle remains profile guidance only; the starter does not claim install,
deploy, restart, restore, Voice/Discord E2E, provider connection, Promotion,
Current Truth, Final Human GO, or Public Beta access. This is documentation/test
hardening only; `NO_GO_UNPUBLISHED` remains unchanged.

R82 clarified the ideal six-phase installation lifecycle against the current
sanitized public candidate and added PowerShell/POSIX runbook and validator
command parity. R83 aligned the Validation Guide ideal/current boundary and its
lifecycle command paths. R84 added README PowerShell/POSIX command parity for
Quick Start, Review Bundle, and runtime-candidate validation. R85 added
onboarding PowerShell/POSIX command parity for customization, planning,
Catalog/self-check, validator, and review-bundle preparation. These are
documentation/test hardening only; they do not add runtime, Voice, Discord,
provider, authority, Promotion, Current Truth, Final Human GO, or Public Beta
access, and `NO_GO_UNPUBLISHED` remains unchanged.

R86 synchronized STATUS and ROADMAP provenance through the R85 onboarding
surface. R87 added Template Guide and Catalog POSIX parity, R88 added guided
onboarding POSIX parity, R89 added Validation Guide core POSIX parity, R90
added Public Preview Self-check POSIX parity, and R91 added Compose candidate
runbook POSIX parity. Each revision was published with focused regression
coverage and exact remote readback; each remains documentation/test hardening
only and does not add runtime, Voice, Discord, provider, authority, Promotion,
Current Truth, Final Human GO, or Public Beta access.

R92 synchronizes the public STATUS/ROADMAP provenance to the R91 public
candidate (`b071ce9b2fd4167c8ac199bcd1983b64224fba43`, tree
`c6c7bafebd9cca6bdc37365af560b2f11f9fc7e8`). This synchronization is itself
documentation-only; `NO_GO_UNPUBLISHED` remains unchanged.

R100 added the standalone Public Preview Self-check cross-navigation from the
ideal Company Template layers through the current Catalog, Starter Walkthrough,
and Installation Lifecycle path. R101 added the standalone Installation
Lifecycle reading entry from Template Guide -> Company Template -> Blocks ->
Governed Records -> MOCs, then Catalog -> Starter Walkthrough before profile
selection. R102 synchronized STATUS/ROADMAP provenance to that surface. R103
added the README ideal/current layer map: Template Guide -> Company Template ->
Blocks -> Governed Records -> MOCs before Catalog -> Starter Walkthrough ->
Public Preview Self-check -> Installation Lifecycle. R103 remains the
historical README/documentation layer-map candidate at commit
`92a67b1bd0b450b549590d915b24dd983bb3eb7a`, tree
`a8437da05a2688e64129458eb604a6f604deb59c`. R104 synchronized
STATUS/ROADMAP provenance to R103, which remains historical. R105 added the
direct Installation Lifecycle link in the Template Catalog Runtime profiles
row and was the historical public Template Catalog/Installation Lifecycle
candidate at commit `615fdbab66ed1ad3fa779fb762dc8a27eca857d1`, tree
`3b881f999704e1c3e3c3f4c0929fd019c6f163ed`. These are documentation/test
changes only; `read-only/candidate-only` and `NO_GO_UNPUBLISHED` remain in
force, and real Voice rotation remains unproven.

R106 synchronized STATUS/ROADMAP provenance to R105; R105 remains historical.
R107 aligned the Company Template ideal order to Human Intent -> Blocks ->
Governed Records -> MOCs -> validator/review before optional runtime profile
selection. Its historical public candidate was commit
`de163c060006d50545229fd8ef092f97c583074d`, tree
`a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc`. This is
documentation/test hardening only; the public path remains
read-only/candidate-only and `NO_GO_UNPUBLISHED`, with no runtime, Voice,
provider, Promotion, Current Truth, or Final Human GO claim.

公開Company starterは、Source IntakeからPromotion Decision Recordまでの9 Block、全出力を受ける9種のGoverned Record契約、Company Operations / Public Release Review / Incident & Recoveryの3 MOC、manifestを含みます。目的別MOCは同じcanonical flowの順序を保ったnavigation projectionです。依存なしinitializerは元exampleや既存targetを上書きせず、pack IDとMOC参照を再束縛し、22文書を`draft`にして生成packを検証します。customization checkerはplaceholder 0でも`READY_FOR_GOVERNED_REVIEW`までに限定し、review/evidenceを残します。review bundle builderは、その状態だけをmanifest・Blocks・MOCs・Recordsのexact SHA-256 / byte sizeへ束縛し、途中driftを拒否します。saved-bundle verifierはbundle metadata/digestと現在bytesを再照合し、duplicate keyや1-byte driftをfail closedで`MISMATCH`にします。Review Request、Response、Decision Handoffは保存済みchainを再入力なしで運びますが、すべてread-only/candidate-onlyです。Work Order、Capability Grant、Change Executionを分離し、Promotion Candidateと人間のPromotion Decisionも分離しています。標準ライブラリvalidatorでflow、MOC、Record coverageを検査できますが、実権限付与、Human approval、incident runtime、recovery execution、runtime deployment、Promotion、Current Truthを作るものではありません。

Source binding verification candidateは、privateなR31 record、Source Content、aggregate access evidenceをbounded no-link readerで照合し、strict parse、exact raw-byte binding、lossless R30 source-binding projection digest、二回のterminal rereadを報告します。reportは常に`CANDIDATE_ONLY`で、成功しても`STABLE_POSTCHECK_UNVERIFIED` / `ELIGIBLE_UNVERIFIED`です。full R31 schema、cross-file atomic snapshot、locator resolution、origin、authenticity、consent authority、retention enforcement、trusted time、Intent builder、runtime、GOは未証明です。populated inputとprivate projectionはrepositoryへ含めていません。

Protected Source binding receipt candidateは、将来のprotected runnerがprivate snapshot、trusted clock、immutable locator resolution、6種のevidence、replay reservation、retention/deletion、detached attestationを束縛するためのclosed schemaです。現在はschema/test/runbookだけで、populated receipt、runner、evidence body、trust-root/signature verification、nonce reservation、削除実行はありません。全claimはfalseで、Public Betaは`NO_GO_UNPUBLISHED`です。

Compose minimum / Proxmox segmentedには、preflight、candidate作成、Work Order付きapply、positive/negative verification、rollback、隔離restore演習の6フェーズ契約、schema、標準ライブラリvalidator、公開runbookを追加しています。実環境識別子やsecretを含まないplanning/evidence contractであり、実installer、deploy、restart、restore、provider E2Eのreceiptではありません。

Compose minimumにはさらに、Company DBとEvidence metadata Storeを別service、別internal network、別volumeに置くdata-plane skeletonを追加しています。host port、hardcoded password、mutable image、共有network/volume、unbound file、SQL role/table driftをvalidatorが拒否します。credential非開示resolverはCompose configの生JSONを保存せず、password、image repository、host絶対pathを除いたproject namespace、image digest、network、volume、migration、healthcheckのcandidateを作り、保存後validatorがcurrent shipped revisionとdigestを再照合します。Docker daemonでのimage取得・container起動・migration・health・restart・backup/restoreは未実行です。

local image availability preflightは、匿名化したdaemonと候補digestへ、既存imageのlist/inspect結果を時刻付きsnapshotとして束縛します。read-only queryだけで、image pull/tag/removeやcontainer作成・起動へfallbackしません。saved verifierのPASSはhistorical self-digest/candidate bindingだけで、真正性、freshness、複数queryのatomicity、current stateは証明しません。公開repositoryには実hostのavailability snapshotを含めておらず、現行hostでのlive PASSは未証明です。

clean-install/migration evidence candidateは、external runnerのreported effects、Work Order/target/before-state hash、別executor/reviewer hash、2 serviceのmigrationとpositive/negative DB checksをcandidate/preflightへ束縛します。saved verifierはDocker/DBへ接続せず、`UNATTESTED_EVIDENCE_BINDING_ONLY`までしか返しません。真正性、freshness、atomicity、current state、実行済みclean install/migrationは未証明です。

protected attestation verifierはOpenSSH署名、allowed signer、signed window、nonce snapshotをpoint-in-timeで検査します。one-use evaluatorはさらに外部入力policy digest、allowed-signers hash、nonce-store IDを束縛し、同一SQLite transactionで署名評価とnonce一意予約をcommitします。同時二重評価は一件だけ成功します。ただしcanonical policy adoption、trusted clock、store continuity、reported runtime truth、live installは未証明です。

nonce-store checkpointはreservation rowのdigest集合、store ID、exact schema contractを署名可能なprivate checkpointへ固定します。successor検証ではcurrent store exact match、immediate-parent digest/signature、parent集合のsubsetを確認するため、1リンク内の巻き戻しと同件数差替えを拒否できます。ただし外部pinの権威、trusted clock、branch不存在、全履歴continuity、backup/restoreは未証明です。

recursive checkpoint-chain verifierは、最大1,024 checkpointをself-contained private bundleへ固定し、全embedded digest、独立pinと一致する`ssh-keygen` exact bytesでの全OpenSSH signature、直前parent link、同一store ID、append-only reservation集合を検査します。supplied SQLite storeは最初のopened-object copyと通常SQLite snapshotを相互照合してからcurrent checkpointとのlogical equivalenceを確認します。これはbundleに含まれる提示された1 pathの検証であり、pinned binaryのvendor authority、external anchorの権威、authoritative complete history、parallel branch不存在、actual store continuity、backup作成、restore実行、key rotationは未証明です。

checkpoint-head anchor verifierは、独立pinされたanchor/bundle bytes、bundle内のhead/store/count、短時間window、reviewer policy、OpenSSH署名を束縛します。restore-drill verifierは、成功shapeを持つanchor/source/restored report、distinctなreport/receipt digest、同一checkpoint state、全reported check、runner/reviewer identity hashの不一致を一つの署名済みcandidateへ束縛します。これらはunsigned reportやopaque receipt本文の真正性を再実行せず、external anchorのcanonical authority、trusted clock、complete history、branch不存在、actual backup/restore、physical lineage、protected runner、人物分離、Promotion、Current Truth、Public Beta GOは未証明です。

checkpoint segment-transition verifierは、独立pinされたR20 bundle、prior head、1つのsuccessor checkpointとdetached signature、supplied store、旧/new signer policyとOpenSSH key-blob集合、distinct reviewer policy、最大900秒window、pinned `ssh-keygen` exact bytesを検証します。key-rotationとsame-policyのmodeを分離し、検証したtransition/successor signature bytesのdigestをreportへ残しますが、検証範囲は提示された1境界だけです。canonical anchor authority、trusted clock、complete history、parallel branch不存在、旧鍵失効、鍵侵害不存在、segmentation policy採用、actual store continuity、backup/restore、protected runner、人物分離、Promotion、Current Truth、Public Beta GOは未証明です。

segment transition candidate builderは、prior bundleとsuccessor checkpoint/signatureのexpected digest、旧/new/reviewer policy、mode、ID、最大900秒windowからR22 candidateをdeterministicに新規作成します。strict JSON、R20/R19 structure、immediate parent、store ID、append-only reservation、modeごとのOpenSSH key-blob集合、reviewer hash衝突を署名前に検査し、existing outputを上書きしません。creation reportはsource bindingの構造検査だけを示し、transition/successor signature validity、実key rotation、旧鍵失効、protected execution、人物分離、Promotion、Current Truth、Final Human GO、Public Beta GOを示しません。

## Current boundary

このリポジトリは情報公開面です。Discord や外部 provider の Current Truth、Human Decision、production runtime の代替ではありません。
