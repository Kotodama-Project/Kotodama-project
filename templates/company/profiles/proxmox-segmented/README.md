# Proxmox Segmented Profile

service role、network、identity、storage/restore境界を分離するruntime候補profileです。

- [Machine-readable lifecycle contract](../../../../examples/installation-lifecycle/proxmox-segmented.json)
- [Lifecycle overview](../../../../docs/INSTALLATION-LIFECYCLE.md)
- [Proxmox runbook](../../../../docs/PROXMOX-SEGMENTED-RUNBOOK.md)
- [OpenManus bounded executor candidate](../../../../docs/OPENMANUS-PROXMOX-EXECUTOR-CANDIDATE.md)

OpenManus candidateはこのprofileをhost isolation boundaryとして再利用します。初期状態では専用KVM guestからProxmox management planeへの直接accessを許可せず、KotodamaのWork Order / Capability Grant / Verification / Promotion境界の後ろで交換可能なexecutorとして扱います。

公開例はsanitized role/evidence contractです。guest ID、hostname、IP、storage ID、credential、live deployment/restart/restore receiptは含みません。
