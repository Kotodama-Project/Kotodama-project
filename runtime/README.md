# Runtime Candidates

公開templateを実行環境へつなぐ、secret-freeな候補artifactです。

| Candidate | Included | Current evidence |
|---|---|---|
| [Compose minimum data plane](compose-minimum/README.md) | Company DB、Evidence metadata Store、分離network/volume、SQL schema | exact-byte validator、negative tests、offline Compose config only |
| [GPT-Live Voice-to-Work](live/README.md) | 公式Live接続契約、VC別制御、話者境界、静かな応答、実行権限・再実行防止 | 36 synthetic/local tests。Discord/Live/PCの実接続・本番統合は未検証 |

[GPT-Live採用・移行方針](../docs/GPT-LIVE-ADOPTION.md)では、クラウド音声の第一選択をGPT-Live-1とし、GrillUの汎用化、VC別worker、Slack/Teamsの別作業を定義しています。方針の採用と本番稼働の証明は別です。

`runtime/`に存在することはdeploymentの証明ではありません。各候補は`example`または`candidate_only`から始まり、対象revisionへ束縛したWork Order、runtime health、negative test、restart、rollback、backup/restore receiptが揃うまでlive/verifiedとは呼びません。
