# Roadmap to Public Beta

## Published now

- [x] Public repository and project direction
- [x] Explicit incomplete-preview status
- [x] Privacy and publication boundary
- [x] Minimal Company manifest / Block / MOC schemas
- [x] Dependency-free validator and negative tests
- [x] Source-to-Promotion-Candidate governance starter and walkthrough
- [x] Machine-verified flow inputs, Block sequence, dataflow, and MOC binding
- [x] Nine governed record contracts with exact Block-output coverage
- [x] Capability Grant, Change Execution, and human Promotion Decision seams
- [x] Navigation-only Company, Public Release Review, and Incident / Recovery MOCs
- [x] Machine-verified secondary MOC ordered-subsequence contract
- [x] Dependency-free starter initializer with ID/MOC rebinding and overwrite refusal
- [x] Machine-readable customization checklist with review/evidence separation
- [x] Candidate-bound review bundle with exact SHA-256 and byte-size bindings
- [x] Saved-bundle verifier with metadata, digest, and byte-drift detection
- [x] Candidate-bound review workflow with separate Human Decision and Promotion
- [x] Dynamic saved-bundle to Review Request contract with Pack-specific counts
- [x] Dynamic Review Response contract bound to the saved request
- [x] Dynamic Decision Handoff contract bound to the saved review chain
- [x] Public Template Guide, Starter Walkthrough, Status, and Roadmap current-state sync
- [x] Company Pack Catalog, Guided Next Steps, and Schema / Validator / Test Matrix entry navigation
- [x] Fourteen-entrypoint Company Pack CLI Reference with fixed cross-shell help boundaries
- [x] Standard-library-only one-command review-chain smoke with temporary cleanup and closed report
- [x] Clone-to-result five-minute tour with cross-shell commands, report interpretation, and bounded next choices
- [x] README Company OS reader/story map from Vision through current reality to safe first use
- [x] Draft Cloudflare edge candidate with exact Wrangler supply-chain binding and manual-only preview upload guard
- [x] Draft official Cloudflare OS source pin and content-free Gatekeeper-to-Kotodama adapter contract
- [x] Content-free official Cloudflare OS local runtime receipt with exact integrity, 1060 passing tests, loopback readback, and cleanup evidence

## Current Cloudflare candidate

The draft Cloudflare candidate now separates Cloudflare edge from the official
Cloudflare OS project. The edge side remains a content-free Worker candidate;
no preview version has been uploaded. The Cloudflare OS side pins the exact
official starter, the core gitlink used by that starter, and the separately
observed current core head. Because the gitlink and current head differ, an
independent drift review is required before re-pinning.

The local adapter covers observation, protected observation, submitted,
simulated, rejected, and applied Gatekeeper events. It emits Kotodama candidate
records only and cannot authorize execution, Promotion, or Current Truth.

The bounded local runtime evaluation is now complete: exact lock/toolchain
integrity is recorded, 1060 tests pass with 7 explicit skips, all 26 workspace
package projects have build coverage, three stable headers-only HTTP 200
readbacks were observed in `LOOPBACK_ONLY` mode, and cleanup left no evaluation
process or listener. This is local evidence only; provider deployment remains
`not_deployed`.

The next dependency-ordered gates are independent review of the 99-file drift,
remediation or explicit re-pin of the high `nanoid` advisory, default-deny
observability retention/readback, package-manager attestation verification,
paid-plan budget and entitlement, and provider readback/rollback/deletion.
Private Context, backup/restore, production behavior, Discord publication,
Promotion, Current Truth, and Final Human GO remain open.
`NO_GO_UNPUBLISHED` remains unchanged.

## Current public documentation revision

R179 is the latest public documentation revision and the current public
Company OS orientation surface, bound to the published R178 fixed point at
public `main` commit `23e954d4f5bb0dbf4450d768d6b37c2895c97b0b` with tree
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
`d5d6187c7e5e7b6c4fe44e4b60a8aa096d4e8dc0` with tree
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

R177 remains historical as the current public
Template/Company/Blocks/Records/MOCs/starter orientation surface, bound to the
published R176 candidate at public `main` commit
`722345885b8767ee89a28e10f06db2de1ee73ace` with tree
`4282baf4efc394ffa786720f3bfca68d3caf78c0`. The
[Company Pack CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) indexes
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
public `main` commit `722345885b8767ee89a28e10f06db2de1ee73ace` with tree
`4282baf4efc394ffa786720f3bfca68d3caf78c0`. R175 remains historical as the
fourteen-entrypoint Company Pack CLI Reference revision. R174 remains
historical as the review-chain help-boundary revision. R173 remains historical
as the core Company Pack help-boundary revision. R172 remains historical as the
Template/Company/Blocks/Records/MOCs/starter orientation surface, bound to the
published R171 candidate at public `main` commit
`c4a15b0e91a3bacd9125a24e1111521b467c174c` with tree
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
`aca4d22772e84cf7da103b97872c94a04c67ac31` with tree
`008f43ff3f929c990717799fd2bb1b1a52419485`; its commands were
`python -m unittest tests.test_mocs_entry_navigation -v` and
`python3 -m unittest tests.test_mocs_entry_navigation -v`; its POSIX `python3` command was
documented but not executed in the Windows validation environment. R161
remains historical as the Schema / Validator / Test Matrix full review-chain
revision at public `main` commit
`106173b689870be06bb83ed23a144c76ad850b33` with tree
`042c28d389881884af1e8bcde65eca521036db22`. R160 remains historical as the
Company Pack Catalog Quick start revision at public `main` commit
`c70ce092d2303321380bd411410baefd40dfd4fb` with tree
`be9514b9ed1664ef18ed365e40edfdccd96a6e0f`. R159 remains historical as the
Template entry full-chain revision at public `main` commit
`5639e25eb6458733db0687d605496f747939f944` with tree
`fe3a0dfb66e687060cb23efc39d9db68216aee24`. R158 remains historical as the
Company starter full-chain revision at public `main` commit
`eb7f52220eb6e17005a985473dec4b8f62216f46` with tree
`dbf9ccfb47c59b79a865151144cd83f85e065dff`. R157 remains historical as the
README candidate-path revision at public `main` commit
`9107637fa25681ffc3c144aa09a10496ee644a2c` with tree
`116d23e1679b8e8d25ad84a0a0865423f698263b`. R156 remains historical as the
STATUS/ROADMAP provenance revision at public `main` commit
`b9baa3df9d982f9e2a24ea4c0612afba4043acae` with tree
`6649d86fab5018c0812de3197220899d8bb3c5bf`. R155 remains historical as the
first-read Catalog/Next Steps/Matrix entry-navigation revision at public
`main` commit `97dca324e28777d4618abf53804f47db995e5abc` with tree
`9e4ad41d7f79ef6d2d9096ebccaad276ff03615c`. R154 remains
historical as the STATUS/ROADMAP synchronization to R153 at public `main`
commit `f12246af5954735c393108d42b8d2ce873d51406` with tree
`ae1319d42dc1d68fe860d5fbb7aed503e4db63df`. R153 remains historical as the
README Document Map **Review-chain artifact map** entry at public `main` commit
`92b574129ada8d9af2fc2a95e29cdd92590a5dd8` with tree
`b8d981464e18c31e448b3b57d3bb758ad6f67ae2`; it points to
`STARTER-WALKTHROUGH.md#review-chain-artifact-map` and documents Review Bundle,
Review Request, Review Response, and Decision Handoff artifact states and next
handoffs. R152 remains
historical as the STATUS/ROADMAP synchronization to R151 at public `main`
commit `371641e16b3857115be3a52ee32a12117c3bd7f1` with tree
`a6acc28e2455275d294463591f8ffece13ce542f`. R151 remains historical as the
artifact-map entry-surface revision at public `main` commit
`7633f0d4996c1bd210fb68b65fb12ff81c7fe4b7` with tree
`5bcb3b231e1377b3505e51385b57feb04f607361`. R150 remains
historical as the STATUS/ROADMAP synchronization to R149 at public `main`
commit `e15655db50da8106eeb9976f2b2d6c92f4884b43` with tree
`476d36bf3faaf8b9ccb9f8b11e5e6a56680b358a`; R149 remains historical as the
review-chain artifact-map publication at public `main` commit
`ea23f3a31ae68025bf23889beea878d3062adefa` with tree
`0fa942044a2140b243b4a03c831c511b9938332b`. It introduced the review-chain
artifact map for Review Bundle, Review Request, Review Response, and Decision
Handoff, with the Company Pack Catalog entry and before or after the
external-free smoke guidance. The R149 regressions are
[`test_starter_walkthrough_runbook_docs.py`](tests/test_starter_walkthrough_runbook_docs.py)
and [`test_company_pack_catalog_entry_navigation.py`](tests/test_company_pack_catalog_entry_navigation.py).
R148 remains
historical as the first-read review-chain entry wording revision at public
`main` commit `a0c050aa6c7c7f40302e3cd9afffad65a61a3ae5` with tree
`01e5183e3a0c63369afdc437dfb360bf2d070455`. R147 remains historical as the
full review-chain smoke revision. R147 adds the **full
review-chain smoke**: Review Request, Review Response, and Decision Handoff are
saved and freshly verified after the starter Bundle in one temporary,
external-free pack. The executable path is
[`test_public_starter_runbook_smoke.py`](tests/test_public_starter_runbook_smoke.py),
and the public runbook links are synchronized across README, Starter Walkthrough,
Schema / Validator / Test Matrix, and Company Pack Next Steps at public `main`
commit `1abcfd8f835f7d52627c194aacd8a62efb87875b` with tree
`2c8579fa242357dcc28a6d73c95011e1446b6846`. R147 is
documentation/static-regression evidence only; the published surface remains
read-only/candidate-only and `NO_GO_UNPUBLISHED`. R146 remains historical as
the STATUS/ROADMAP synchronization to the R145 schema review-chain revision at
public `main` commit `1abcfd8f835f7d52627c194aacd8a62efb87875b` with tree
`2c8579fa242357dcc28a6d73c95011e1446b6846`; R145 remains historical as the
schema matrix review-chain revision at public `main` commit
`21a4a23586ebfd653a56d7c4b82a778d3791d6ed` with tree
`7a151d62026f4381c4c2734bcbc841797ee9f554`; R144 remains historical as the
Company Pack direct review-chain navigation revision at public `main` commit
`a0ab89f6b5f09deedb695dd478cce9ef421fef77` with tree
`9ed3f7e1cb5884893044e9d5a464c21f758f77ac`; R143 remains historical as the
Company Pack review-chain documentation revision. R141 remains historical as
the Company Pack Guided Next Steps and Installation Lifecycle revision at
public `main` commit `ebcdd003d062c6bc90b5ea546da3d430911bda74` with tree
`ec765b5f824a92d2efdc065b4a225d7779a6e9d2`; the changed surfaces were
[`docs/COMPANY-PACK-NEXT-STEPS.md`](docs/COMPANY-PACK-NEXT-STEPS.md) and
[`docs/INSTALLATION-LIFECYCLE.md`](docs/INSTALLATION-LIFECYCLE.md), covered by
[`test_company_pack_next_steps_entry_navigation.py`](tests/test_company_pack_next_steps_entry_navigation.py)
and [`test_installation_lifecycle_docs.py`](tests/test_installation_lifecycle_docs.py).
R140 remains historical as the
Installation Lifecycle guided-next-steps revision at public `main` commit
`2ad60c6eb24a33e125f658ff0be52a3d53b27fa3` with tree
`55fc6ab347409ffb4444390c67b25fe9b548997f`; R139 remains historical as the
Company Pack guided path revision at public `main` commit
`f1bc6e79159fb175bbd8f575a9e09e8cb724245c` with tree
`3fdd381b3902e6f57c271f8d5fa7a3932ad4adb0`; R133 remains historical as the
README Document Map layer-wording revision at public `main` commit
`15a94c9f041c04994ab1ae00630ae0ea58387276` with tree
`538badff2d305e7b567b312e1ae918579050b44c`. R133 clarified that Status and
Roadmap are orientation, followed by five ideal Company Template layers, while
Catalog onward remains the current read-only/candidate-only path. R132 remains historical as the README Guided
Next Steps entry-navigation revision at public `main` commit
`9f1b3ee5556740abab803f49164bad02bdeda3ae` with tree
`7f9d2ed059cd48e7240d9904e41221e219c47276`; R131 remains historical as the
STATUS/ROADMAP synchronization to R130 at public `main` commit
`0e772cdd4a4a95ad97fee3f60555fb52ebad3f8b` with tree
`b6ffb79781c50bbc07ba7e22405d31e12148be28`. R130 remains historical as the
Company Pack Next Steps entry navigation with a stable ideal/current/smoke
first-stop at public `main` commit
`1667007004f92ac65e0124355fda9b71d81d7e6b` with tree
`aebd38c2012b745333e66348232dc88804181b65`. The changed surface is
[`docs/COMPANY-PACK-NEXT-STEPS.md`](docs/COMPANY-PACK-NEXT-STEPS.md), covered by
[`test_company_pack_next_steps_entry_navigation.py`](tests/test_company_pack_next_steps_entry_navigation.py),
and links the ideal Company Template, Blocks, Governed Records, and MOCs
layers to the current Company Pack Catalog / Starter Walkthrough and planner
schema/regression smoke path. R130 is documentation/static-regression
evidence only; the published surface remains read-only/candidate-only and
`NO_GO_UNPUBLISHED`. R129 remains historical as the STATUS/ROADMAP provenance
synchronization to R128 at public `main` commit
`4d29fca3f8005c9758b78889adab04b2f9614512` with tree
`a178210e7356108a020edd7b9784e24735250105`. R128 remains historical as the
Company Pack Catalog entry-navigation revision. R128 adds Company Pack
Catalog entry navigation with a stable ideal/current/smoke first-stop at
public `main` commit `752fa4b46246110757f01294b559c39412a0b4be` with tree
`60ee3062bcd472562e01f03708cb1fd58c32f7f7`. The changed surface is
[`docs/COMPANY-PACK-CATALOG.md`](docs/COMPANY-PACK-CATALOG.md), covered by
[`test_company_pack_catalog_entry_navigation.py`](tests/test_company_pack_catalog_entry_navigation.py),
and links the ideal Company Template, Blocks, Governed Records, and MOCs
layers to the current Company starter/Catalog and Matrix/Walkthrough/regression
smoke path. R128 is documentation/static-regression evidence only; the
published surface remains read-only/candidate-only and `NO_GO_UNPUBLISHED`.
R127 remains historical as the MOC entry-navigation revision at public `main`
commit `b05db80ec979129d176408870a4f4e4857e43ded` with tree
`ac02e58afb505e8ae4be15c5ad5eda80ae57f318`; R126 remains historical as the
STATUS/ROADMAP synchronization to R125. R125 remains historical as the
Company Starter entry-navigation revision at public `main` commit
`a5d052d425c9236a5cdb118a796b936ba74232aa` with tree
`bca093039d31b3b0f7c595ec91d8224f7419bd7c`. R125 adds Company
Starter entry navigation with a stable ideal/current/smoke first-stop at
public `main` commit `a5d052d425c9236a5cdb118a796b936ba74232aa` with tree
`bca093039d31b3b0f7c595ec91d8224f7419bd7c`. The changed surface is
[`examples/company-starter/README.md`](examples/company-starter/README.md),
covered by [`test_company_starter_entry_navigation.py`](tests/test_company_starter_entry_navigation.py),
and links the Company Template layers, Company Pack Catalog, Schema /
Validator / Test Matrix, Starter Walkthrough, and Public Preview Self-check.
R124 remains historical as the root Template Catalog entry-navigation
revision at public `main` commit `26946de5655835dfdff75a6aef2b8f344d7b7e78`
with tree `2778816782efb41029657a9788463fbe1569f681`; R123 remains historical
as the STATUS/ROADMAP synchronization to R122. R122 remains historical as the
Blocks/Records navigation revision at public `main` commit
`677bd15bec0fdfd22410b237916d05be0d1ca02c` with tree
`299a0248734daec3974b80ff174b4540995f4c47`. The guided path remains
`CANDIDATE_FOR_GOVERNED_REVIEW` and `MATCH`; the plain path remains
`CUSTOMIZATION_REQUIRED` and fail-closed as `BUNDLE_REFUSED`. R121 remains
historical as the Matrix-to-Catalog smoke entry, R120 remains historical as
the STATUS/ROADMAP provenance synchronization to R119, and R119 remains
historical as the Company Pack Catalog Runbook smoke entry at public `main`
commit `b878464eca0571fe293222d372cf417c9e9e1573` with tree
`f5aa3a3fa405c0e5fed4d984921d6ad44dca0bd3`. R118 remains
historical as the Template Guide first-read ideal/current/smoke entry, R117
remains historical as the STATUS/ROADMAP provenance synchronization, and R116
remains historical; R116 added the README Runbook smoke entry immediately
before Quick Start at public `main` commit `2a5a65cdbefc0e1fc33c88771a95443ed52d5960`
with tree `456d5a990ae030699246959e12daf0a4a9cbb6d1`. R115 remains historical
as the Starter Walkthrough smoke entry, R114 remains historical as the
STATUS/ROADMAP provenance synchronization, and R113 remains historical as the
executable public starter runbook smoke (`test_public_starter_runbook_smoke.py`)
and its matrix/test entry. R112 remains historical as the STATUS/ROADMAP
provenance synchronization. R111 remains historical as the schema/validator/test
matrix revision; R111 added the schema/validator/test matrix and its
README/Template Guide/Validation entry links. R110 remains historical as the
stable MOC index and entry-point routing revision, R109 remains historical as
the STATUS/ROADMAP label cleanup, R108 remains historical provenance, and R107
remains historical provenance.
R103 remains the historical README/documentation revision. R100 is the latest
Public Preview Self-check POSIX parity, R89 is the latest Validation Guide
core POSIX parity, R88 is the latest guided onboarding POSIX parity, R87 is
the latest Template Guide and Catalog POSIX parity, and R86 is the latest
STATUS/ROADMAP provenance before R92. The published R91 candidate is public
`main` commit `b071ce9b2fd4167c8ac199bcd1983b64224fba43` with tree
`c6c7bafebd9cca6bdc37365af560b2f11f9fc7e8`.

R68 is the historical README contract synchronization. R80 is the latest
starter navigation usability synchronization in that historical wave. R78 is
the latest installation lifecycle usability synchronization in that wave. R76
is the latest Template Guide usability synchronization in that wave. R74 is
the latest documentation synchronization for schema/validator parity. R58
synchronizes this roadmap with the current public Company Pack surface at that
historical checkpoint.
The published review chain remains read-only/candidate-only: it binds exact
bytes, saved Pack-specific counts, and false claims, but it does not create
Human approval, runtime authority, Promotion, Current Truth, or Public Beta
access. R54, R55, R56, R57, R58, and R62 extend the public documentation/test
surface only. R64, R65, R66, R70, R72, R73, and R74 extend local
schema/validator parity checks
without changing the Company Pack surface or runtime claims. R62 remains the
latest navigation synchronization in that historical wave; R74 is the latest
parity synchronization for the resolved Compose candidate in that wave. R68
added the README Voice rotation ideal/current contract while preserving the
runtime boundary. R107 is historical provenance for the Company Pack surface
label; it is not a current-state claim.

R82 is the latest runbook usability synchronization in that historical wave.
R83 is the latest Validation Guide usability synchronization in that wave. R84
is the latest README command parity synchronization in that wave. R85 is the
latest onboarding command parity synchronization in that wave. R86 through R91
extend the public documentation/test surface with provenance and POSIX parity;
each revision keeps the ideal/current distinction and the read-only/
candidate-only boundary explicit. None adds runtime, Voice, Discord, provider,
authority, Promotion, Current Truth, Final Human GO, or Public Beta access.

R100 added the standalone Public Preview Self-check cross-navigation. R101 added
the Installation Lifecycle standalone reading entry from Template Guide ->
Company Template -> Blocks -> Governed Records -> MOCs, then Catalog -> Starter
Walkthrough before profile selection. R102 synchronized STATUS/ROADMAP
provenance. R103 added the README ideal/current layer map from Template Guide ->
Company Template -> Blocks -> Governed Records -> MOCs before Catalog -> Starter
Walkthrough -> Public Preview Self-check -> Installation Lifecycle. R103 is
the historical README layer-map candidate at public `main` commit
`92a67b1bd0b450b549590d915b24dd983bb3eb7a` with tree
`a8437da05a2688e64129458eb604a6f604deb59c`. R104 synchronized STATUS/ROADMAP
provenance to R103. R105 added the direct Installation Lifecycle link in the
Template Catalog Runtime profiles row and is public `main` commit
`615fdbab66ed1ad3fa779fb762dc8a27eca857d1` with tree
`3b881f999704e1c3e3c3f4c0929fd019c6f163ed`. These revisions are documentation/
test hardening only; they retain read-only/candidate-only,
`NO_GO_UNPUBLISHED`, and no runtime/Voice/provider/Promotion/Current Truth/
Final Human GO claim.

R106 synchronized STATUS/ROADMAP provenance to R105, which remains historical.
R107 aligned the Company Template ideal order to Human Intent -> Blocks ->
Governed Records -> MOCs -> validator/review before optional runtime profile
selection and is public `main` commit
`de163c060006d50545229fd8ef092f97c583074d` with tree
`a9679c8f2ff04146b8ddaf1803ee094b56b5d4bc`. R108 synchronizes this provenance
surface. These are documentation/test hardening only; read-only/candidate-only
and `NO_GO_UNPUBLISHED` remain in force, and runtime, Voice, provider,
Promotion, Current Truth, and Final Human GO remain outside scope.

- [x] Template/Company/Blocks/Records/MOCs/starter navigation synchronization
      with ideal/current usage, dynamic Pack-count guidance, and the
      read-only Review Request -> Review Response -> Decision Handoff path
- [x] Company Template ideal/current usage documentation synchronization
      between README, STATUS, Starter Walkthrough, and Template Guide
- [x] Installation lifecycle first-read and profile-selection guidance
      for Company Pack-only, `compose_minimum`, and `proxmox_segmented`
- [x] README first-stop guide and bounded profile-selection navigation
- [x] Company Pack Catalog first-stop sequence with bounded no-runtime guidance
- [x] Template-pack path canonicalization aligned with the published manifest schema
- [x] Installation-lifecycle purpose schema/validator parity for non-whitespace values
- [x] Compose binding integer schema/validator parity for integer-valued JSON numbers
- [x] Resolved Compose binding integer schema/validator parity for finite
      non-negative integer-valued JSON numbers
- [x] Installation-lifecycle fixed-boolean schema/validator parity
- [x] Compose security fixed-boolean schema/validator parity
- [x] Resolved Compose nested boolean schema/validator parity
- [x] Template Guide ideal/future versus shipped MOC distinction
- [x] Installation lifecycle ideal/current and command/path clarity
- [x] Starter ideal/current navigation and Installation Lifecycle profile guidance
- [x] README Voice rotation ideal/current contract synchronization with an
      explicit no-runtime and no-Public-Beta boundary
- [x] Runbook ideal/current and PowerShell/POSIX command parity synchronization
- [x] Validation Guide ideal/current and PowerShell/POSIX command parity synchronization
- [x] README Quick Start, Review Bundle, and runtime-candidate command parity synchronization
- [x] Starter onboarding customization, planning, Catalog, validator, and review-bundle command parity synchronization

- [x] Sanitized Compose minimum and Proxmox segmented lifecycle contracts
- [x] Machine-checked preflight/apply/verify/rollback/isolated-restore evidence requirements
- [x] Public runbooks separating planning contracts from live installation receipts
- [x] Secret-free Compose minimum Company DB / Evidence metadata Store skeleton
- [x] Exact-byte skeleton validator with host-port, password, image, isolation, and SQL negative tests
- [x] Credential-free resolved Compose candidate with project, image, network, volume, migration, and digest binding
- [x] Saved resolved-candidate validator with password-independent digest and tamper refusal
- [x] Read-only local image availability preflight with anonymized host and exact candidate binding
- [x] Saved availability-snapshot verifier limited to historical self-digest/candidate binding, with authenticity/freshness/atomicity/current-state claims denied
- [x] Unattested clean-install/migration evidence-candidate schema and saved verifier with role-separated hash bindings and complete reported DB checks
- [x] OpenSSH protected-attestation verifier and SQLite-backed one-use nonce reservation candidate with fail-closed trust/clock/continuity boundaries
- [x] Signed private nonce-store checkpoint with exact logical snapshot and immediate-parent append-only verification
- [x] Recursive private checkpoint-path verification with all signatures and supplied-store logical equivalence
- [x] Signed checkpoint-head candidate and restore-drill reported-evidence binding with exact private report/receipt digests
- [x] Signed checkpoint segment-transition candidate with same-policy and key-rotation boundary verification
- [x] Deterministic new-file-only private segment-transition candidate builder with R22 round-trip verification
- [x] Read-only Public Preview self-check aggregating starter structure, Catalog, customization boundaries, and false-claim checks

## Candidate contract included in this revision

- [x] [Read-only Source binding candidate](docs/SOURCE-BINDING-VERIFIER-CANDIDATE.md) with strict bounded parsing, stable terminal reread, non-reflective refusal, and non-emitted R30 projection digest. This line describes revision contents, not publication, protected verification, or Public Beta GO.
- [x] [Protected Source binding receipt candidate](docs/PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md) schema with private snapshot, clock, locator, evidence, replay, retention/deletion, and detached-attestation roles. This is an unpopulated schema contract, not protected execution or a verified receipt.
- [x] [Protected execution request / handoff candidate](docs/PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md) with opaque runner/input refs, bounded evaluation window, fixed stop/rollback shape, expected receipt, and independent-verification handoff. This is schema-only; no execution is requested or accepted.

## Runtime profiles still requiring live evidence

- [x] Executable Compose data-plane candidate manifest (not a live receipt)
- [ ] Protected, authenticated, fresh digest-pinned image staging and clean-install/migration receipt
- [ ] Exact Proxmox guest/service candidate and segmented deployment receipt
- [ ] Candidate-bound restart, rollback, and isolated restore receipts
- [ ] External checkpoint-head canonical authority, old-key revocation, adopted segmentation policy, and scope-matched tested restore execution/continuity
- [ ] PostgreSQL Company DB and Evidence Store setup/restore E2E

## Required before opening access

- [ ] Fresh candidate-bound Voice cutover and rollback evidence
- [ ] Real 15-minute rotation, transcription post, and deletion evidence
- [ ] Speaker attribution and Voice-to-Verified-Handoff E2E
- [ ] Separate-person verification and three-persona E2E
- [ ] Protected reconciliation and independent verification receipts
- [ ] Candidate-bound Final Human GO

この一覧は進捗を透明にするためのものです。チェック項目は、対応する検証 receipt が揃うまで完了扱いにしません。
