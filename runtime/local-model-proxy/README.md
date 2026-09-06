# Local model bridge for official Cloudflare OS

This private loopback service connects one operator-selected local model to the
official OS's existing OpenAI-compatible chat transport. The pinned OS currently
exposes that transport through its Ollama provider option. This is a compatibility
route for the pinned revision, not a claim that the upstream server runs Ollama.

The operator supplies a private JSON configuration containing `upstream` (an
HTTP(S) `/v1` URL), `model`, `port`, `expiresAt`, `maxRequests` and an existing
`stateRoot` directory. The bridge binds only `127.0.0.1`. Never put provider
credentials, endpoint configuration or account state in this source directory.

```text
node runtime/local-model-proxy/server.mjs PRIVATE_CONFIG_JSON
node --test tests/node/test_local_model_proxy.mjs
```

Only model listing and chat completions are exposed. The model list describes
the configured model; a real response is required to verify provider readiness.
Requests use one fixed upstream, one fixed model, one concurrent invocation,
at most 4096 output tokens and a bounded invocation budget. The expiry and
metadata receipt survive a normal restart. A retained writer lock or interrupted
receipt requires reconciliation before another writer starts. Redirects,
provider/admin routes, unknown request fields, multiple choices and `store:true`
are refused. `store:false` is accepted for the official OS's normal request.

The receipt records request hashes, sizes and outcomes. It contains no prompts,
responses or credentials. A completed transport does not verify a generated
artifact or complete its Task. Repeated model requests are not certified as
exactly-once; callers still need their own durable effect/idempotency contract.

There is no internet-facing authentication layer. Use only the operator's
private local transport, with an explicitly scoped SSH/Unix-socket boundary if
the OS runs on another machine. OS accounts and their own model configurations
remain the application authorization boundary. Do not expose the listener as a
shared public service or treat it as a source-ACL gateway.

The PC and its transport must remain available. Missing connectivity, exhaustion
and expiry return errors; there is no cloud fallback. Provider capacity is a
separate operational constraint, so begin with short serial requests.

The evaluation patch set in `../cloudflare-os-kotodama/patches/` binds a
conservative Qwen context window and strict Document block inputs to one exact
upstream revision. Apply it only after verifying its source hashes and preserving
preimages. Existing Gadget instances retain their own code and require a
separate update; changing a Blueprint does not migrate stored Gadgets.
