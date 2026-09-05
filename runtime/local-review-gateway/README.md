# ローカル Voice review Gateway

この小さな候補実装は、Cloudflare Worker が既に参照する二つの Gateway
endpoint を localhost で実行します。合成 seed または operator が指定した sanitized
handoff candidate のローカル JSON を読み、
利用者の review 操作を revision に束縛して保存し、再起動後も読み直せます。
依存 package、モデル呼出し、Cloudflare account、DB、provider 接続は不要です。

保存するのは限定された review projection です。Task SSOT、raw Source Evidence、
Decision、Capability Grant、実行 queue は持ちません。`accept` も projection の
review 状態を `accepted` にするだけで、仕事の実行、governance approval、
Promotion、Current Truth、Human GO を作りません。公開境界は
`read-only/candidate-only`、`NO_GO_UNPUBLISHED` のままです。

## 起動と停止

Node.js 24 の標準ライブラリを使います。作業ディレクトリから、他用途と共有しない
既存の保存ディレクトリを指定してください。以下の環境変数は operator がローカル
に設定します。値をファイルへ commit したり、コマンド引数・ログへ出さないでください。

- `CONTEXT_GATEWAY_CLIENT_ID`: 明示した trusted backend の identifier。
- `CONTEXT_GATEWAY_CLIENT_SECRET`: ローカル検証専用のランダムな秘密値、32～4096 ASCII 文字。
- `LOCAL_REVIEW_PORT`: 任意。既定値は `8789`。

```text
node runtime/local-review-gateway/server.mjs --state-root work/local-review-state --seed-synthetic
```

保存ディレクトリは起動前に作成します。初回は `--seed-synthetic` で、付属する
一件の合成候補だけを取り込みます。既存 store があれば seed は適用せず保存済み
状態を読みます。再起動では `--seed-synthetic` を省略できます。API 利用時の
`startReviewGateway({ stateRoot, clientId, clientSecret, seeds })` も同じ契約です。
`seeds` は operator が渡す `{principals, records}` の閉じたcatalogで、
初期 revision は `1`、review state は `pending`、既存 Worker の allowlist に
完全一致する projection だけが許可されます。HTTP に import endpoint はありません。

### 手動候補ファイルの取り込み

sanitized handoff candidate を自分で用意する場合は、`--seed-synthetic` の代わりに
ファイルと、その **exact bytes の期待 SHA-256** を指定します。

```text
node runtime/local-review-gateway/server.mjs --state-root work/local-review-state --import-file work/review-candidates.json --expected-sha256 <64桁の小文字SHA-256>
```

UTF-8 JSON の root は `{principals, records}` objectです。principalは `{principal_ref, kind, actor}`、recordは `{projection, access_policy}`。分類・担当・明示reader/reviewer・期限が必要で、具体形は [情報アクセス手順](../../docs/INFORMATION-ACCESS.md) と `syntheticCatalog()` を参照します。
`actor` は明示した `subject` / `email` の組で、片方だけを使う場合は、もう片方を
`null` にします。`projection` は `synthetic-fixture.mjs` と同じ閉じた形式の候補で、
`handoff_id`、`revision: 1`、`human_review.state: "pending"`、digest URN、
`authority: "candidate_only"` と false の effect 境界を保持してください。actor を省略したり、private field や
raw body を追加した候補は拒否します。入力を clone して使う場合も、明示した actor と
内容を確認したあとで期待 digest を固定してください。秘密値を入力ファイルに含めません。

最大 64 件・4 MiB、重複 key・不正 UTF-8・symlink/hardlink file・親 directory の
symlink を拒否します。読み込む bytes 数も固定上限で制限し、digest は JSON 解析前に
照合します。ファイルは変更せず、入力 path や actor 生値は store に保存しません。
`--import-file` と `--expected-sha256` は両方必須で、`--seed-synthetic` との併用は拒否します。

**import は新しい store の初期化専用**です。既存 state があれば同じ候補でも拒否し、
上書き・自動 merge は行いません。再起動では import 引数を外し `--state-root` だけを
指定します。API でも `startReviewGateway({ stateRoot, clientId, clientSecret,
importFile, expectedSha256 })` で同じ検査を利用できます。

この入口が確認するのは、operator が指定したファイルの bytes と候補の構造だけです。
入力は認証済み Voice capture、原会話の真正性、source lineage、consent/retention、
actor grant の独立証明にはなりません。JSON の自由文を意味解析して private content を
検出する機能もありません。raw transcript を持ち込まず、利用許可と redaction を確認した
candidate だけをローカルで渡してください。取込みは実行・承認・Promotion を起動しません。

listen は `127.0.0.1` に固定され、public bind は拒否します。長時間動かす場合は
作業環境の tracked process launcher で owner・PID・期限を記録してください。
Ctrl+C / SIGINT / SIGTERM は server を閉じ、writer lock を解放します。
強制終了で lock が残った場合は、自動解除しません。元プロセスの終了と保存 bytes を
確認してから、operator がその専用 lock directory だけを除去して再開してください。

## HTTP 契約

全 request は次の header を必要とします。

- `cf-access-client-id` / `cf-access-client-secret`: 設定値との完全一致。
- `x-kotodama-access-subject` / `x-kotodama-access-email`: seed に束縛した actor。
  片方だけの identity は他方を省略し、seed では `null` にします。

サービス資格情報の検証に成功した **trusted backend だけ** が actor を代理できます。
actor header 自体は認証証明ではありません。この秘密値をブラウザ・Gadget・一般の
利用者へ渡してはいけません。実 Worker は署名検証済み Access identity から header を
新規構築します。Gateway は subject/email の組を actor digest として照合し、
主体IDへ一意に解決し、情報ごとの現在のpolicyでreader/reviewer・分類・取消・期限を検査します。権限のないhandoffは存在しない場合と同じ `404` を返します。
ブラウザからの `Origin` 付き request、異なる Host、未認証 request は拒否します。

| 操作 | 成功時の内容 |
|---|---|
| `GET /v1/voice/handoffs` | 主体IDのread権限に一致する最初の一件のprojection |
| `GET /v1/voice/handoffs?q={handoff_id}` | readerに明示された exact ID 一件。全文検索・一覧 API ではない |
| `POST /v1/voice/handoffs/{handoff_id}/review` | revision を一つ進めた保存済み projection |

GET と POST の応答には `handoff_id`、正整数の `revision`、既存の概要・話者別
ハイライト・判断候補・ToDo・質問・digest URN・review state を含みます。
Worker の `GET /voice/review` も ID と revision を保持します。利用者は返された値から
`POST /voice/review/{handoff_id}` を構成できます。

POST は `application/json`、次の閉じた body だけを受け付けます。

```json
{"action":"accept","expected_revision":1}
```

`action` は `accept` / `edit` / `reject`。`edit` のときだけ
`edited_overview` が必須です。review は候補概要の訂正であり、raw source の変更では
ありません。`expected_revision` と保存済み revision が違えば `409`、入力が不正なら
`400` です。Worker も revision を必須検査して転送し、POST 応答が同じ ID、
revision + 1、指定 action の review state に一致しなければ `502` で拒否します。

## 保存・拒否境界

- request body 16 KiB、edited overview 8000 UTF-8 bytes、query 256 UTF-8 bytes、
  同時接続 16、request/idle timeout 5 秒。
- 最大 64 件、store 最大 4 MiB。保存先は明示したディレクトリ内の固定 filename
  `voice-reviews.json`（v2）。v1は保全して起動を拒否し、分類・閲覧者を勝手に補完しません。request の ID を filesystem path に使用しません。
- 親を含む symlink directory、symlink/hardlink store、破損 JSON、不正 projection、
  重複 JSON key、private field、malformed UTF-8 を拒否します。
- 同じ store の二重起動は専用 writer lock で拒否します。CAS と fsync 済み一時ファイルの
  rename を await なしの一つの処理で行い、成功後にのみ新 revision を返します。
- 保存済み状態の再起動 persistence は検証しています。停電耐性・OS crash recovery・
  malicious local filesystem writer に対する防御・本番 key custody の証明ではありません。
- credential と actor 生値は store に保存せず、request body や private content を
  ログへ出しません。自由文が private かどうかの意味判定は行いません。
  この candidate への入力は合成・認可済み projection に限定してください。

rollback は Gateway を停止して、operator が保全した候補 store に戻すか、別の
専用ディレクトリで合成 seed から再開します。公開側や Task 正本への書き戻しはありません。

## 検証と次の接続点

```text
node --test tests/node/test_cloudflare_voice_review.mjs tests/node/test_local_review_gateway.mjs tests/node/test_information_access.mjs
python -S -B tools/validate_cloudflare_edge_candidate.py
```

Worker の既存 JWT fixture だけを合成し、Gateway 通信は実 local HTTP server を使う
GET → edit → restart → GET を検証します。test 内の HTTPS→loopback transport 置換は
検証専用です。Worker 本体の HTTPS-only Gateway 制約を緩めません。

次の connector seam は、認可済み Verified Handoff の exact source digest/revision と
actor grant をこの手動 import へ検証付きで束縛する Context Gateway adapter と、返された ID/revision
から review する公式 Cloudflare OS Gadget です。実装済みなのはローカル Gateway と
Worker の契約だけです。OS Gadget/Blueprint/Gatekeeper の native 結線、実 Access/Tunnel、
HTTPS private transport、Voice capture、専門 Agent 実行、provider deploy、モデル呼出し、
governance Decision への採用、Promotion は未実装・未証明です。
