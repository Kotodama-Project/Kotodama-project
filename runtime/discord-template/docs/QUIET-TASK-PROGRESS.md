# 会話を遮らない仕事の進捗

声から始まった仕事の**既存の開始DM**を、確認時点のTask状態へ更新できます。
新しいDM、channel投稿、音声、model呼出しは追加しません。結果のDMは従来どおり届きます。
既定は無効で、local Task ownerのみが対象です。

```json
"notifications": {
  "taskProgress": {
    "enabled": false,
    "minIntervalSeconds": 30,
    "maxUpdates": 6
  }
}
```

minIntervalSecondsは30〜3600秒、maxUpdatesは1〜6回です。同じTask全体に適用し、
訂正で版が進んだり、runtimeが再起動しても回数は戻りません。状態はTask ownerから読み、
進捗率や「ほぼ完了」といった推測を表示しません。確認待ち、失敗、停止確認中、取消済み、
結果不明を区別し、確認日時を付けます。確認待ちは人の受入ではありません。

既存Task eventsを5秒ごと・64件まで読み、同じTaskの変化はその時点の最新状態にまとめます。
更新するのは機能が有効な間に送った開始DMだけです。宛先は同じTaskと依頼者に束縛し、
stop/resumeの版変更後も保持します。開始DMの到着が遅れた場合も、宛先登録後に現在の状態を
読み直します。訂正で別の開始DMが届いても、最初に登録したDMを進捗用に維持します。
起動前や無効と認識していた期間の
eventは再生しません。同じ版・状態は一度だけ試み、不明な配送を自動再送しません。
上限、quiet hours、権限不足やVC退出で見送った状態は再送せず、次の状態変化を待ちます。
Taskの開始・完了の既存通知、および明示的な`tasks`/`result`の照会は引き続き使えます。

## 宛先と権限

依頼者が同じVC epoch内に在室し、全在室者が音声処理と全Sourceの読取を許可されている
場合だけ、依頼者のDMを更新します。16人・32source bindingsを超える場合は見送ります。
pause/recovery、聴衆変更、quiet hours、取消・訂正、Task版変更、機能の無効化でも止まります。
宛先・permission取得後に設定、Task、全Source、VC epoch/generationを再検査します。

退出や進捗通知の停止は仕事の取消ではありません。実行を取り消す場合は既存のstopを使います。
runtime終了時は、この機能が開始した編集中の処理を待ち、Storeを先に閉じません。
保持する追加情報は既存delivery/event内のmessage ID、Task ID、版、状態、試行時刻のみです。
仕事の本文、結果、音声を別の台帳へ複製しません。

## 方式の比較と受入

[公式Live thinking仕様](https://developers.openai.com/api/reference/resources/live/primary-websocket#session.thinking.append)は
直接の発話要求をしませんが、後の発話に影響し、秘密保持の境界にはなりません。
[client delegationの指針](https://developers.openai.com/api/docs/guides/live-delegation#keep-updates-accurate-and-useful)も
実際に変わった状態の通知と、会話の割込みと仕事の取消の分離を求めています。
初版は[設計比較](https://github.com/Kotodama-Project/Kotodama-project/issues/144#issuecomment-6025119707)に従い、
既存DMを更新してmodel contextや音声への送信を増やさない方式を採用しています。

合成試験で既定無効、state deduplication、再起動後の上限、非同期処理中の権限取消・出典撤回・
Task訂正、聴衆の権限、退出後の仕事継続、不明な編集の再送禁止を確認します。
**実Discord・実VCでの受入は未実施**です。端末通知の挙動や更新の使いやすさも#154で確認します。
この実装だけで有効化・実配備・Public Betaの受入を行ったとは扱いません。
