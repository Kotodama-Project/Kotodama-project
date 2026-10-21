# 旧Company OSの廃止とDiscord製品への移行

2026-10-21に独自Company OSの開発を終了しました。Discordの会話から仕事を進める体験は継続し、既存[音声repo](https://github.com/Kotodama-Project/discord-voice-template)へ必要な修正を選択して引き継ぎます。現在のmainは移行文書と開発用検査のみです。
旧runtime・package・Botの更新先としてmainを利用しないでください。

## 旧sourceの固定参照

- Commit: `50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b`
- 保存タグ: `archive/company-os-2026-10-21`
- [旧source全体](https://github.com/Kotodama-Project/Kotodama-project/tree/50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b)

履歴・旧テスト・ライセンス・検証記録は固定commitに残ります。active treeにarchiveコピーを作りません。
旧版への参照は復旧・移行調査用で、新規導入やセキュリティ保守の約束ではありません。
旧版で実際に稼働していたSHAがこのcommitと異なる場合、実際のpinと修正を先に保全します。

## mainから取り除いたもの

| 対象 | 処置と置換先 |
|---|---|
| `runtime/`、`python/`、package metadata・依存lock | 旧実装をmainから削除。思考・実行はOpenAIへ、必要なDiscord接続・訂正・保存の修正は音声repoへ選択移行（未完了） |
| `schemas/`、旧`templates/`、`examples/`、旧`tools/`・`tests/` | 独自台帳・13段審査・契約・fixture・性能基盤を削除。成果の確認は対象repoの検査へ |
| `knowledge/`、`governance/`、`migration/`、`experiments/` | 旧設計の公開projection・registry・候補を削除。原資料やprivateデータの削除ではない |
| `.agents/`、`.codex/`、`.claude/` | 旧機能を実行・再構築するスキルとagent設定を削除。短いAGENTSへ |
| 旧`docs/`、`CONTEXT.md` | 現行の方針・運用・移行文書へ縮小。過去の命令は現行要求ではない |
| 旧build/deploy/release workflow | mainから削除。新構成の検査のみを保持。過去branchの関連Actionsも個別に無効化 |
| 旧Issue・PR・milestone | 方針変更として終了。未達機能を完成扱いにしない |

## 既存稼働物で必要なこと

ソースから消すことと、稼働サービスやデータを消すことは別の作業です。この変更は以下を実施した証拠ではありません。

1. 管理者が非公開に、実際のservice・consumer・source SHA・更新元・起動方法・保存先・責任者を調べる。main自動追従の有無を確認する。
2. 既存の変更、実際の稼働SHA、復旧方法を保持し、必要なら旧sourceへ明示pinする。保存タグを作っただけでconsumerがpinされたとは言わない。
3. `kotodama.sqlite`とWAL/SHM、Source・Task・Project・訂正履歴、成果ファイル、音声archive、鍵、retention情報を保持する。移行前に件数・読戻し・復元を確認する。
4. 現在のreader/writer形式を確認する。特に[#95](https://github.com/Kotodama-Project/Kotodama-project/issues/95)と[旧PR #323](https://github.com/Kotodama-Project/Kotodama-project/pull/323)のretention markerは、private dual-reader受入が未確認のまま改名しない。
5. 稼働中の旧依存があれば[#12](https://github.com/Kotodama-Project/Kotodama-project/issues/12)等の既知の修正・脆弱性影響を実際の版に照合する。archiveしたことで修復済みにはならない。
6. 今も必要なDiscordの体験と仕事を後継へ引き継ぐ。旧本体・音声repo・実稼働の私有拡張の差分を確認し、必要な修正だけを選ぶ。未処理の仕事を照合せず新sessionへ再投入しない。権限と共有先を確認し、private sourceや会話・DBを一括アップロードしない。
7. 未処理Task・録音・保持・削除義務・rollbackを確認し、不要と確認したserviceだけを停止する。停止・移行後の結果を読戻して記録する。

このrepoの整理ではremote service、private consumer、DB、鍵、音声、別repoを変更していません。
別プロジェクトのActionsやサービスは一括停止しません。
旧runtimeの本番停止、全データ移行、OpenAI接続の受入は[残る仕事](../ROADMAP.md)で追跡します。

## 履歴の回収

cleanな別checkoutで、固定commitを参照します。現在の作業をresetしたり、稼働directoryをcheckoutし直したりしません。

```sh
git clone --no-checkout https://github.com/Kotodama-Project/Kotodama-project.git kotodama-retired-reference
git -C kotodama-retired-reference checkout --detach 50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b
```

これはsourceの回収だけです。依存install・process起動・既存DBへの接続は自動実行しません。
整理の撤回が必要なら、この変更のmerge commitを対象とするrevert PRで通常のreviewを行います。旧サービスの復旧は、実際の稼働pinとbackupを使います。

## Repositoryをarchiveする条件

このrepoと移行元repoは、後継の実音声・実仕事・成果返送の受入、未処理の仕事と保存データ、必要なIssue、出典・ライセンス、復旧先が引き継がれてから個別に判断します。保存タグはGitHub repositoryのarchive設定ではありません。BecomeOne等が移行元として凍結されていても、全移行済み・GitHub archive済みとは推論しません。
