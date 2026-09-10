# Runtime Candidates

公開templateを実行環境へつなぐ、secret-freeな候補artifactです。

| Candidate | Included | Current evidence |
|---|---|---|
| [Compose minimum data plane](compose-minimum/README.md) | Company DB、Evidence metadata Store、分離network/volume、SQL schema | exact-byte validator、negative tests、offline Compose config only |
| [Luna Task swarm](../docs/LUNA-TASK-SWARM.md) | owner binding、bounded scheduler、ACK/reply/status、Codex CLI adapter、project Skill | opt-in local fixture、concurrency/restart/negative tests。Company authorityやdeploymentを発行しない |

`runtime/`に存在することはdeploymentの証明ではありません。各候補は`example`または`candidate_only`から始まり、対象revisionへ束縛したWork Order、runtime health、negative test、restart、rollback、backup/restore receiptが揃うまでlive/verifiedとは呼びません。
