# Official Cloudflare OS bounded runtime candidate

This directory pins the first Kotodama review baseline for the official
[Cloudflare OS](https://github.com/cloudflare/cloudflare-os) project.

The selected baseline is the exact current
[deployment starter](https://github.com/cloudflare/cloudflare-os-starter) and
the core gitlink that starter actually names. The separately observed core
repository head is intentionally not substituted for that gitlink. The two
revisions differ, so an upstream drift review is required before changing the
baseline.

Validate the source pin, content-free Gatekeeper projection contract, and saved
local runtime evaluation receipt:

```powershell
python tools/validate_cloudflare_os_candidate.py
python -m unittest tests.test_cloudflare_os_candidate -v
python tools/validate_cloudflare_os_local_runtime_evaluation.py
python -m unittest tests.test_cloudflare_os_local_runtime_evaluation -v
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
Six P1 findings remain, including the pending independent upstream drift review,
one high `nanoid` advisory, Windows-only compatibility mitigation, unproven
observability retention/readback, provider E2E, and supply attestation signature.

Cloudflare OS is an early-access AI productivity environment, not a traditional
computer operating system. Kotodama adopts it as a bounded workspace/Gadget/
Gatekeeper foundation. BecomeOne and Human Intent retain governed meaning;
Proxmox retains the protected local runtime/data plane; Context Gateway retains
query authority. A Gatekeeper result enters Kotodama as a candidate and cannot
promote Current Truth by itself.

`NO_GO_UNPUBLISHED` remains in force.
