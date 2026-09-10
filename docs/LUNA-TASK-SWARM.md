# Luna Task Swarm

この文書は、Kotodama の owner-bound Task を Luna worker と協働させるときの入口です。対象は、bounded な work packet、peer 通信、native host と CLI の実行境界、独立 review です。Task registry、authority 発行、Task completion、Promotion、Current Truth の書き換えはこの導線の責務ではありません。

この文書の例は synthetic shape です。実際の Task、actor、path、digest、ID、owner grant は、実行時に owner が供給した値へ置き換えます。過去の prototype の件数や pass は、現在の runtime receipt として再利用しません。

## 最初の一手

作業開始前に、次の packet を一つの immutable な入力として束縛します。タイトル、モデル名、ディレクトリ名、過去の assistant completion だけから値を推測しません。

```json
{
  "packet_version": "kotodama.task-swarm/v1",
  "source": {
    "ref": "owner://source/<opaque-ref>",
    "digest": "<64-lowercase-hex>",
    "observed_at": "<UTC timestamp>"
  },
  "task": {
    "task_id": "<owner task>",
    "revision": 1,
    "context_digest": "<64-lowercase-hex>",
    "owner_ref": "<owner>",
    "active_home": "<exact execution home>",
    "authority_ref": "<owner authority>",
    "capability_ref": "<sender grant>",
    "expires_at": "<UTC timestamp>",
    "status": "active"
  },
  "objective": "<one bounded outcome>",
  "ownership": {
    "writer": "<actor>",
    "worktree": "<exact worktree>",
    "paths": ["<exact file or directory>"],
    "exclusive_keys": ["<owner-resolved resource>"]
  },
  "dependencies": ["<accepted result or artifact ref>"],
  "budget": {"N": 8, "C": 4, "W": 3, "V": 2, "depth": 1, "max_depth": 1},
  "actor": {"actor_ref": "<actor>", "epoch": 1, "invocation_ref": "<invocation>"},
  "deadline": "<UTC timestamp>",
  "acceptance": ["<criterion id and observable result>"],
  "validation": ["<command or readback and expected result>"],
  "stop": ["expiry", "binding drift", "stale epoch", "scope mismatch", "budget exhaustion"],
  "return": "typed worker/reviewer packet"
}
```

`source` は、依頼または owner が束縛した根拠の locator/digest です。`task` の値は `runtime/task_swarm/protocol.py` の Task fields と一致し、actor fields は `actor_ref/epoch/invocation_ref/actor_status` を含みます。owner が値を返せない、期限が既に過ぎている、または exact ownership が決まらない場合は編集や dispatch を始めず、`LUNA_PACKET_MISSING` または適切な stop を返します。

## 実行 route を決める

native host と CLI は異なる証拠型です。route の選択は packet の入力ではなく、現在の host で capability を確認した後に行います。

| route | 実行 | 必須の観測 | できないとき |
| --- | --- | --- | --- |
| native host | 現在 callable な `spawn_agent`/spawn、follow-up、send、wait、interrupt 相当の live surface | 親 call が返した child ID、child の実際の completed turn、effective model/effort/permissions、parent-child provenance | `LUNA_UNSUPPORTED_COORDINATOR_SURFACE`。CLIへ黙って置換しない |
| deterministic CLI | `python tools/task_swarm.py --help` と owner が許可した `examples/task-swarm-demo` | local command、入力 binding、出力 digest、transport/state の観測。これは local evidence | native runtime や provider/live acceptance と称さない |
| authorized Codex CLI | owner が明示的に許可した `CodexBackend` route | owned PID/creation time → stdout の thread UUID → exact rollout cwd と completed turn、requested/observed model/effort/sandbox | ambiguous/mismatched runtime を拒否し、権限や global config を広げない |

native の callable surface が一つも無い場合は、native の success として記録しません。CLI demo の成功も、native child や provider/live state の証明ではありません。TOML role、`name`、nickname、静的 model、設定 flag は requested policy であり、実際にその role が loaded された証拠ではありません。parent の model は route 選択で変更せず、Luna role を選択したときだけ child の要求値を `gpt-5.6-luna`/`max` とします。child が parent の live override を継承する可能性があるため、実効 permission をそのターンで読んで返します。

## bounded dispatch と ownership

各 worker に一つの ownership cell を渡し、exact path と owner-resolved `exclusive_keys` を packet に書きます。ファイル名、役割名、モデル名、Task title から grant を推測しません。scheduler の `SwarmState` は plan の jobs、依存関係、lease、attempt、epoch、budget を保持します。`claim` の一回は成功した仕事だけでなく failed start も attempt を消費します。

`depth` は現在の node、`max_depth` は許可された上限です。child は `parent.depth + 1` に置き、descendant が許可されていない depth1 worker は spawn しません。`N` は global attempts、`C` は同時実行、`W` は wave、`V` は verifier reserve です。未使用予算を勝手に増やさず、期限と owner expiry の早い方を守ります。lease の回復は identity が実際に dead と確認できた場合だけ行い、unknown/missing identity を死んだことにしません。

新しい invocation は新しい epoch/token を受けます。古い epoch の report、send、ACK、reply は stale として拒否されます。続行時に最初の attempt ID、spawn receipt、child UUID を再利用しません。root が runtime provenance をまだ束縛していない場合、worker は unknown のまま返します。

## peer 通信の意味

`PeerTransport` と MCP surface の意味を混同しないようにします。送信者と受信者の両方で Task scope、recipient grant、current epoch/invocation、expiry を再検証します。idle recipient に送ることはできますが、sender が終了した後に accepted message を読む場合も同じ scope と grant が必要です。

| 段階 | 事実 | 終了条件 |
| --- | --- | --- |
| `stored` | sender grant 内で message が一度保存された | `peer_send` の envelope、message ID、digest、expiry |
| `acked` | 宛先が `peer_ack` を明示し、payload digest と epoch を一致させた | sender の `peer_status` に `ack` が現れる |
| `replied` | ACK 済み parent へ元 sender 宛ての `peer_reply` が保存された | `reply_ids` が現れる |
| `reply_acked` | reply の宛先が reply を ACK した | `unacked_reply_ids` が空になる |
| `expired/stale` | TTL、Task expiry、epoch、scope が成立しない | stop と gap を返す |

`peer_receive` は未 ACK の envelope を読むだけで、ACK は inbox message ではありません。sender が ACK を待つときは `peer_status(message_id)` を使います。`read_message` は restart 後の audit 用に、同じ actor に宛てられた ACK 済み parent も返します。`peer_reply` は元の sender に返し、parent が recipient に宛てられ ACK 済みであることを要求します。idempotency key の同一 replay は同じ論理 message の ingress provenance と expiry を保ち、別 recipient/parent/payload/scope で同じ key を使うと拒否します。

MCP の write は `peer_send`、`peer_ack`、`peer_reply` だけです。payload は UTF-8 JSON と digest-addressed local store の上限に従い、credential-shaped content を保存・echo しません。`wait_seconds` は finite 0..20 の範囲です。設定ファイルや呼び出し元の文章だけで open-world action を追加しません。

## report、review、acceptance

worker の report は candidate です。次の三つを区別します。

- `candidate`: artifact/evidence locator と digest があり、review へ渡せる
- `needs_data`: 依存・source・runtime receipt が不足しており、Task は続行できない
- `identity_conflict`: actor、epoch、invocation、Task scope、runtime provenance が一致しない

review job は reported dependency を読めますが、同じ worker の自作結果を独立検証したことにはなりません。reviewer は criterion ごとに次を返します。

```json
{
  "criterion_id": "A5",
  "status": "passed|failed|blocked|not_run",
  "evidence_locator": "<exact path/ref>",
  "gap_reason": "<required when blocked or not_run>"
}
```

`SwarmState.report` の戻りは reported candidate、`accept(run_id, job_id, result_digest, verification_ref, owner_ref)` は owner/controller のみの受入です。`accept` に渡す evidence は owner adapter が先に読み、digest と current owner を照合します。reported、quiescent、全 worker の終了、transport delivery は Task completion ではありません。

snapshot の `run_state` は `active`、`waiting_owner`、`quiescent`、`budget_exhausted` を区別します。未受入の report は `waiting_owner` であり、`quiescent` は work が静止した状態に過ぎません。どちらも owner の Task を完了へ進める receipt ではありません。

## stop と gates

host clock が deadline/TTL を計算します。UTC offset 付き時刻、finite limit、non-negative wait、Task/actor expiry を public boundary ごとに検証します。表示上のローカル日付が変わったことから valid な UTC window の終了を推測しません。

次のいずれかで route を止め、原因と次の owner action を typed packet に残します。

- owner binding の欠落、drift、期限切れ、`status` 不可
- scope、recipient、capability、source digest、context digest の不一致
- stale epoch/token、unknown identity、ambiguous runtime provenance
- global/per-job attempt、concurrency、pending message、fan-out の上限
- native callable surface の欠落、CLI output の UUID/cwd/turn ambiguity
- review criteria の未実行、verification digest の不足、owner accept の不在

`LOCAL_PASS` はローカル bytes と checks の証拠です。device、provider、public、Human の権限や結果を暗黙に上位へ昇格させません。今回の構成・静的 validation に `DEVICE_PASS`、`PROVIDER_PASS`、`PUBLIC_PASS`、`HUMAN_GO` は含まれません。

## typed return

worker と verifier は、文章だけでなく次の形を返します。root は未観測の attempt/runtime/provenance を埋めるまで accepted と扱いません。

```yaml
status: completed | partial | failed | blocked
attempt: <supplied or null>
objective: <packet objective>
ownership:
  task_id: <owner task>
  actor_ref: <actor>
  paths: [<exact paths>]
  epoch: <observed or null>
changed_files: []
checks:
  - id: <criterion>
    result: passed | failed | blocked | not_run
    observed: <short factual result>
artifacts: []
evidence_locators: []
unknowns: []
gap_reason: null
integration_notes: <root handoff>
gate_ceiling: LOCAL_PASS
```

期限後の作業は `late_excluded` として返し、期限内の成功へ混ぜません。`partial` や `blocked` は不足した work を明示するための状態であり、Task owner の判断を先取りしません。

## local checks と evidence ceiling

Python3.12で、依存を導入してから明示的なlocal fixtureを実行します。通常のテストとoffline demoはモデルを呼びません。

```powershell
python -m pip install -r requirements-task-swarm-test.txt
python -m pytest -q tests -k task_swarm
python tools/task_swarm.py demo --root work/offline-demo --allow-local-fixture
python -c "import tomllib, pathlib; [tomllib.loads(p.read_text(encoding='utf-8')) for p in pathlib.Path('.codex/agents').glob('kotodama_luna_*.toml')]; print('TOML_OK')"
```

実際のCodex/Lunaを呼ぶ場合は、ログイン済みCodex CLIの実行ファイルを明示します。次のコマンドは3 workersと別のverifierを使い、最大6試行・同時3実行のfixtureを開始します。認証情報は引数へ渡しません。

```powershell
python tools/task_swarm.py demo --root work/live-demo --allow-local-fixture --live --allow-peer-writes --codex-executable <codex実行ファイルのパス>
```

既存の出力先は上書きしません。`work/`内のowner入力・メッセージ本文・詳細runtime記録はprivateな実行証拠として保持し、Gitへ追加しません。`summary.json`はlease tokenを含まない要約、`protocol-verification.json`は実際のpayload/ACK対応です。モデルの最終文だけで成功にせず、owner受入直前にcandidate・receipt・stdout・runtime出力を読み直します。

Skill/TOMLの静的検査は、runtimeの自動選択やproject roleがhostへ読み込まれたことを証明しません。native routeは実hostのツールと親call/child UUIDを観測します。CLI routeの`peer_*`や永続mailboxがnative hostにも存在すると仮定しません。local fixtureをCompany authorityやdeployment proofと呼びません。

`budget.verifier_reserve`はreview用に保護する試行数です。省略時はreview job数（総予算以下）を予約し、workの再試行はその枠を使えません。code・Skill・roleのハッシュを実行入力へ固定し、途中で変更された場合はそのrunを止めて新しい入力で検証します。

## 配置された role

- `.codex/agents/kotodama_luna_worker.toml` — 一つの work cell、typed report、bounded peer communication
- `.codex/agents/kotodama_luna_verifier.toml` — independent criterion review、runtime/provenance/receipt の照合

二つの role は `name`、`description`、`developer_instructions`、`model = "gpt-5.6-luna"`、`model_reasoning_effort = "max"` を要求します。実効 sandbox、approval、tool availability は親の live turn から観測します。role の静的設定だけで read-only や実際の Luna execution を主張しません。

## 公式参照

role の配置と custom agent の field は [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) を、CLI の stdio、startup、timeout、tool allow-list は [MCP for CLI](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) を基準にします。これらの説明は requested configuration の根拠であり、現在の host で role が loaded されたこと、child spawn が callable であること、実効 permission が read-only であることの証明ではありません。
