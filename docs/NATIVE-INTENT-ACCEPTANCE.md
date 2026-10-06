# 要件整理画面の利用者起点の受入試験

比較の基準は#126を受け入れたmain `cbec86ad14faffe48abbe712cfac50181467fbe5`。
その`client.js`は、感度試験で使った前身`d35dde11c6b2437b8154a172dc01ebbd6032f794`と同じbytesです。
元#66の表示・応答順の修正だけを再配置し、過去の観測を現在の受入へ流用しない。
この変更は実際のGadget `client.js`をChromiumで読み込み、合成RPCの応答と操作を与える**ブラウザコンポーネント試験**。Cloudflare OS本体・Gatekeeper・実認証・実Codex・会話理解・本番配備のE2Eではない。

## 操作上の契約

- 新しい再確認や変更要求より前の応答は、後から届いても画面を巻き戻さない。
- 読み取りが返らない場合も、明示的な再確認で古い読み取りを置き換えられる。ポーリング自身は読み取りを重ねない。
- 確認中の古いready状態は実行許可として表示しない。失敗後に自動読み取りで過去の依頼を再表示しない。二重イベントで追加の変更要求を作らない。
- `ready`以外の応答に候補が混入していても表示しない。候補の「条件が未記載」を「確認済み」「問題なし」に読み替えない。
- 長いURLや文章を320/360/390/768/1280pxで読める。未信頼文字列はHTMLとして解釈しない。

## 実行と解釈

```sh
python -S -B tools/check_tracked_secret_hygiene.py
python -m pip install --require-hashes -r requirements-native-browser-ci.txt
python -m playwright install chromium
python tools/test_native_intent_browser.py --evidence-dir work/browser-evidence > work/browser-results.json
```

既存Chromiumを使うローカル環境は`CHROMIUM_EXECUTABLE`へその実行ファイルを指定できる。
12職務の依頼文、10状態の正常応答／候補混入応答、5表示幅、4つの順序・操作・文字列境界を試す。**304バリエーションは304人の利用者、304種類の独立した業務、304エージェントではない。** 正常状態と異常応答の件数も分けて出す。

HTTPはブラウザ境界で遮断し、合成`gadget`が記録する呼出数を検査する。実行は一回だけという検査はUI境界の確認であり、サーバーの冪等性・組織の権限検証を代替しない。実際の会社での本人確認、依頼の意図抽出、承認と送達、結果の元Workとの一致は別の受入対象。

## 検出感度

同一スクリプトの`--root`を固定基準checkoutへ向け、修正前と修正後を比べられる。失敗したから期待値を現在の実装へ合わせない。既存のAPI、UUID予約、承認キュー、サーバーの認可条件は変更しない。

## ローカルHTTPと永続化を通す連続した利用

別の試験で実際の`local-review-gateway`を起動し、12職務の合成入力について、閲覧→権限のないreview拒否→同版の訂正競合→再起動→古い画面のaccept拒否→読取権限取消→再起動後の取消維持を通す。対象は自分が作成した一時領域とlocalhostだけ。元の意図と訂正文を実際のHTTP応答・保存から照合する。これは**1つのライフサイクルを12入力で試す**もので、12実会社の業務成功ではない。

```sh
node --test tests/node/test_local_review_gateway.mjs tests/node/test_information_access.mjs tests/node/test_company_persona_journeys.mjs
```

既存のGateway/access試験と12職務のjourneyを実行する。サーバー・保存処理・HTTPは実物だが、外側の認証issuerと会社identityは合成。Cloudflare Access自体の認証、会話理解、実組織の権限変更、実顧客への送達、画面からサーバーまでの一続きのE2Eは成立させていない。CI証拠はリポジトリ監査へ混入しないrunner一時領域に保存する。

ブラウザ依存は共通validator環境へ混ぜず、`requirements-native-browser.txt`から
`uv pip compile --universal --generate-hashes --python-version 3.12 --output-file requirements-native-browser-ci.txt requirements-native-browser.txt`
で生成したhash付きlockを使う。pathを限定した任意workflowはこのコンポーネントだけを実行し、全体unittestを重複させない。
