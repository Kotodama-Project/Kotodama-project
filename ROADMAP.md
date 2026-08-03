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

## Current public documentation revision

R68 is the latest README contract synchronization. R76 is the latest Template
Guide usability synchronization. R74 is the latest documentation
synchronization for schema/validator parity. R58 synchronizes
this roadmap with the current public Company Pack surface.
The published review chain remains read-only/candidate-only: it binds exact
bytes, saved Pack-specific counts, and false claims, but it does not create
Human approval, runtime authority, Promotion, Current Truth, or Public Beta
access. R54, R55, R56, R57, R58, and R62 extend the public documentation/test
surface only. R64, R65, R66, R70, R72, R73, and R74 extend local
schema/validator parity checks
without changing the Company Pack surface or runtime claims. R62 remains the
latest navigation synchronization; R74 is the latest parity synchronization
for the resolved Compose candidate. R68 added the README Voice rotation
ideal/current contract while preserving the runtime boundary. R58 remains the
current Company Pack surface label.

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
- [x] README Voice rotation ideal/current contract synchronization with an
      explicit no-runtime and no-Public-Beta boundary

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
