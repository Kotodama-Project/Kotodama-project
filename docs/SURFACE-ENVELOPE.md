# Slack／Teams の共通event契約

Issue #70の最初の範囲は、accountを使わない合成eventの契約です。
既存Node runtimeのmoduleとして用意し、別runtimeやTask ownerを増やしません。
HTTP endpoint、OAuth install、メッセージ送信、実adapterはまだ接続していません。

## 入力と取消

[schema](../schemas/surface-event-envelope.schema.json)はsurface、tenant、installation、
channel、thread、actor、event ID、source ID／revision、時刻、期限、同意参照、
原文、ACL、media能力を束縛します。表示名やemailはidentityに使いません。
同じchannel名やactor表記でもtenant／installationが異なれば別sourceです。

[Node契約](../runtime/discord-template/src/surface-contract.mjs)は、呼出し元が用意した
現在のinstallation／membership／permission revision／期限と照合します。再送はevent IDで
拒否し、編集・削除・取消は同sourceの新revisionとして扱います。古いrevisionへ戻りません。
同threadへのresult照合でも現在のsource revisionとmembership／期限を読み戻す形を要求します。
このmodule自体は履歴を保存しません。実adapterでは既存Source ownerへ永続化し、
passive sourceを実行権限に変えず、明示依頼を既存Taskへ返す必要があります。

schemaを読むだけのCLIは署名・membership・providerの検証を主張しません。

```text
python -B tools/validate_surface_envelope.py examples/surface-envelope/slack.json
node --test runtime/discord-template/tests/surface-contract.test.mjs
```

## 署名mechanismの確認

[Slackの公式手順](https://docs.slack.dev/authentication/verifying-requests-from-slack/)に従い、
JSON化前のraw body、v0、timestampをHMAC-SHA256で検査し、5分を超える時刻差や改変を拒否します。
合成secretで機構を確認しています。endpointのheader重複処理、app installとscope、
raw payloadからの正規化、実workspaceの権限はこの試験に含めません。

[Bot Connectorの公式手順](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication?view=azure-bot-service-4.0)
を元に、Teams向けfixtureはRS256、issuer、app audience、nbf／exp、serviceUrl一致、
channel endorsementを検査します。RSA keyは試験中だけ生成します。実OpenID metadata／
keyの取得・更新とtrust、TLS受信、tenant installを実装したものではありません。
Emulator、Graph、別cloud、meeting mediaへこのfixture検証を流用しません。
実adapterでは公式SDKと実test tenantで認証経路を受け入れる必要があります。

署名mechanismのPASSはprovider本人性のPASSではなく、戻り値はその区別を保持します。
合成envelopeは常にTask作成とpublication authorityをfalseにします。

Node入口も同じ閉じたschemaを使います。standalone runtimeへのcopyは
`python tools/dev/sync_surface_schema.py`で生成し、byte一致を試験します。

## 利用能力の対応

| 能力 | Slack | Teams | 現在の証拠 |
|---|---|---|---|
| text／thread／原文・actor・出典 | candidate | candidate | 合成schemaと固定identity照合。実ingress未接続 |
| 署名・認証mechanism | candidate | candidate | 合成HMAC／RSAの正負試験。provider trust未確認 |
| retry／編集・削除・取消 | candidate | candidate | 読取履歴でreplay／古いrevisionを拒否。永続adapter未接続 |
| 同じTaskへの依頼・訂正・停止・成果 | unknown | unknown | 新しいTask ownerは作らない。実接続と返却は未確認 |
| 同じtenant／threadへのresult | candidate | candidate | 現行scopeとsourceの検査のみ。送信なし |
| native人向けUI／通知／文書pagination | unknown | unknown | 実workspace／tenantでの受入なし |
| native音声・会議・speaker本人性 | unsupported | unknown | このcandidateはmediaを起動しない。静かな参加も未受入 |
| consent／保持／切断復旧／cost／rollback | unknown | unknown | 入力に同意参照と期限を保持。実運用の受入なし |

Session / conversation ledgerはslack_textとteams_textのmetadata種別を受け入れます。
voice種別や実exportを追加したものではありません。実workspace、管理者同意のあるtenant、
media経路、保持と費用の範囲を確定した後に実接続を検証します。
Public BetaはNO_GO_UNPUBLISHEDです。
