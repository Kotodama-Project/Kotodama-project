# Discordから使うKotodamaの最小構成

`runtime/discord-template`は、カジュアル版で先行した汎用実装を公開本体の
[任意ランタイム](../runtime/discord-template/README.md)として取り込んだ実装候補です。
別製品ではなく、KotodamaをDiscordから使う最小構成です。組織の導入や他adapterは必須ではありません。

## 導入

リポジトリを取得後、`runtime/discord-template`を作業ディレクトリにして、
同ディレクトリのREADMEに従ってNode 24、固定依存、Bot、処理対象、
ローカルASRとモデル接続を設定します。実際のcredentialや参加者情報は各利用者の
private設定に置きます。このリポジトリには既定の接続先や利用可能なキーはありません。

## 取り込んだ範囲

- 固定VCの在室確認、話者別入力、停止・再開、privacy scope。
- ローカル日本語ASRを確定Sourceとする選択肢。既定のwake方式では未呼びかけ時はLiveを起動しません。speech方式も明示選択できます。
- 同一Liveセッションへbackend結果を戻す複数ターンとローカル再生の割り込み。
- Luna Responses analyzer、context/output上限、token使用量とLive時間の記録。
- 既存のlocal Task owner、訂正、限定worker、成果の検証。remote ownerは任意の接続契約。
- [#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)のレビュー対応: 会話解析の同時実行・待ち行列・日次/累計の上限、書込みの仕事（`write_file`・`develop`）はLinuxの固定Docker imageで隔離して検証（Linuxと`worker.verify`・`worker.verification`の設定が必要）、再起動時はqueuedをpaused・runningをuncertainとして保持し自動で再実行しない。別サーバー・別VCの状態変化で返答が止まる不具合などの修正（#91〜#93）。
- [#101](https://github.com/Kotodama-Project/Kotodama-project/pull/101)のエージェント用チャンネル: `discord.agentChannelIds`のチャンネルでは操作者の発言をメンションと同じに扱い、明確で実行に足りる依頼はすぐ仕事にして、依頼者へDMで件名と仕事のIDを届けます。

ASR原文は認識結果であり誤り得ます。正しい人間の意図や実行権限と同一視せず、
訂正と元の出典を保持します。現行の呼びかけ中心の実装は、雑談への自然な自発参加や
既存許可内のすべての自走を完成したものではありません。

PR #79でこのNodeテンプレートのsourceはmainへ統合済みです。新しい導入は[自然会話の設定例](../runtime/discord-template/docs/DISCORD-SETUP.md#自然会話を試す設定例)から確認できます。

## 統合判断と未受入

音声のruntimeはこのNodeテンプレートに一本化します（2026-09-24のowner判断）。
公開候補[#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69)（room/workspace・複数transportの基盤）と[#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71)（PythonによるLive制御）は
別runtimeとしては取り込まず、方針文書と、このruntimeに無い考え方だけを移します（[#30](https://github.com/Kotodama-Project/Kotodama-project/issues/30)）。
同じVCを二つのruntimeに所有させません。

この導入候補はpublic mainの既存Company Pack実行や確認Gatewayへ
自動接続済みではありません。個人構成ではlocal ownerを一つ選び、
組織構成では既存ownerへ明示接続します。Taskや知識の二重正本を作らない統合は残件です。

統合時点（2026-09-13）の実マイクでは、一度の返答後に継続応答が不安定だった観測があり、
ローカルASRのモデル・認識・開始条件の修正が残っています。
合成テストやAPI応答を連続実聴の成功に置き換えません。
公開Botの提供、音声会話の品質保証、組織データのsecurity受入、Public Beta GOは含みません。

## 出典と検証

取り込み元はKotodama contributorsのMITライセンスのテンプレート、
source revision `febd72de1313b51e5f22962401fae6629afca01e`です。
そのLICENSEとdocs/PROVENANCEをディレクトリ内に保持します。
privateなGit履歴、実設定、音声、会話、credentialを移していません。
以後の汎用実装の統合先はこの公開本体とし、先行テンプレートとの変更の分岐を整理します。

GitHub CIではLinux/Windowsでランタイムのテストと公開情報チェックを実行します。
外部モデル、Discord認証、実音声はCIで使用しません。
