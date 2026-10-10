# 判断と許可の現在地

`judgment`は、同じ稼働runtimeの現在設定、Task、Source、Lumaの承認記録を
読み取る診断です。作業開始、確認質問、承認、公開、台帳の追加を行いません。

```sh
node bin/kotodama.mjs judgment --config .kotodama/config.json --actor YOUR_USER_ID
node bin/kotodama.mjs judgment --config .kotodama/config.json --actor YOUR_USER_ID --task TASK_ID --json
```

runtimeが起動している必要があります。既存のloopback control認証と
owner/PID/起動時刻の照合を使い、現在のoperatorだけが読めます。
`--task`は本人の一件に限定し、Luma一覧は取得しません。
本文、Taskの題名・条件、イベント内容、URL、private path、credential、
CLIの任意引数は出力しません。対象のID・revision・digestは本人向けの診断です。

| JSONの項目 | 読み方 |
| --- | --- |
| `configured.actions` | 今の設定で許している操作 |
| `effective.actions` | 起動時workerと現在設定を照合した結果。`blocked`は制約がある状態、`scope_check_required`は対象のSource・依頼・実行前検査がさらに必要な状態 |
| `effective.configurationDrift` | workspace、owner、実行器、検証等の現在設定と起動時設定の差分。設定ファイルの変更だけで稼働workerが切り替わったとは扱わない |
| `codexToolApproval` | CLI引数から読める設定値と、起動時の設定値。実際のCodex内部policyは`observed: unknown` |
| `tasks.items[].review` | `RESULT_REVIEW_PENDING`は成果確認待ち。独立したagentのreviewで扱える場合もあり、必ず人へ承認を求める意味ではない |
| `tasks.items[].technical` | runtime resultに記録された実行・check・独立review。`reported_pass`は保存結果の申告であり、このcommandによる独立再検証ではない |
| `humanDecision` | 会社側Decision ownerは未観測。一般Taskの成果確認からHuman GOやPromotionを作らない |
| `identity` | login/OAuth等の本人操作やprovider sessionをこの診断では観測していない |
| `luma.items[].approvalReceipt` | 既存のactor/Source版/候補digestに束縛したbutton承認記録。`missing`、`valid`、`expired`、`mismatched`、`consumed`を区別 |
| `luma.items[].pendingDecision` | 現在の候補に承認が不足する場合だけ`HUMAN_DECISION_REQUIRED`。古い出典、取消、候補不一致は`CANDIDATE_RECONCILIATION_REQUIRED` |

Codexのtool approvalが`never`でも、会社の人間判断やLumaのbutton承認を
無効にした意味ではありません。設定で指定しなければ`unspecified`、解釈できない
値は`unknown`です。user config、fallback、CLI内部の優先順位を推定しません。

Task一覧はlocal ownerのみを読みます。remote ownerでは`REMOTE_OWNER_UNOBSERVED`
と返し、local SQLiteをremote Taskの写しとして読みません。起動時bindingの
差分があるときもTask詳細を出しません。Sourceの現在の閲覧許可とrevision、
既存のread authorizationを確認し、訂正された入力の技術結果は`invalidated`です。
Lumaも現在のSourceの閲覧許可、guild/channel scope、既存の認可を確認します。

一覧は種類ごとに最新20件までです。`truncated: true`なら過去の項目が残っています。
閲覧できない項目は本文やIDを出さず`unavailable`件数へ集約します。返却直前に
設定・Task・Source・Luma request/candidateとDiscordの権限変更世代を再照合し、途中で変化したsnapshotを
部分的な成功として返しません。

診断の待ち時間は8秒、一度に一件です。時間切れでも未完了のprovider readが
終わるまで枠を保持し、再試行を`JUDGMENT_BUSY`で拒否します。shutdownは最大15秒で
このreadの終了を確認し、確認できなければ`JUDGMENT_DRAIN_UNCERTAIN`として
SQLiteとhost lockを保持します。権限・設定が読めない場合もfail closedです。

`observedAt`は診断開始時刻です。表示はpoint-in-timeの記録で、新しい実行許可では
ありません。Lumaの許可は従来どおり5分間・一度だけで、実行時の`claimEvent`が
現在の許可を再確認します。`consumed`は再利用可能な許可ではありません。
provider readbackは`reported_not_independently_verified`として残します。

ローカルのCLI/controlと合成provider認可を試験します。実Discord、本人のlogin、
Luma write、会社Decision ownerの接続、配備の受入は別途必要です。
公開面は`NO_GO_UNPUBLISHED`を維持します。
