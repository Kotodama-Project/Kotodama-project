# 確認状況

この文書は実装候補の受入境界です。ローカル試験で実サービスの成功を代用しません。

## 自発参加（#150）

既定無効で実装済み・実VCは未受入です。ローカル合成試験で、短いstrict判定、独立した永続枠、断り後の沈黙、未許可・不明話者・古いepoch・出典変更・取消の拒否、固定自己紹介、Task/intentを作らないことを確認します。自己紹介用Liveは話者の入力sessionに登録せず、実Opus packetを使った割り込み試験でも入力音声を送りません。既存の呼びかけ経路は維持します。

実際に有効化する時期・参加者・利用量と自然な割り込み頻度の判断は #154 の人による受入です。合成モデル・SDKでの成功を実音声の受入にしません。

## 複数roomとBot pool（#142）

[Bot pool](VOICE-POOL.md)は実装済み・実VCは未受入です。同時room、満杯のbusy、二重join、
接続失敗と切断、遅い接続の取消、room別の権限・同意・停止を合成接続で検査します。
原音保存・rotationはpoolでは拒否し、単一VCの既存経路を保持します。実Botの準備と
実VCでの同時接続・復帰は#154の受入として残します。

実音声の確認は [受入手順・記録様式](REAL-VOICE-ACCEPTANCE.md) を使います。
本文を出さない診断 CLI の集計と、人による実聴の結果を分けて記録します。
この準備物の追加によって、以下の未受入項目が受入済みになることはありません。

| 範囲 | 状態 |
|---|---|
| 出典の版・訂正・閲覧制限、意図と実行の分離 | ローカル回帰試験 |
| CLI子プロセス→実HTTP→Task→成果ファイルの読戻し | 合成入力・合成モデルの実プロセス試験 |
| 同一Liveセッションでの複数回答、commentary返却、割り込み、未許可音声の破棄 | SDK・Discord player注入fixture試験 |
| ローカルASRのWAV境界、日本語確定テキスト、呼びかけ前Live 0件、呼びかけ後の継続 | HTTP・音声stream注入fixture試験 |
| Luna Responses analyzerの`store:false`、retry 0、厳密schema、context/output上限、token usage、エラー本文非露出 | SDK注入fixture試験。実APIの構造化応答は別に確認 |
| Liveの累積秒snapshotと`session.closed`最終値を加算せず保存 | SDK注入fixture試験 |
| 音声API残高不足の分類、重複通知防止、停止の再起動保持 | 両SDKのエラーを注入したローカル回帰試験。残高補充後の実音声は未受入 |
| 固定VCの自動入退室、無人猶予、手動停止の再起動保持、接続競合・復旧 | 接続注入fixtureによるローカル回帰試験。実Discordの入退室・復旧は未受入 |
| Linuxでのコード変更・Git差分・検証コマンド | 合成課題を実Luna/Codex CLIで実行し、差分・テスト・hash読戻し成功 |
| 実Discordの登録・コマンド表示・成果配送 | 専用Bot登録、実メッセージ→意図→Task→変更・テスト→成果DMのhash読戻し成功。入力はCLIによる接続試験で、利用者の満足確認は別 |
| 2人・30分の実音声、モード切替、実聴 | 未受入 |
| 実VCでの割り込み停止時間、120ms prefillの途切れ・体感遅延、500ms queue上限 | 未受入 |
| 実Lumaから取得したCSV→既存n8n→Botの取込 | 実サービス経路で取込と同一bytesの重複防止を確認。実参加者のいる当日運営は未受入 |
| n8n取込結果の本人DM、重複防止、送信直前の権限・出典検査 | 実n8nから本人DMへ到達し、送信者・宛先・本文hashをAPIで読戻し。同じ入力の次回はalready_sent。撤回・版変更・権限変更・配送不明はHTTP/SQLite/Discord fixtureで確認 |
| 公開テンプレートとして別設定で再現 | 未受入 |

`offline_fixture`は合成試験の表示です。設定にIDやモデル名があるだけで接続済みとは表示しません。CIは実音声・APIキー・Discord tokenを使いません。

2026-09-13の限定実行確認では、合成の開発課題をtrusted CLIから投入し、Lunaが実ファイルを変更しました。Discordの画面操作による確認はエージェントがCLI経由で行ったもので、人による満足・音声同意の証拠とは区別します。ローカルモデルのfallbackはprimaryの起動失敗を模した条件で、実モデルのCLIツール操作・ファイル変更・テスト・成果hash読戻しまで確認しました。Discordの後続訂正でも同じTask IDの新版でREADME作成とコード修正が成功しています。


## Review remediation acceptance (candidate)

The following regression surfaces are executable in `tests/analysis-admission.test.mjs`,
`tests/restart-recovery.test.mjs`, `tests/artifact-read.test.mjs`, and
`tests/verification.test.mjs`. Passing them is local/CI evidence, not user acceptance.

| Scenario | Required observation |
|---|---|
| 400 concurrent analysis submissions | At most the configured active and queued counts; no unbounded pending set |
| Permission/revision changes during queueing | No stale/unauthorized model dispatch or result adoption |
| Zero/exhausted analysis allowance | Source preserved, analysis explicitly deferred, no new execution |
| Restart and UTC rollover | Consumed cumulative reservations persist |
| Runtime restart | Unstarted Tasks visibly paused; running/stopping uncertain; no duplicate execution |
| Explicit paused resume | Same Task ID, new revision, current permission checked before state mutation |
| Ordinary files, FIFO, links, directories | Bounded reads; special/link paths rejected without hanging |
| Generated verification | No host-command fallback; read-only workspace; no network or host credentials |
| Cancelled verifier / cleanup failure | Owned daemon container removed, or explicit uncertain result |
| Discord matrix failure/skip/cancel | Existing required repository context fails |

The real Docker probe needs Linux and `KOTODAMA_TEST_VERIFIER_IMAGE` containing the
immutable ID of a deliberately prepared fixture image. Linux CI prepares that
fixture; the runtime never pulls an image. Without this fixture the real isolation
probe is explicitly skipped, and argument/mocked lifecycle tests are not substituted
for it. The image ID and cleanup result are emitted as bounded CI evidence.

Still separate and not claimed here: a second person's clean installation,
2-person/30-minute real Discord voice, measured interruption/latency, provider
billing, configured production Docker daemon/image, and Human GO. Existing live
receipts apply only to their own revisions and unchanged behaviors.

## 15分のVoice rotation（#148）

区間管理・非公開投稿を実装し、時計を注入した900秒境界・発話延長・ASR待ち・再起動と、
全閲覧者/全Sourceの読取権限、取消、unknown配送の再送禁止を合成入力で検証します。
実音声の受入、到着時刻・話者・途切れ・再参加の実測は未実施で、PB-G2は未完了です。
[確認手順](VOICE-ROTATION.md)に従い、人の受入結果を#148へ記録します。

## 不足情報の確認（#145）

Interaction Policyとclarify_onceを実装し、合成のStore/Pipeline/Discord送信先で、同じ
話者・部屋の最大一回、並行予約、再起動、期限、誤った話者・権限取消・出典撤回を検査します。
質問の案内は元チャンネルへの回答を明示し、受信できないDM返信を誘導しません。
実Discord・実VC・実APIでの質問の品質とPB-G10は未受入です。

## 静かな仕事の進捗（#144）

静かな仕事の進捗（#144）は[既存DMの更新](QUIET-TASK-PROGRESS.md)として既定無効で実装しています。
権限・版・上限・退出後の仕事継続は合成試験で検証し、実Discord・実VCと通知の使いやすさは未受入です。

## 履歴増加時の保存・検索

`tests/store-scale.test.mjs` は100チャンネル・12,000出典・2,400 Taskの合成履歴で、
会話contextのJSON読取りが設定した12出典に収まり、出典・Taskの検索と訂正の
無効化が索引を使うことを検査します。閲覧不可・撤回済みの出典は件数制限の
前に除き、読取可能なarchiveだけが対応する速い文字起こしを置き換えます。
時刻・版・出典IDの順序、本文の総文字数上限、同じguild/channelにある異なる
providerの出典も従来の条件を維持します。

既存SQLiteへの索引用projectionの移行は一度のtransactionで行い、原文・
fingerprint・過去版・Task本文を変更しません。再起動時の全履歴の再解析、
訂正時の全Task本文のJSON走査、予約ごとの全日付の合計読取りを避けます。
Taskのcontext再束縛・訂正、権限の変化、予算のrollbackも回帰試験で検査します。
旧版での単独書込み・削除を経た再upgradeでは、SQLiteに残るtriggerの印を使って
projectionを再構築します。原文の閲覧制限も返却時に再確認します。

初回移行は現在の出典とTaskの件数に比例します。全資料のexportと全件一覧は
要求した件数に比例し、remote Task ownerの一覧取得は既存契約のままです。
この合成試験は同時書込みの実測、世界規模のthroughput、実provider・Discordの
遅延を証明しません。
