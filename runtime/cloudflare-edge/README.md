# Cloudflare Edge Profile Candidate

## Previewの承認と読み戻し（#4）

起動前に#3の対象account／zone、#10の実行者・承認者・secret・private receipt保存先、
Work Orderと費用範囲を確認します。既存preview aliasがあれば元versionとの対応をprivateに
保存し、衝突が不明なまま上書きしません。8つのruntime／provider bindingが必要です。
workflowの両jobはUbuntu 24.04に固定し、validatorはdispatch revisionから読みます。

承認するcandidate SHAは現在のmainと同じ値です。workflowは承認前と承認後にmain tipを
再検査し、変わっていれば止まります。起動はownerが承認したWork Orderの下で行います。
versions uploadは本番routeやproduction versionへのpromotionを行う工程ではありません。

upload後はprivate作業領域でHEADのheaderだけを確認します。JWTなし401、別host403、
認証された未知path404、health／version200が対象です。設定欠落の503を成功へ読み替えません。
bodyを保存せず、version ID、host、認証header、raw response headerは公開receiptへ入れません。
元記録はprivateに置き、公開候補は対象commit、version／headerのdigest、時刻、statusだけです。

[preview receipt schema](../../schemas/cloudflare-preview-receipt.schema.json)を次で検査します。

```text
python -B tools/validate_cloudflare_preview_receipt.py examples/cloudflare-preview/synthetic-receipt.json --expected-candidate aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

例のSHAとprobeは合成値です。実確認ではWork Orderに束縛したSHAを指定します。
CLIはlocal JSONの整合とrevisionを確認するだけで、upload／再照会／Human approvalを
検証しません。失敗statusや未実行probeも記録できますが、reported_checks_matchはfalseです。

失敗時は新しい公開／route変更へ進まず、previewへの許可を止めます。本番versionとrouteに
変化がないことを読み戻し、元aliasの復旧や生成versionの保持／削除は対象をprivate記録で
特定して別の承認下で行います。保存先のrestoreと実rollbackは#8／#10の受入として残ります。

Environment・runner・clock/nonce・private保存先とrestoreの条件は
[保護された実行とreceipt保存先](../../docs/CLOUDFLARE-PROTECTED-RECEIPTS.md)で確認します。

## リクエスト期限

Access key取得、Gatewayへの要求、response／review bodyの読取には、同じ5秒のrequest期限を
適用します。期限超過は内容を含まない504、caller取消は499で終了し、fetch signalとreaderを
取消します。タイマーcallbackが遅れても完了時の時刻で判定し、遅いJWKSをcacheへ入れません。
bodyはbyte上限に加えてchunk数を制限します。POSTの応答が期限を超えた場合、Gatewayでの
commitが無かったという意味にはなりません。再送前に同じhandoffのrevisionを読み戻します。
tenant／purpose／consentと内容を含まない処理記録は[Gateway v3](../local-review-gateway/README.md)で検査します。実provider受入は#6の未完事項です。
incoming requestの取消通知には、[公式のRequest.signal設定](https://developers.cloudflare.com/workers/configuration/compatibility-flags/#enable-requestsignal-for-incoming-requests)
に従いenable_request_signalを明示します。compatibility dateだけで有効とは仮定しません。

This directory is a secret-free deployment candidate for the Cloudflare-facing
edge of Kotodama. It is not the Kotodama data plane and it does not replace the
Proxmox segmented profile.

## Boundary

- Cloudflare: public edge routing, Access JWT verification, a bounded Voice
  review projection, and deployment metadata.
- Proxmox: search runtime, Context Gateway, databases, Evidence Store, n8n,
  OpenClaw, and private administration.
- Tailscale or an equivalent private path: operator access while the
  Cloudflare Access/Tunnel candidate is not independently verified.

The Worker exposes `/healthz`, `/version`, `GET /voice/review`, and
`POST /voice/review/{safe-document-id}`. Every route requires both the exact
bound preview hostname and a valid RS256 Cloudflare Access JWT with an exact
issuer and audience. Missing, malformed, forged, expired, not-yet-valid, or
wrong-audience JWTs fail closed. A different host, including a base
`workers.dev` or version-origin hostname, is denied before any upstream fetch.
Cached Access keys are refreshed once immediately when a verified token names
an unknown `kid`, so normal signing-key rotation does not wait for cache expiry.

The Voice route can call only the configured HTTPS Context Gateway origin:

- `GET /voice/review?q=...` maps to `GET /v1/voice/handoffs?q=...`;
- `POST /voice/review/{id}` maps to
  `POST /v1/voice/handoffs/{id}/review`;
- review actions are limited to `accept`, `edit`, and `reject`;
- review request streams are cancelled as soon as they cross the 16 KiB body
  limit, including when `Content-Length` is absent or understated;
- the verified Access `sub` and `email` claims are copied into fresh outbound
  actor headers, so caller-supplied spoof headers are never forwarded;
- the Gateway response is reconstructed through an allowlist;
- raw audio, transcript, credential, source body, and private corpus keys are
  rejected, not silently forwarded;
- evidence is digest-URN only and authority remains `candidate_only`.

The Worker has no search, storage, AI, Voice, ASR, database, or canonical-state
binding. Context Gateway remains mandatory; direct search access is absent.
Every other path fails closed.

## Runtime bindings

The preview requires the following values to be supplied through the protected
deployment environment. Values must not be committed or printed:

- `ACCESS_ISSUER`: exact HTTPS Cloudflare Access issuer origin;
- `ACCESS_AUD`: exact Access application audience;
- `PREVIEW_HOST`: exact Access-protected aliased preview hostname, without a
  scheme or path;
- `CONTEXT_GATEWAY_ORIGIN`: exact HTTPS Context Gateway origin;
- `CONTEXT_GATEWAY_CLIENT_ID`: Access service-token client identifier;
- `CONTEXT_GATEWAY_CLIENT_SECRET`: Access service-token secret.

If any value is absent or malformed, all routes return `503`; a host mismatch
returns `403`, and an invalid Access assertion returns `401`. Uploading code
does not by itself configure Access, Tunnel, the Context Gateway, or these
runtime values.

## Candidate checks

```powershell
python tools\validate_cloudflare_edge_candidate.py
python -m unittest tests.test_cloudflare_edge_candidate -v
C:\path\to\node.exe --test tests\node\test_cloudflare_voice_review.mjs
```

```bash
python3 tools/validate_cloudflare_edge_candidate.py
python3 -m unittest tests.test_cloudflare_edge_candidate -v
node --test tests/node/test_cloudflare_voice_review.mjs
```

The GitHub workflow first checks a lowercase 40-hex commit and requires it to
equal the current remote tip of `main`, the protected default branch that
receives changes through pull requests and the required checks; a historical ancestor is refused. Validator code is checked out from
the exact `github.sha` dispatch revision on `main`, rather than re-resolving a
mutable default-branch name during the run. Candidate Python or tests are not
executed in that unprivileged validation job. After Environment approval, the
upload job repeats the exact remote-tip check before Wrangler runs, closing
branch-advance drift during the approval wait. It can upload a preview version
with the deterministic `voice-review` preview alias only after a manual
dispatch from `main` and approval by the
`cloudflare-preview` GitHub Environment. It does not deploy a production route.

The trusted validator checks the default configuration and every named
environment for forbidden provider/data bindings. The default and preview
environments disable the base `workers.dev` route; only preview URLs are
explicitly enabled for the preview environment. A preview-only R2, KV, AI,
service, route, or similar binding is refused, and an environment-specific
observability/logging override must remain disabled until provider retention
has separate evidence. It also requires the Access verification, exact two
bounded fetch sites (Access JWKS and Context Gateway), Voice projection denial,
and no direct search/provider endpoint markers.

Before any run, configure that Environment with required reviewers, prevent
self-review where available, restrict deployment branches to `main`, and add
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and the six declared preview
runtime bindings as Environment secrets. After the verified Wrangler install,
the upload step writes those six values to one permission-restricted temporary
JSON file, passes it only to `versions upload --secrets-file`, and removes it
on every step exit. Missing values fail before upload. Values must never be
committed, printed, or passed as command-line values. These protections and
secret values are not configured or verified by this public candidate.

Wrangler is fixed to `4.120.0`. The upload job downloads the exact npm tarball,
then trusted code verifies its npm SHA-512 integrity, legacy npm shasum, and the
recorded SLSA subject SHA-512 before installing it with lifecycle scripts
disabled. The trusted, hash-bound
[`wrangler-runner-package.json`](wrangler-runner-package.json) and
[`wrangler-runner-package-lock.json`](wrangler-runner-package-lock.json) are
copied beside that verified tarball and installed with `npm ci`; the validator
checks the lock entry and registry dependency closure before any upload secret
is exposed. Only that verified package path is invoked with upload credentials.
The top-level binding lives in [`wrangler-integrity.json`](wrangler-integrity.json);
the SLSA attestation signature is not independently verified here. These local
checks do not prove provider execution or deployment.
Observability and logs are disabled by default until provider retention and
content-free readback have a separate receipt.

A version-only upload does not create or verify the Cloudflare Access
destination and does not supply a Context Gateway implementation. Bind Access
to the exact preview Worker in a separate candidate-bound provider step, then
prove unauthenticated denial and authorized `/healthz` and `/version` readback.
Voice review routes remain blocked until the configured Context Gateway is
implemented and independently reachable.

Before running the workflow, bind an exact commit to a Work Order and verify:

1. the API token is limited to the intended Cloudflare account and Worker;
2. the account remains within the approved plan and cost ceiling;
3. the preview URL is protected by Cloudflare Access before private data is
   introduced;
4. logs contain no request body, authorization header, personal identifier, or
   private source content;
5. rollback is the previous known-good Worker version;
6. Public Beta remains `NO_GO_UNPUBLISHED`.

## Non-claims

The files here do not prove Cloudflare account ownership, Access/Tunnel/DNS
configuration, runtime secret binding, preview deployment, production
deployment, Context Gateway origin reachability, real Voice data, provider E2E,
rollback, Promotion, Current Truth, or Public Beta GO.
