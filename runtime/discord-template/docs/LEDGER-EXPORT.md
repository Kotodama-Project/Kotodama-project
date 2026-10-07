# 私有の会話台帳 snapshot

`ledger-export` は停止中の local owner の Source 履歴と Task event を、既存の
Session/conversation ledger 契約へ書き出します。資料を生成する `export` とは別です。
合成データで実装・復元・Python validator を検証済みです。実運用データでは未実施です。

## 使い方

操作者が private な保存先、鍵、保持方針と対象の同意範囲を選んだ後に実行します。
runtime を停止してください。鍵はランダムな32 bytesを64桁のhexにし、指定した環境変数に
入れます。CLI引数、Git、会話、ログに鍵を入れません。出力先の親directoryは事前に
用意し、他の利用者が読めないOS側のアクセス権を設定します。POSIXでは生成directoryを
0700、fileを0600で作ります。Windows ACLの設定はこのcommandの担当外です。

private scope JSON の形（以下は意味を示す合成例。実運用のscopeではありません）:

```json
{
  "mappingKeyEnv": "KOTODAMA_LEDGER_KEY",
  "policyId": "operator-selected-policy",
  "policyRevision": "operator-selected-revision",
  "retainUntil": "2099-01-01T00:00:00Z",
  "consentBasis": "operator-selected-consent-record",
  "knowledgeScope": "operator-selected-knowledge-scope"
}
```

```text
node bin/kotodama.mjs ledger-export --config PRIVATE_CONFIG --actor YOUR_USER_ID --scope PRIVATE_SCOPE_JSON --output NEW_PRIVATE_DIRECTORY --json
python tools/validate_session_conversation_ledger.py validate NEW_PRIVATE_DIRECTORY/ledger.jsonl
```

Python commandはrepository rootから実行します。Node commandはこのcomponent rootからです。
`retainUntil`は実在する未来のUTC日時（秒または1〜3桁の小数秒、末尾Z）です。存在しない日付や24時の正規化を拒否します。
scopeの文字列は既存方針へのbindingであり、新しい同意・本人確認・実行grantを発行しません。
鍵を失うと復元できません。鍵の保管/rotationや本番backup、復旧はownerの既存運用に従います。

## 出力と再実行

新しいdirectoryに3ファイルだけを作ります。

| file | 内容 |
|---|---|
| `ledger.jsonl` | opaque ref、時刻、SHA-256、順序・参照。本文、元ID、path、hostを埋め込まない |
| `payload.aes256gcm` | 正確な store event body、該当 Source 版、参照対応表、scope、snapshot receipt の暗号文 |
| `manifest.json` | ledger/ciphertext digest、nonce/tag、opaque鍵・保存先binding。本文・鍵・生pathなし |

HMACの参照鍵とAES-256-GCMの暗号鍵はHKDFで分離します。公開metadataのSHA-256と
保存先bindingを認証し、private payloadを読み戻して各eventのcontent hashと照合します。
Node標準cryptoだけを使い、外部依存やprivate donorコードは追加しません。
`readLedgerPackage` は既存保存先に対する復元・整合確認APIで、private bytesをメモリへ
返します。本文を表示するCLIやprovider送信はありません。

同じsnapshot・鍵・scope・保存先での再実行は既存bytesを読み戻し、`duplicate`を返します。
内容が変わったら新しいdirectoryを指定します。既存packageを書き換えません。別保存先への
単純copy、誤鍵、改変、link/hardlink、余分なfile、欠けたpackageは拒否します。
途中失敗のdirectoryは削除せず残します。診断・回収はownerが扱います。

## 対応と限界

| store event | ledger event | evidence |
|---|---|---|
| `source.created` | `human_message` / `voice_segment` | exact `source_versions` と元eventを暗号化 |
| `source.corrected` | `source_update` / `SOURCE_UPDATED` | 直前のSource eventへcausal/invalidation ref |
| Task create/start/correct/context/result/stop/resume/recovery | systemの`agent_action` | event作成時のTask版・Source/context版のbinding、同じTaskのopaque correlation、先行eventへのcausal ref |

ledgerの時刻はstoreが観測したevent時刻です。元の取得時刻、話者track、原文、訂正前後の
本文などは正確なSource JSON内に保持します。`RAW_SOURCE_JSON` はこの取得済みJSONを
意味し、raw PCM/ASRの再取得や復元を主張しません。音声の話者が未同定なら除外します。

ledgerの`correction`はbound SessionのHuman Decision専用です。原文訂正はそこへ
変換しません。Sessionは`UNASSIGNED_INBOX`、decisionは`NONE`、本人確認は
`UNVERIFIED_PUBLIC_CLAIM`のままです。Task正本を作らず、Taskの状態を変更しません。
当時のTask本文や成果本文がevent履歴にない場合、現在値で埋めません。成果eventは
元のstate/artifact_countのみを保持します。intentはmodel/decision provenance不足のため
今回のexportには含めません。新しいTask eventは既存events表に入力scopeの小さなbindingを保持します。
過去のeventにこのbindingが無い場合は除外し、現在のTaskから過去のscopeを補完しません。
Task訂正eventは変更前のSource/contextも照合します。これは監査の参照であり、Task状態の正本ではありません。

現在も読めるDiscord Sourceと、その各履歴版のreadersに操作者が含まれるものだけが対象です。
Taskは本人のものに限り、現在のSource/contextに加え、event時点のSource/contextの各版も確認します。
音声は現在のspeaker opt-outも確認し、撤回後のSourceと依存Task eventを除外します。
非Discord・撤回/権限外・未対応eventは`omitted_events`へ数え、receiptを暗号文に保持します。
対象Sourceの過去版欠落、先行訂正event欠落は拒否します。全provider・全履歴の完全export
ではありません。最大10,000 events/入力32 MiB/出力各64 MiBを超えれば、切捨てず拒否します。

既存runtime lockがないことを確認し、SQLiteのBEGIN IMMEDIATEによるwriter reservationを
snapshot読取から同期出力・readbackまで保持します。既存のtransactionは借りません。
export専用のpersistent host lockは書かないので、強制終了や電源断でもSQLiteが排他を解放します。
実process強制終了後に通常runtimeを起動できることを合成試験で確認します。remote ownerは
読取・書込前に拒否します。runtime lockを盗んだり、他processを停止したりしません。

## 保持と移行候補

期限・consent・knowledge scopeをopaque refへ写し、policy revisionをprivate payloadに
保持します。自動期限削除、snapshot backup復旧、運用鍵管理、削除receipt/readbackの生成は
含めません。archive/restore/deleteのledger状態は`NOT_REQUESTED`、encryptionは
`DECLARED_UNVERIFIED`です。合成の復元成功を本番の保持・削除完了へ昇格しません。
[保持・削除](RETENTION-READBACK.md)の既存運用とも別のprivate保存物として管理します。

公開mainには既存vault実装がなかったため、この限定packageで保存・復元・原本/訂正参照・
冪等性・改変拒否を補います。private移行候補を転載/採用した主張はありません。#169の
全family inventory、private receipt、運用保存先や削除完了はこの合成実装で完了しません。
