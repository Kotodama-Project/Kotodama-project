# Discordから使うKotodamaの最小構成

このrevisionは、カジュアル版で先行した汎用実装を公開本体の
[任意ランタイム](../runtime/discord-template/README.md)として取り込む候補です。
別製品ではなく、KotodamaをDiscordから使う最小構成です。組織の導入や他adapterは必須ではありません。

## 導入

リポジトリを取得後、`runtime/discord-template`を作業ディレクトリにして、
同ディレクトリのREADMEに従ってNode 24、固定依存、Bot、処理対象、
ローカルASRとモデル接続を設定します。実際のcredentialや参加者情報は各利用者の
private設定に置きます。このリポジトリには既定の接続先や利用可能なキーはありません。

## 取り込んだ範囲

- 固定VCの在室確認、話者別入力、停止・再開、privacy scope。
- ローカル日本語ASRを確定Sourceとする選択肢。未呼びかけ時はLiveを起動しません。
- 同一Liveセッションへbackend結果を戻す複数ターンとローカル再生の割り込み。
- Luna Responses analyzer、context/output上限、token使用量とLive時間の記録。
- 既存のlocal Task owner、訂正、限定worker、成果の検証。remote ownerは任意の接続契約。

ASR原文は認識結果であり誤り得ます。正しい人間の意図や実行権限と同一視せず、
訂正と元の出典を保持します。現行の呼びかけ中心の実装は、雑談への自然な自発参加や
既存許可内のすべての自走を完成したものではありません。

## 統合判断と未受入

公開候補[#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69)は
room/workspace・複数transportの基盤、[#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71)は
PythonによるLive制御候補です。今回のNodeランタイムとは同時に同じVCを所有させません。
それぞれの汎用化・既存Source/Task ownerへの接続を確認してから採否を決め、
未統合stackを丸ごと依存として追加しません。

この導入候補はpublic mainの既存Company Pack実行や確認Gatewayへ
自動接続済みではありません。個人構成ではlocal ownerを一つ選び、
組織構成では既存ownerへ明示接続します。Taskや知識の二重正本を作らない統合は残件です。

実マイクでは一度の返答後に継続応答が不安定だった観測があり、
ローカルASRのモデル・認識・開始条件を修正中です。
合成テストやAPI応答を連続実聴の成功に置き換えません。
公開Botの提供、音声会話の品質保証、組織データのsecurity受入、Public Beta GOは含みません。

## 出典と検証

取り込み元はKotodama contributorsのMITライセンスのテンプレート、
source revision `17d64637baca6e6595394d9cfcc53b8c554e72a7`です。
そのLICENSEとdocs/PROVENANCEをディレクトリ内に保持します。
privateなGit履歴、実設定、音声、会話、credentialを移していません。
以後の汎用実装の統合先はこの公開本体とし、先行テンプレートとの変更の分岐を整理します。

GitHub CIではLinux/Windowsでランタイムのテストと公開情報チェックを実行します。
外部モデル、Discord認証、実音声はCIで使用しません。
