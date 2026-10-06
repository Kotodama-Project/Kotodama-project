# 既存ナレッジから実行入力までを束縛する

既存の`knowledge_base.py context`と`runCodexBrief()`の間に限定したknowledge入力の組立てを追加した。Work・承認・Taskの正本を作り直さず、Voice専用HTTP入口へknowledgeを偽装して流さない。

## 流れ

1. 現行ownerが既存KBを検証し、対象を絞ったcontext JSONを生成する。出典版、classification、期限、critical context不足は既存の判定を使う。
2. `prepareKnowledgeBriefInput()`へ依頼文、JSON bytes、ownerが現在と確認したcontext SHA-256とsource digestを渡す。
3. 不一致、未解決、期限切れ、重複concept、予算超過を拒否する。`projection_only`や`source_required`は入力に残す。
4. `runCodexBrief()`が固定指示とJSON wrapperを含む**実際のUTF-8 stdin bytes**を作り、起動前にdigestを観測可能にする。
5. `thread.started`の観測と成功結果に同じbindingを付ける。入力JSONだけのhashとstdin全体のhashを混同しない。

## APIと境界

`runtime/codex-task-bridge/knowledge-input.mjs`の`prepareKnowledgeBriefInput({request, contextJson, expectedContextSha256, expectedSourceDigest, now})`は、既存KBの`kotodama.generated-knowledge-context / v1`だけを受け付ける。現行の`as_of`、4つのselector配列、16フィールドのConceptを閉じた形で検査し、未来の評価時刻、存在しない暦日、欠落・空source、撤回/廃止/矛盾状態や選択と省略の重複を拒否する。別のKnowledge Work Packageや任意会話を暗黙変換しない。

依頼は最大4 KiB、contextは最大16 KiB、組み合わせたrunner入力も最大16 KiB。無言の切捨てはしない。`now`はtrusted adapterの時計を使い、過去時刻のfixture評価を現在の受入にしない。

`onInputPrepared(binding)`は同期callback。失敗・Promise返却・callback内の取消があればmodel processを起動しない。bindingは`input_sha256`, `stdin_sha256`, `stdin_bytes`, `schema_sha256`で、本文・secretを含まない。開始callbackと完了結果にも同じdigestを渡す。schemaが実行中に変われば結果を拒否する。

`input_sha256`はcallerの文字列、`stdin_sha256`は固定指示とwrapperを含めて`stdin.end()`へ渡すbytes。準備観測は「準備済み」で、providerが全bytesを消費した証明ではない。sessionは開始、CLI完了は当該応答の完了であり、会社の仕事の完了ではない。

既存brief bridgeは開始callbackのbindingをjournal v3の`session.input_binding`へ同期保存する。
失敗・中断・再起動の後も同じ認可付きsession endpointで読み戻せる。成功結果のbindingが
開始時と違えば拒否する。v1/v2は元bytesを版別のexclusive backupへ保全して移行し、
過去に観測していないbindingは`null`のままにする。これはKB admissionをHTTP経路へ
接続したものではない。開始前の失敗にはsessionを捏造せず、必要なcallerがprepare callbackを
既存のoperation/evidence sinkへ保存する。第二のTask台帳は作らない。

expected digestを入力自身から受け取るだけでは真正性を得られない。現在のKB/Work ownerがsourceを照合し、取消・変化・期限を推論直前と結果利用前にも確認する必要がある。helperはファイルやACLを開かず、渡された現在pinと比較するだけである。

`task_binding`は引き続き`not_connected`。新規Task登録、永続session resume、Work状態更新、権限付与、配備、Public Beta、Human GOは追加していない。

## 検証

- Node試験でcontextの内容・source版、不一致、未解決、期限、予算、stdin一致、失敗後の開始観測、observer失敗/非同期/取消を確認する。
- `test_knowledge_context_binding.py`は実KB CLIを別processで起動。fixtureへ合成訂正を入れ、context/source digestとstdinが変わること、古いcontextを新しいsource pinで拒否することを既存runnerまで通す。model部分はfixtureで、意味理解の試験ではない。
- OSが起動する実Node子プロセスを合成executorとして使い、受信したUTF-8 stdinのSHA-256と準備・開始・完了のbinding一致を検証する。実modelの推論を行うものではない。
- 過去の実Codex観測をこのrevisionの受入へ流用しない。この移行では実Codex CLI・provider・非公開のoperator receiptを使用していない。

```sh
node --test --test-reporter=tap tests/node/test_codex_input_binding.mjs tests/node/test_codex_brief_bridge.mjs
python -B -m unittest discover -s tests -p test_knowledge_context_binding.py -v
```

実CLI検証はoperatorの既存account・binary hash・model・許可された入力でのみ行う。CIから実modelを呼ばない。callbackやrequested sandbox設定だけで、OS sandbox・provider境界の全受入とはしない。
