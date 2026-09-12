# Runtime Candidates

公開templateを実行環境へつなぐ、secret-freeな候補artifactです。

| Candidate | Included | Current evidence |
|---|---|---|
| [Compose minimum data plane](compose-minimum/README.md) | Company DB、Evidence metadata Store、分離network/volume、SQL schema | exact-byte validator、negative tests、offline Compose config only |
| [Cloudflare edge](cloudflare-edge/README.md) | content-free Worker、manual preview upload guard、Wrangler integrity binding | local static/runtime smoke candidate only; no provider upload |
| [Official Cloudflare OS](cloudflare-os/README.md) | exact starter/core pin、content-free Gatekeeper projection adapter、saved local runtime receipt | 1060-test `PASS_LOCAL_RUNTIME_WITH_GAPS`; no provider execution or production claim |

`runtime/`に存在することはdeploymentの証明ではありません。各候補は`example`または`candidate_only`から始まり、対象revisionへ束縛したWork Order、runtime health、negative test、restart、rollback、backup/restore receiptが揃うまでlive/verifiedとは呼びません。Public Beta は `NO_GO_UNPUBLISHED` のままです。
