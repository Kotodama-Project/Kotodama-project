# OpenManus Proxmox Runtime Candidate

OpenManusをKotodamaのbounded executorとして専用Proxmox KVM guestへ隔離するためのruntime candidateです。

- Design: [`docs/OPENMANUS-PROXMOX-EXECUTOR-CANDIDATE.md`](../../docs/OPENMANUS-PROXMOX-EXECUTOR-CANDIDATE.md)
- Machine-readable candidate: [`examples/executor-runtime/openmanus-proxmox.json`](../../examples/executor-runtime/openmanus-proxmox.json)
- Schema: [`schemas/executor-runtime-candidate.schema.json`](../../schemas/executor-runtime-candidate.schema.json)
- Existing Proxmox lifecycle: [`docs/PROXMOX-SEGMENTED-RUNBOOK.md`](../../docs/PROXMOX-SEGMENTED-RUNBOOK.md)

## Current state

`candidate_only`です。このdirectoryの存在はVM作成、OpenManus install、provider接続、browser起動、restart、rollback、restore、production adoptionを証明しません。

## Initial boundary

- dedicated KVM guest
- 4 vCPU / 8 GiB RAM / 60 GiB disk as an initial hypothesis
- concurrency 1
- task-scoped workspace only
- outbound through an allowlisted gateway
- direct Proxmox management-plane access denied
- no direct Current Truth promotion
- no Capability Grant mutation

## What must be added before protected execution

- exact upstream/dependency/browser package lock and digests
- private guest/segment/service-identity locators
- adapter transport implementation
- health and cancellation contract
- positive + negative network tests
- restart / rollback / isolated restore receipts
- benchmark and independent verification evidence

Do not place guest IDs, hostnames, IP addresses, storage IDs, credentials, API keys, private prompts, or private source bodies in this public directory.
