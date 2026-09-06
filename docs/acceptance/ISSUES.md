# GitHub対応事項の照合

[68項目へ](README.md)

観測: 2026-09-06T02:43:57.707015+00:00。open Issue全25件の本文を読み、受入と運用義務へ対応付けた。本文中の古いPR/SHA/件数は過去の記載であり、現在のheadは[PR snapshot](github-snapshot.json)を使う。既存Issueを完了・閉鎖する操作は行っていない。

| Issue | 対応R | 残る義務 |
|---|---|---|
| [#2 [Cloudflare] Hybrid edge + official Cloudflare OS adoption epic](https://github.com/Kotodama-Project/Kotodama-project/issues/2) | R43, R45, R46, R47, R49, R50, R53, R56, R57, R58, R61, R63, R64, R65 | 二plane順序、provider/data/cost/production boundary、independent E2E/Human decision |
| [#3 [Cloudflare OS][CFOS-01] Inventory account, zone, plan, and current services read-only](https://github.com/Kotodama-Project/Kotodama-project/issues/3) | R43, R49, R58 | opaque locator、plan/cost、service status、unknown/stopのauthenticated readback |
| [#4 [Cloudflare OS][CFOS-02] Verify guarded Worker preview-version pipeline](https://github.com/Kotodama-Project/Kotodama-project/issues/4) | R43, R44 | exact SHA/manual upload、Environment/token、HTTP/log/quota/rollback |
| [#5 [Cloudflare OS][CFOS-03] Add Tunnel and Access ingress with default-deny policy](https://github.com/Kotodama-Project/Kotodama-project/issues/5) | R43, R53, R58 | outbound-only/default-deny、auth negatives、direct-origin拒否、separate apply/readback |
| [#6 [Cloudflare OS][CFOS-04] Integrate Context Gateway and search through a metadata-safe edge contract](https://github.com/Kotodama-Project/Kotodama-project/issues/6) | R43, R44, R53, R56, R58 | Gateway-only scope、consent/cache/body-free logs、timeout/backend negatives |
| [#7 [Cloudflare OS][CFOS-05] Evaluate AI Gateway and Vectorize under data and cost gates](https://github.com/Kotodama-Project/Kotodama-project/issues/7) | R49, R65 | synthetic-only data/retention/cache/region/cost/deletion/rollback |
| [#8 [Cloudflare OS][CFOS-06] Prove observability, quota, rollback, and promotion gates](https://github.com/Kotodama-Project/Kotodama-project/issues/8) | R49, R63 | content-free logs、quota/stop、data rollback、exact candidate promotion |
| [#9 [Cloudflare OS][CFOS-07] Decide request-body processing, residency, and log boundary](https://github.com/Kotodama-Project/Kotodama-project/issues/9) | R43, R49, R56, R57, R58 | payload class/region/log/cache/retention/cost decision before private body |
| [#10 [Cloudflare OS][CFOS-02A] Prove protected deployment identity, runner, and receipt sink](https://github.com/Kotodama-Project/Kotodama-project/issues/10) | R43, R46, R49, R58 | least privilege、reviewer/runner、nonce/clock、durable receipt |
| [#11 [Official Cloudflare OS][CFOS-UPSTREAM-05] Review pinned drift and prove local runtime](https://github.com/Kotodama-Project/Kotodama-project/issues/11) | R40, R45, R47, R48, R50, R51, R52 | current-head drift、exact dependency、independent review、#12-16/#9/#10/#19 |
| [#12 [Official Cloudflare OS][CFOS-SECURITY-06] Remove vulnerable nanoid from pinned production graph](https://github.com/Kotodama-Project/Kotodama-project/issues/12) | R48 | independent remediation/adopted pin、zero vulnerable graph、review |
| [#13 [Official Cloudflare OS][CFOS-SUPPLY-10] Verify pnpm registry signatures and provenance](https://github.com/Kotodama-Project/Kotodama-project/issues/13) | R40, R48 | trust root/source workflow identity、independent review、upstream adoption |
| [#14 [Official Cloudflare OS][CFOS-WINDOWS-07] Replace local shim with a reviewed cross-platform contract](https://github.com/Kotodama-Project/Kotodama-project/issues/14) | R47, R48, R50 | support lane、cross-platform bytes/launcher、negative tests/cleanup |
| [#15 [Official Cloudflare OS][CFOS-QUALITY-12] Budget frontend chunks and eliminate lint warning drift](https://github.com/Kotodama-Project/Kotodama-project/issues/15) | R48 | baseline、non-increasing budgets、growth checks、warning disposition |
| [#16 [Official Cloudflare OS][CFOS-WORKERD-13] Define the Proxmox workerd production-support boundary](https://github.com/Kotodama-Project/Kotodama-project/issues/16) | R47, R50, R51, R52, R53 | hosted vs Proxmox、ops lifecycle、support owner、independent operational E2E |
| [#19 [Governance] Rebind main protection and security controls after organization transfer](https://github.com/Kotodama-Project/Kotodama-project/issues/19) | R42, R58, R59, R62, R63, R67 | neutral checks、review/force-push/deletion、security settings、admin readback |
| [#20 [Documentation] Refresh STATUS and ROADMAP to the current public control plane](https://github.com/Kotodama-Project/Kotodama-project/issues/20) | R37, R44, R54, R62, R67 | refresh exact heads/runs/date、candidate/public/settings/human lanes、smoke and history |
| [#23 ops: confirm ownership and lifecycle for dormant or legacy repositories](https://github.com/Kotodama-Project/Kotodama-project/issues/23) | R64, R68 | owner/lifecycle/dependencies/successor/support for seven repositories; no archive before readback |
| [#24 [Epic] Complete BecomeOne → Kotodama dual-repository migration](https://github.com/Kotodama-Project/Kotodama-project/issues/24) | R37, R39, R54, R55, R56, R57, R59, R60, R61, R62, R63, R66, R68 | canonical ledger、four terminal classes、license/history/privacy、immutable export、canary/rollback、zero residual |
| [#25 [Governance] Decide public license and record export provenance](https://github.com/Kotodama-Project/Kotodama-project/issues/25) | R48, R55, R59, R62, R63, R68 | rightsholder/license/notices/SBOM/provenance manifest/independent review |
| [#26 [Architecture] Fix public package and CLI namespace before control-plane cutover](https://github.com/Kotodama-Project/Kotodama-project/issues/26) | R55, R68 | public/private namespace、compatibility bridge、consumer inventory、collision/canary/rollback |
| [#28 [Release] Build an immutable kotodama-core candidate with SBOM and provenance](https://github.com/Kotodama-Project/Kotodama-project/issues/28) | R39, R48, R55, R68 | clean build/allowlist/SBOM/signature/provenance/vulnerability disposition/artifact pin |
| [#30 [Migration] Linearize public sibling Drafts after PR #18](https://github.com/Kotodama-Project/Kotodama-project/issues/30) | R39, R42, R62, R66, R67, R68 | retarget/rebase exact parents、manifest reconciliation、rerun checks、independent review; no merge authorization |
| [#31 migration(A019): re-author provider-neutral registry schemas](https://github.com/Kotodama-Project/Kotodama-project/issues/31) | R36, R41, R66, R68 | six rows、schema/negative/history receipt、#25/#30/private receipt gates |
| [#32 migration: prove restart-safe agent continuity and converge swarm receipts](https://github.com/Kotodama-Project/Kotodama-project/issues/32) | R35, R36, R37, R38, R39, R41, R42, R54, R60, R61, R62, R66, R68 | separate resume/instance/ledger、lease/idempotency/tamper、no fallback/private import、blocked aggregate |

#20と#21のSTATUS/ROADMAP整理は、このclosing candidateにも現在の表示を追加する。既存#21 branchをrootから上書きせず、採用時には#30の順序に従い重複変更を照合する。#19/#25の管理・rights判断や、#24の移植完了をこの文書PRで閉じない。
