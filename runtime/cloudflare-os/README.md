# Official Cloudflare OS source candidate

This directory pins the first Kotodama review baseline for the official
[Cloudflare OS](https://github.com/cloudflare/cloudflare-os) project.

The selected baseline is the exact current
[deployment starter](https://github.com/cloudflare/cloudflare-os-starter) and
the core gitlink that starter actually names. The separately observed core
repository head is intentionally not substituted for that gitlink. The two
revisions differ, so an upstream drift review is required before changing the
baseline.

Validate the source pin and the content-free Gatekeeper projection contract:

```powershell
python tools/validate_cloudflare_os_candidate.py
python -m unittest tests.test_cloudflare_os_candidate -v
```

The command reads local candidate files and runs synthetic metadata-only
events. It does not clone or execute Cloudflare OS, install dependencies, use a
credential, call a provider API, enable billing, upload a Worker or Dynamic
Worker, or publish anything.

Cloudflare OS is an early-access AI productivity environment, not a traditional
computer operating system. Kotodama adopts it as a bounded workspace/Gadget/
Gatekeeper foundation. BecomeOne and Human Intent retain governed meaning;
Proxmox retains the protected local runtime/data plane; Context Gateway retains
query authority. A Gatekeeper result enters Kotodama as a candidate and cannot
promote Current Truth by itself.

`NO_GO_UNPUBLISHED` remains in force.
