# Runtime Candidates

公開templateを実行環境へつなぐ、secret-freeな候補artifactです。

| Candidate | Included | Current evidence |
|---|---|---|
| [Discord minimum runtime](../docs/DISCORD-RUNTIME.md) | local ASR、継続Live会話、Luna、限定Task worker | 公開本体への統合候補。連続実聴と既存組織owner接続は未受入 |
| [Compose minimum data plane](compose-minimum/README.md) | Company DB、Evidence metadata Store、分離network/volume、SQL schema | exact-byte validator、negative tests、offline Compose config only |
| [Cloudflare edge](cloudflare-edge/README.md) | content-free Worker、manual preview upload guard（current `main` tip only）、Wrangler integrity binding | local static/runtime smoke candidate only; no provider upload |
| [Official Cloudflare OS](cloudflare-os/README.md) | exact starter/core pin、content-free Gatekeeper projection adapter、saved local runtime receipt | 1060-test `PASS_LOCAL_RUNTIME_WITH_GAPS`; no provider execution or production claim |
| [Luna Task swarm](../docs/LUNA-TASK-SWARM.md) | owner binding、bounded scheduler、ACK/reply/status、Codex CLI adapter、project Skill | opt-in local fixture、concurrency/restart/negative tests。Company authorityやdeploymentを発行しない |
| [Git Steward coordination core](git-steward/README.md) | work-cell reservation、lease/epoch fence、independent reviewer、integration record、SQLite journal adapter、read-only Git observer | 41 synthetic Node tests（real SQLite・temporary Git）via `tests/test_git_steward_runtime.py`（Linux required check; Windows not yet）; no model call、Git push、GitHub/provider write or deployment |
| [OpenManus Proxmox executor](openmanus-proxmox/README.md) | OpenManus bounded executor、Proxmox KVM isolation、request/result authority boundary | pinned upstream candidate、JSON Schema、static invariants; no live VM/deployment evidence |

`runtime/`に存在することはdeploymentの証明ではありません。各候補は`example`または`candidate_only`から始まり、対象revisionへ束縛したWork Order、runtime health、negative test、restart、rollback、backup/restore receiptが揃うまでlive/verifiedとは呼びません。Public Beta は `NO_GO_UNPUBLISHED` のままです。
