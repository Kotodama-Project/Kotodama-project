# Official Cloudflare OS local runtime evaluation

This receipt advances the official Cloudflare OS candidate from source-only
inspection to a bounded, content-free local runtime result. It does **not**
advance the provider, production, private-data, or Public Beta gates.

The machine-readable receipt is
[`runtime/cloudflare-os/local-runtime-evaluation.json`](../runtime/cloudflare-os/local-runtime-evaluation.json).
It is bound to the previously published official starter and its exact core
gitlink. The separately observed current core remains drift, not an ambient
upgrade.

## Result

| Check | Observed result |
|---|---|
| Source baseline | exact starter plus its exact core gitlink |
| Upstream drift | 99 files; independent review still pending |
| Dependency installation | frozen lockfiles, lifecycle scripts ignored, credentials scrubbed |
| Tests | 1060 passed, 7 explicitly skipped, 0 failed in the accepted matrix |
| Build | 26 workspace package projects covered; 24 official recursive plus 2 Windows-adapted equivalents |
| Runtime | `LOOPBACK_ONLY`, content-free, headers-only; three stable HTTP 200 responses |
| Cleanup | 0 evaluation processes and 0 evaluation listeners remaining |
| External effects | 0 provider API mutations, uploads, deployments, DNS, Access, credentials, billing, posts, or merges |
| Findings | P0/P1/P2 = 0/6/2 |
| Public Beta | `NO_GO_UNPUBLISHED` |

The accepted Windows adapter source is
[`tools/cfos_pnpm_runtime_windows_shim.cs`](../tools/cfos_pnpm_runtime_windows_shim.cs).
It binds an exact Node executable and evaluation root, permits only the build
and local `wrangler dev` command families required by the observed upstream
scripts, and rejects dependency installation and remote Wrangler mode with
exit 64. It is an evaluation compatibility boundary, not an upstream-supported
production launcher.

## Reproduce the saved receipt validation

These commands read only public candidate files. They do not clone upstream,
install packages, read a credential, start a listener, or call Cloudflare.

```powershell
python tools/validate_cloudflare_os_local_runtime_evaluation.py
python -m unittest tests.test_cloudflare_os_local_runtime_evaluation -v
```

```bash
python3 tools/validate_cloudflare_os_local_runtime_evaluation.py
python3 -m unittest tests.test_cloudflare_os_local_runtime_evaluation -v
```

The validator checks schema closure, exact source-pin continuity, the shim
digest, finding counts, zero external effects, loopback/body/cleanup boundaries,
and public-safety markers. It validates a saved observation; it does not rerun
the 1060 upstream tests or establish freshness on another machine.

## Open P1 findings

1. The 99-file starter-pinned-to-current-core drift has no independent review.
2. The pinned production graph contains `nanoid` 3.3.16 with one high advisory;
   the patched line begins at 3.3.17.
3. Windows needs the local launcher adapter and an LF checkout for byte-stable
   fixture tests; this is only a local mitigation.
4. Observability and explicit error-reporting defaults lack a Kotodama retention
   and readback receipt.
5. Workers, Access, storage, Browser Rendering, Dynamic Worker Loaders, paid
   entitlement, rollback, and provider E2E remain unproven.
6. The exact pnpm archive digest is bound, but its published attestation
   signature was not independently verified.

The two P2 findings are production frontend chunk-size warnings and 64 lint
warnings across four rules.

## Next dependency-ordered gate

Close the independent drift review, remediate or explicitly re-pin the high
advisory, and make telemetry/retention default-deny. Only then create a separate
exact Work Order for a public/synthetic provider preview with budget, quota,
automatic stop, readback, rollback, and deletion evidence.

Local workerd does not prove a Cloudflare account deployment. Synthetic content
does not prove private Context safety, data residency, retention, backup, or
restore. Cloudflare OS Gatekeepers do not replace Kotodama Human Decision, Work
Order, Promotion, or Current Truth. `NO_GO_UNPUBLISHED` remains.
