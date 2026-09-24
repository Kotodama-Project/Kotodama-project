---
name: kotodama-luna-swarm
description: Run bounded Kotodama Task swarms with owner-bound work packets, truthful native-versus-CLI routing, observable peer receipts, and independent review. Use when a Kotodama task needs Luna worker coordination or a swarm communication handoff; use the ordinary implementation workflow for a single-agent change.
---

# Kotodama Luna Task Swarm

日本語で依頼を受けたら、まず `Task packet` を日本語で要約し、Task owner が持つ目的・権限・停止条件の範囲だけを実行する。通信、worker の終了、モデルの自己報告は Task 完了を意味しない。完了は owner の検証と受入で決まる。

詳細な field、envelope、status、route の定義は [LUNA-TASK-SWARM.md](../../../docs/LUNA-TASK-SWARM.md) を読む。ここでは毎回の判断順だけを示す。

## 担当と実行面

受け取ったpacketが`may_spawn=false`なら、あなたは割り当て済みのworker/verifierです。自分の仕事・通信・返却だけを行い、下記のcoordinator向けdispatchやCLIの再起動を繰り返しません。既にユーザーまたはownerが許可した同じ範囲について、追加の許可を要求しません。

coordinatorは最初に指定されたrouteを選びます。`codex_cli`はこのリポジトリのMCP `peer_*`と永続journalを使います。native hostでは、その時点で公開されたspawn/send/follow-up/wait相当を使い、Task/context digestとアプリケーションのmessage IDを含む明示ACK・返信を対応づけます。native hostに`peer_*`が存在すると仮定しません。nativeメッセージの再起動後の再取得を確認できない場合は、その耐久性を未検証とし、明示的に選ばれたCLI routeの証拠と分けます。

## 手順

1. **Task packet を束縛する。** `source`、Task の `task_id/revision/context_digest/owner_ref/active_home/authority_ref/capability_ref/expires_at`、担当する exact paths と `exclusive_keys`、依存関係、`N/C/W/V`、depth、期限、受入基準、validation、停止条件、返却形式を揃える。省略が作業の認可または完了判定を不可能にするなら、`LUNA_PACKET_MISSING` を返し編集しない。packet と owner binding が対応していれば完了。

2. **選んだrouteの実能力を確認する。** nativeでは現在のhostのspawn/follow-up/send/wait相当がcallableかを確認し、親callから実child IDとcompleted turnを観測する。CLIでは実行ファイル、owner input、MCP起動、stdoutとruntimeの対応を検査する。選んだrouteがなければ`LUNA_UNSUPPORTED_COORDINATOR_SURFACE`としてそのlaneを止め、別routeへ黙って切り替えない。TOML、task名、件数、静的model名をruntime proofにしない。

3. **bounded dispatch を行う。** 各 child に一つの ownership cell と入力だけを渡し、`parent.depth + 1` と packet の予算内に収める。親の model は保持し、role を選んだ specialist は `gpt-5.6-luna`/`max` を要求する。実際の親 call が返した child ID だけを provenance として使い、CLI に native parent/child ID を作らない。dispatch receipt、期限、epoch が保存されれば完了。

4. **通信状態を receipt で終端する。** `peer_send` は delivery receipt、`peer_ack` は明示的な ACK、`peer_reply` は ACK 済み parent への返答として扱う。`peer_receive` に ACK を探しに行かず、送信者は `peer_status` の `ack/reply_ids/unacked_reply_ids` を読む。`stored → acked → replied → reply_acked` と `expired/stale` を区別し、同じ idempotency key の再試行は元の ingress provenance を保つ。sender/recipient の Task scope、current epoch、invocation、expiry が検証できれば完了。

5. **worker report と review を分離する。** worker は `candidate`、`needs_data`、`identity_conflict` のいずれかを evidence locator/digest 付きで返す。worker の「成功」や配信済みメッセージを受入と呼ばない。独立 reviewer は criterion ごとに `passed|failed|blocked|not_run` と exact locator を返し、自分の work を自分で検証しない。owner adapter が evidence を読み、`accept` を呼んだときだけ accepted candidate になる。review packet と owner acceptance が別 identity でそろえば完了。

6. **stop を先に適用する。** host clock で finite な期限/TTL/limit を判定し、表示上の日付から推測しない。binding drift、scope/recipient mismatch、stale epoch、capability mismatch、quota/budget exhaustion、未知の identity、review の不足、期限切れは即時 stop とする。`waiting_owner`、`quiescent`、`budget_exhausted` は Task 完了ではない。stop receipt と未解決 gap が返れば完了。

7. **typed packet を返す。** `status=completed|partial|failed|blocked`、packet/attempt/objective/ownership、変更ファイル、checks と観測結果、artifact/evidence locator、unknowns/gap_reason、integration notes、gate ceiling を返す。root が attempt ID と verified runtime provenance を束縛するため、未観測の ID は空欄のままにする。`LOCAL_PASS` は `DEVICE_PASS`、`PROVIDER_PASS`、`PUBLIC_PASS`、`HUMAN_GO` へ昇格させない。返却 packet と観測 timestamp が一致すれば完了。

## 境界

- owner-supplied binding は local execution input であり、Task、Company authority、Promotion、Current Truth を作らない。
- parent が持つ実効 permissions は role TOML を上書きし得る。書込み可能な実効環境を見て read-only と称さない。
- native receipts と CLI receipts は別型で保存する。設定ファイル、名前、過去の prototype、synthetic pass count は実行証拠ではない。
- public send、provider 操作、credentials、共有 SSOT、core/runtime の変更はこの skill の認可に含めない。
