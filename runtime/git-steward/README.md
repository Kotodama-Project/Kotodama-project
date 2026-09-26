# Git Steward — executable coordination candidate

This is the internal coordination kernel for the Cloudflare OS Git role, not a
running LLM, public API, deployed Gadget, GitHub App, or second Task authority.
The registered role remains `candidate` / `proposal_only` with no runtime receipt.
See [the system design](../../docs/GIT-STEWARD-AND-WORK-CELLS.md).

## Included

| File | Responsibility |
|---|---|
| `coordinator.mjs` | Provider-neutral, synchronous work-cell state machine and candidate assessment |
| `sqlite-store.mjs` | Atomic journal adapter for SQLite-backed Cloudflare Durable Object storage |
| `git-observer.mjs` | Node-only, read-only comparison of immutable Git commits |
| `coordinator.test.mjs` | Negative/positive tests, disk restart, simultaneous SQLite writers, real Git worktrees |
| `business-simulation.test.mjs` | Correction, dependency invalidation, clock, legacy-journal regressions and rehearsal entry point |
| `business-rehearsal.mjs` | Synthetic scenario runner with real temporary Git, SQLite and controlled child processes; not a production executor |
| `../../tests/test_git_steward_runtime.py` | Entry point discovered by the existing Python regression workflow |

No package installation is needed for this slice. Use Node >=22.13, Git and
Python >=3.10. Node's built-in SQLite may emit an experimental warning.

```sh
node --test --test-reporter=tap runtime/git-steward/coordinator.test.mjs runtime/git-steward/business-simulation.test.mjs
python -m unittest discover -s tests -p 'test_git_steward_runtime.py' -v
node runtime/git-steward/business-rehearsal.mjs > business-rehearsal.json
```

The original suite has 37 Node tests; the business suite adds focused regressions
and a multi-condition rehearsal. The Python entry point is
one launcher test, not another set of independent cases. It fails rather
than silently skipping when Node/Git/SQLite are unavailable. Full-repository
regression and hosted CI must be reported separately.

## Protected integration, not a public method

Inside the existing OS integration, a trusted repository-scoped Durable Object
can compose these modules:

```js
import { GitSteward } from './coordinator.mjs';
import { CloudflareSqliteStore } from './sqlite-store.mjs';

// ctx.storage belongs to ONE object for the canonical repository identity.
// trustedPolicy is operator-owned, not a Gadget/HTTP request field.
const steward = new GitSteward(new CloudflareSqliteStore(ctx.storage), trustedPolicy);
// Only after native identity, live Work/Grant revision and source ACL checks:
const projection = steward.execute(authenticatedPrincipalRef, admittedCommand, Date.now());
```

This snippet is composition guidance, not a complete Gatekeeper implementation.
Do not export `execute(actor, command, now)` directly to HTTP, MCP or a Gadget.
The caller must not select its identity, repository partition, role, policy,
attestation issuer, clock or capability scope. Transport authentication is not
business authorization. Every read/replay also requires observation authorization.
Bound raw request bytes and depth before JSON parsing; the kernel's closed object
validation is an additional guard, not a network input parser.

`transactionSync` keeps the journal, global fence, state change and request
fingerprint atomic. No `await`, model call, Git command or network operation goes
inside that transaction. Use one repository identity across people, workspaces,
providers and target branches; partitioning by agent would defeat reservations.
The SQLite adapter is tested against a real local SQLite database with a shim
for the documented storage interface, NOT in workerd or a deployed Durable Object.

## Work-cell specification

A cell binds `id`, existing `work_ref` and `work_revision`, `grant_ref`,
`context_digest`, `producer_ref`, independent `reviewer_ref`, `target_ref`,
immutable `base_sha`, `write_paths`, `read_paths`, `conflict_keys`, `depends_on`.
One Work revision has one cell. Sub-work must be admitted by the existing Work
owner, not invented as a second task ledger here. Dependencies reference cells
already admitted; forward, missing and self edges are refused. This ordering
makes cycles unrepresentable. Dependency completion means observed integration,
not a model claiming it finished or a candidate passing tests.

Write admission uses case-sensitive repository syntax. `src/a.ts` is exact and `src/` is a
subtree; globs, absolute paths, whitespace, traversal and `.git` are refused.
Both old and new paths of renames must be checked. Write/write and read/write
scope intersections conflict; read/read does not. Semantic `conflict_keys`
reserve things such as a shared API contract even when paths are disjoint.
Reservations conservatively compare case aliases and file/directory ancestors:
`src` and `src/a.ts` cannot be held by different writers. This does not make
`src` a directory write grant. These are coordination rules, not filesystem
access controls. Symlinks, short names and other filesystem aliases still need
normalization/enforcement in the actual executor before use.

## Commands and evidence

Every command includes `request_id`, `type`, `cell_id`. The trusted policy names
the coordinator, receipt attester, required check names/issuers, and budgets.

| Command | Authorized role | Additional fields / effect |
|---|---|---|
| `add` | Coordinator | `spec`; admit a queued cell for the authoritative current Work revision; a higher revision invalidates older cells and their consumers |
| `claim` | Assigned producer | `base_sha`, `lease_ms`; reserve scopes and increment global epoch |
| `renew` | Same producer | `epoch`, `lease_ms`; only before expiry and within total runtime budget |
| `unknown` | Same producer | `epoch`; preserve uncertain delivery without a second dispatch |
| `stop` | Coordinator | Request stop; does not prove a worker stopped |
| `stopped` | Trusted attester | `epoch`, `receipt_ref`, `disposition` (`queued`/`cancelled`); release only after external proof |
| `submit` | Same producer | `epoch`, base/head/tree SHAs, `diff_sha256`, `changed_paths`, `receipt_ref` |
| `verify` | Independent assigned reviewer | Exact base/head/diff; complete required checks and `receipt_ref` |
| `assess` | Trusted attester | Exact `base_sha`, `head_sha`; returns candidate readiness, NEVER merge permission |
| `integrated` | Trusted attester | Exact base/head, observed `merge_sha`, `receipt_ref`; records a merge that already happened |

Check records contain `name`, `issuer_ref`, `head_sha`, `conclusion`, `receipt_ref`.
Every configured check must be present exactly once with the trusted issuer,
exact candidate head and `success`. Do not collapse a GitHub display name into a
unique check identity: the protected adapter maps real App/workflow/context
identities to the configured opaque issuer and name. A receipt reference is not
proof by itself. That adapter must fetch and authenticate receipts, source
classification, actual changed paths, principals and current grants; none of
those external services is implemented in this kernel.

`branch` and `workspace_ref` in a projection are proposed allocation names. No
Git branch or worktree is created by the coordinator. The real executor must
accept only its fenced assignment and check the fence again at every admitted
write/push operation. No push, merge, force-push, reset, cleanup, provider call,
model invocation, branch-protection mutation or GitHub credential is included.

## Recovery is deliberately conservative

`add` is not a last-speaker-wins decision API. A protected Work owner must resolve
the authoritative current revision before calling it. Same-Work revisions must
increase; an admitted correction atomically marks older queued cells cancelled
and other nonterminal cells stopping. Their scopes stay reserved until attested
stop. Even disjoint paths cannot run two versions of the same Work. Consumers
of a corrected dependency are invalidated transitively and need a new Work-owner
binding; historical integrations and prior context digests remain in the journal.
The projection carries `work_revision`, `context_digest`, `superseded_by` and
`invalidated_by`. This does not implement live Work/Grant/ACL verification.

An expired lease projects `reconciling`; it does not free the scope. A request to
stop projects `stopping`; it is not cancellation confirmation. An external
attester must prove the old executor is stopped or effectively fenced, reconcile
possible writes and preserve its output before sending `stopped`. Reassignment
then receives a higher global epoch; results from the previous epoch are refused.
GitHub operations with ambiguous delivery must be read back before retrying.

Candidate and verified cells keep reservations until observed integration or
confirmed stop. `max_concurrent` therefore bounds all held cells, not just model
processes. This trades throughput for safety in the initial slice. Same-ID replay
returns the current projection, never a cached authorization to use an expired
lease. A reused ID with different contents or actor is refused.

Journal policy is immutable and checked on every command. Accepted commands,
replays and business refusals persist the trusted clock high-water mark; refused
business mutations and deduplication entries roll back. Invalid input rejected
before journal admission and corrupt/binding-mismatched journals do not mutate
the store. Time moving backwards is refused. Capacity is finite (4 MiB journal, at most 8192 remembered commands,
configured cell/attempt/concurrency/lease/time limits). The store does not evict
idempotency records to make room. Planned retention/compaction, protected
anti-rollback anchors and operator-approved policy migrations remain follow-up
work. Never delete/reset a journal while an old executor can still write, and
never restore an old epoch as though it were a fresh repository. Do not mistake
this operational journal for a cryptographically authenticated evidence ledger.

When the target branch or a prerequisite merge changes the base, stop/reconcile
the old cell and have the canonical Work owner issue an updated revision/cell
and context. The kernel does not silently rebase an old assignment or claim that
its tests cover the new target.

## Git observer and isolation

`observeDiff(repositoryPath, baseSha, headSha)` requires full 40-character Git
SHA-1 commit IDs, a non-shallow repository and an ancestral base. It returns the
head tree, both sides of renamed/deleted paths and a SHA-256 of the generated
binary/full-index patch. SHA-256-format Git repositories are not supported in
this slice. Subprocess output/time are bounded; no shell or network is used.

Only run it against a trusted, disposable local checkout with operator-owned Git
configuration and object storage. Disabling external diff/text conversion and
inherited Git environment is not a sandbox against malicious local Git config,
objects, alternates or executable replacement. Do not accept arbitrary `.git`
directories from a caller. Patch hashes bind the exact emitted bytes, not a
promise that every Git version/configuration emits identical patch formatting.

Git worktrees separate working directories but share repository refs/objects.
They do not protect credentials, the main checkout or another agent from hostile
code. Use isolated clones/containers/VMs and an admitted write gateway for actual
untrusted execution. Humans outside the coordinated path may still move refs;
provider readback, strict branch protection or a correctly integrated merge queue
must catch this. Checking the candidate head alone is not an atomic target-base
CAS. No merge queue is enabled by this change.

## Rollback / remaining acceptance

This candidate uses journal v2. A v1 journal is refused with
`JOURNAL_VERSION_UNSUPPORTED` and preserved, not silently upgraded or erased.
Migration requires stopped/fenced old executors, preserved records, authoritative
current Work rebinding and a non-regressing epoch/anti-rollback plan. Neither an
empty replacement database nor a code revert proves that migration. See the
[business rehearsal and staged production proposal](../../docs/BUSINESS-REHEARSAL.md).

Disable new admissions, retain the journal, request stop, verify/fence active
workers, reconcile external writes and preserve receipts before reverting the
candidate code. Do not perform `reset --hard`, `clean`, or automatic worktree
removal against user work. Closing/reverting this source PR does not revoke a
separate provider grant.

Required next acceptance: native Gadget/Gatekeeper identity and observation ACL;
protected live Work/Grant/context admission; real executor fence and stop/readback;
GitHub receipt/check identity mapping; base-change/merge-queue race handling;
workerd deployment tests; multi-user cross-workspace access; restore/retention;
independent review. Local tests establish none of those deployment claims.
