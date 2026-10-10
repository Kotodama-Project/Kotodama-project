# Skillsの入力と成果を確認する

Skillsは、要求から成果までの手順を再利用するための説明です。権限やTaskの
正本にはなりません。構成は用途で選び、既存のownerへ戻します。
planでは合意・根拠の候補とowner参照を返し、既に許可されたapplyの範囲では
そのownerへ記録します。receiptの`changed`は実際の更新有無を表します。

| 用途 | 選ぶSkill | 完了として確認すること |
|---|---|---|
| 要求を固める | `kotodama-intent`、必要なら`kotodama-plan` | 既知の事実を調べ、未解決の選択だけ質問し、合意と受入条件を残す |
| 根拠を調べる | `kotodama-research` | 有効な根拠を再利用し、主張と出典・revision・鮮度を対応させる |
| 開発する | `kotodama-implement`、`kotodama-validate` | 依頼の受入条件と実際の変更・検証結果を対応させる |
| 訂正して文章を返す | runtimeの`shareable-invitation` | 最新の訂正、読者、共有範囲を成果へ反映し、内部メモを共有物へ混ぜない |
| 再開する | `kotodama-handoff` | 合意、訂正、未完了条件と根拠を引き継ぎ、現在の状態を照合する |

依存するSkillを名前で呼ぶだけでは、その本文がworkerに届いた証拠になりません。
runtimeの明示的な選択・入力束縛は[Skill delivery](../runtime/discord-template/docs/SKILL-DELIVERY.md)、
仕事ごとの権限と判断待ちは[Judgment status](../runtime/discord-template/docs/JUDGMENT-STATUS.md)で
確認します。ホストのSkills探索やプラグインを一括で有効にする必要はありません。
公開参照Skillと、任意のworker workspaceに置くSkillは別の配置です。

## 自動で確認できる範囲

Node 24と、runtimeのlockに固定した依存を用意したcheckoutで実行します。

```text
node runtime/discord-template/tools/evaluate-skill-workflows.mjs
```

このコマンドは固定した5組のローカルテストを順番に実行し、JSONをstdoutへ返します。
新しいTask、Decision、モデル呼出やproviderへの書込みは作りません。
各組は90秒、出力2 MB、個々のテストは30秒までです。入力snapshotは宣言した
runtimeのsource/tests/tools/bin、packageとlock、対象Skillsの内容digestです。
依存の実ファイル、private data、実環境、モデルの理解までは束縛しません。

| 評価組 | 実際に確認すること | 自動PASSだけでは分からないこと |
|---|---|---|
| `skill_delivery` | 明示的選択、固定HEAD、本文とstdinのdigest、実行中driftの拒否 | モデルがSkillを理解し従ったか |
| `requirements_clarification` | 一度の質問、同じTaskへの接続、既存grantの取消反映 | 質問や推奨案の質 |
| `research_context` | 長い文脈のページ読込、出典・訂正・閲覧範囲の保持 | 調査の結論や鮮度判断の質 |
| `writing_corrections` | 訂正の同じTaskへの接続、共有範囲、privateな入力の保護 | 文章の適切さと読者の受入 |
| `development_verification` | 実CLI fixture、成果と検証の束縛、未検証の拒否 | 実モデルでの開発能力と依頼者の受入 |

全組の終了codeとTAP件数が整合し、skip/todoがなく、前後の入力digestが一致した場合だけ
`PASS`です。失敗は`FAILED`、skip/todoは`PARTIAL`、不明な終了・timeout・入力driftは
`UNKNOWN`として非zeroで終わります。実Docker verifierの前提がない環境では、その既存
テストのskipを隠さず`PARTIAL`にします。子プロセスの本文・エラー文は出さずdigestを残します。
既存のLinux実隔離試験を準備した場合は、その明示設定`KOTODAMA_TEST_VERIFIER_IMAGE`を
子テストへ渡します。他のprovider認証や任意の環境値は評価のために追加しません。

これは全体の`pnpm test`、`pnpm check`、公開Skill auditor、Python suiteを置き換えません。
`modelReasoningEvaluated=false`、`liveProviderAccepted=false`と、未実行の成果受入を常に
残します。結果を保存する場合は既存TaskのVerification参照とし、別の承認台帳にしません。

## 実モデル・成果の受入

実モデルの評価には、同じTask、Source revision、選んだSkills、受入条件、使用枠を固定した
実行と、成果を読む独立reviewが必要です。下の入力はすべて架空とし、実顧客の本文・個人情報・
認証を公開fixtureへ入れません。静的文書に書いただけのケースを「実行済み」にしません。

| ケース | 合成入力と期待する成果 | 不合格の例 |
|---|---|---|
| 要求整理 | 既に決めた対象・予算と、未決の保存期間を渡す。未決だけを推奨案付きで尋ね、回答を既存Intent/Decisionへ反映する | 対象を聞き直す、前提が未決なのに下位の選択を決めさせる、合意が会話だけに残る |
| 調査再利用 | 有効な出典A、改訂された出典B、矛盾する出典Cを渡す。Aを再利用し、Bを再確認し、矛盾と不明点を結論に残す | 全調査をやり直す、古いBを現行扱いする、根拠のない推奨 |
| 文章訂正 | 招待文の日時と公開読者を後から訂正し、privateな運営メモも渡す。最新日時の共有用成果を返す | 元の日時が残る、運営メモや内部の判断記録を公開文へ含める |
| 開発完了 | 不具合の再現と受入条件を渡す。限定差分と有効な検証結果を同じTaskへ返す | 実行していないテストをPASSとする、成果ファイルの存在だけで完了とする |

reviewは各受入条件を`passed`、`failed`、`not_run`、`unknown`へ分け、理由と成果参照を
既存Verificationへ返します。要件が変わった場合は同じTaskを訂正して新しいrevisionを評価し、
以前のPASSを新しい成果へ使い回しません。入力が届いた証拠と成果の有用性の両方を確認します。

## 改善と停止

失敗した条件から、一つの手順・受入テスト・入力を修正して再評価します。説明が重複する場合は
共通契約へ寄せ、使われない手順を削ります。新しいSkillは既存のどれにも収まらない明確な
triggerと成果がある場合に追加します。権限失効、対象drift、使用枠超過や曖昧な判定では停止し、
質問や再試行を無制限に増やしません。評価のための外部操作は、その対象の既存許可に従います。

ロールバックは該当commitのrevertです。workerへの受け渡しは`worker.projectSkills`を空にし、
runtimeを再起動して無効化します。ローカル評価は`NO_GO_UNPUBLISHED`を変更しません。
