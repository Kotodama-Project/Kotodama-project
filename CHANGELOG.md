# Changelog

公開リポジトリの利用者向けの変更履歴です。形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は [Semantic Versioning](https://semver.org/lang/ja/) に従います。`-preview` の付く版は Incomplete Public Preview で、公開面の既定は `NO_GO_UNPUBLISHED` のままです。tag を push すると `.github/workflows/release.yml` が smoke report と source archive を作り、provenance attestation を付けて draft release を作ります。

This is the user-facing change log of the public repository (Keep a Changelog, Semantic Versioning). Versions with a `-preview` suffix are an Incomplete Public Preview.

## [Unreleased]

### Added

- Luna Task swarm を main に統合（[#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67) と修復 [#85](https://github.com/Kotodama-Project/Kotodama-project/pull/85)）: owner に束縛した計画、予算（試行・同時実行・検証枠）、ACK 付きの agent 間通信、独立した検証者。offline fixture はモデルを呼ばずに動き、実 Codex / Luna の live 受入は未実施（`docs/LUNA-TASK-SWARM.md`）。
- このリポジトリの自動改善ループの運用契約（`docs/IMPROVEMENT-LOOP.md`）: 一周に一件、独立 review と必須 CI を通して merge し、main が赤くなれば revert する。agent がしないことと人が決めることを明記。
- 意図を抜き出して、すぐに走る: `discord.agentChannelIds` のテキストチャンネルでは、操作者の発言をBotへのメンションと同じに扱い、明確で実行に足りる依頼をすぐに仕事にする。会話（テキスト・音声）から仕事が走り始めると、依頼者へ即座にDMで件名と仕事のIDを届ける。
- OpenManus を Proxmox 上の限定 executor として評価するための候補: schema、例、読み取り専用の validator（必須の権限 binding と出力、文字列への秘密の混入、不正 UTF-8、空白だけの値を拒否）と試験。配備や採用は含まない（[#55](https://github.com/Kotodama-Project/Kotodama-project/pull/55)）。

### Changed

- Discord runtime のレビュー指摘への対応を統合（[#84](https://github.com/Kotodama-Project/Kotodama-project/pull/84)）: 会話解析の同時実行・待ち行列・日次/累計の上限、書込み Task の検証を Linux の固定 Docker image で隔離、成果ファイルの読込みを開いたファイルと名前の両方に束縛、再起動時は queued を paused・running を uncertain として保持（自動再実行しない）、必須 CI が Discord の Linux / Windows 試験を要求。`write_file` / `develop` には Linux・`worker.verify`・`worker.verification` の設定が必要になった（`runtime/discord-template/README.md`）。
- `/kotodama tasks` が一時停止中（paused）と状態確認中（uncertain）を日本語で表示し、`/kotodama ask` は解析を後回しにした場合にそう伝える。
- 必須チェック `Trusted repository validation` が Task swarm の Linux / Windows 試験も要求する。swarm の依存は共通 lock と分けた hash 付きの `requirements-task-swarm-ci.txt` から入れる。

### Fixed

- Cloudflare edge の preview upload は、退役した作業 branch ではなく現在の `main` の先頭 commit だけを受け付ける（手動起動・Environment 承認は従来どおり）。候補検証 workflow は `main` への push でも走る。Cloudflare の説明文から古い「draft」表記を直した。
- 別のサーバーや別の Voice channel での入退室・ミュート切替で、Bot の返答が止まっていた（[#91](https://github.com/Kotodama-Project/Kotodama-project/issues/91)）。
- 実行中 Task の毎秒の権限確認が Discord REST を大量に消費し、一時的な API エラーで Task を失敗させていた。確認をチャンネル単位にまとめて 3 秒だけ再利用し、確認不能は 5 秒・3 回まで猶予する（[#92](https://github.com/Kotodama-Project/Kotodama-project/issues/92)）。
- 想定外のエラーが `OPERATION_FAILED` だけになり原因を追えなかった。`--verbose` または `KOTODAMA_DEBUG=1` で、秘密値を伏せた詳細を `debug.log` に記録する（[#93](https://github.com/Kotodama-Project/Kotodama-project/issues/93)）。
- CodeQL の指摘 2 件（成果ファイル読込みの確認と使用の間の競合、検証テストのコード組立て）。
- Task swarm が Windows で失敗していた（ディレクトリ一覧の link 数を信用して既存 payload を拒否、SQLite 接続の閉じ忘れ）。

## [0.1.0-preview] - 2026-09-14

最初の tag です。Public Beta の受付、Discord 招待、公開 Voice Bot、live deployment、Final Human GO は含みません。

### Added

- Company Pack の schema、validator、review chain、one-command smoke、5-minute tour（2026-08-02〜05 の公開 revision。経緯は `docs/HISTORY.md`）。
- 公開リポジトリの governance baseline: MIT root license、hash-locked CI、tracked credential hygiene、session / conversation ledger contract（[#18](https://github.com/Kotodama-Project/Kotodama-project/pull/18)、[#73](https://github.com/Kotodama-Project/Kotodama-project/pull/73)）。
- Task に束縛した Company Pack の実生成と local review gateway（[#75](https://github.com/Kotodama-Project/Kotodama-project/pull/75)、[#76](https://github.com/Kotodama-Project/Kotodama-project/pull/76)）。
- Discord runtime candidate `runtime/discord-template`: local ASR、継続 Live 会話、限定 Task worker、Voice channel のモード（[#79](https://github.com/Kotodama-Project/Kotodama-project/pull/79)、[#80](https://github.com/Kotodama-Project/Kotodama-project/pull/80)、[#81](https://github.com/Kotodama-Project/Kotodama-project/pull/81)）。
- STATUS / ROADMAP の現在化と `docs/HISTORY.md`（[#86](https://github.com/Kotodama-Project/Kotodama-project/pull/86)）。
- README を 80 行の入口に再構成、設計の全文は `docs/OVERVIEW.md`、`README.en.md`、docs lint（[#96](https://github.com/Kotodama-Project/Kotodama-project/pull/96)）。
- Issue form、CODEOWNERS、日本語の CONTRIBUTING と PR template、`docs/CI.md`、`docs/NAMES.md`、`docs/REPOSITORIES.md`（[#89](https://github.com/Kotodama-Project/Kotodama-project/pull/89)）。
- tracked text 全体の private 識別子検査（[#90](https://github.com/Kotodama-Project/Kotodama-project/pull/90)）と Discord Bot token 形の秘密検査（[#94](https://github.com/Kotodama-Project/Kotodama-project/pull/94)）。
- Dependabot の npm 対象に `runtime/discord-template` を追加（[#88](https://github.com/Kotodama-Project/Kotodama-project/pull/88)）。
- release workflow（`.github/workflows/release.yml`）: tag push で smoke report と source archive を作り、provenance attestation を付けて draft release を作る。

### Changed

- 製品方向の補足（2026-09-13 / 14）: Company OS、Evidence Chain、Cloudflare edge と公式 Cloudflare OS 基盤を徹底して作りながら、Voice channel では「楽しく過ごす / 一緒に考える / 必要なときだけ仕事を進める」のモードを選べる。「OK」の後は agent swarm が許可範囲で自律的に進める体験を最重要とする（`docs/PRODUCT-DIRECTION.md`）。
- private な runtime 識別子を公開 template の文書・コメント・テストから除去（[#90](https://github.com/Kotodama-Project/Kotodama-project/pull/90)）。

### Not included

- Voice の実マイク E2E、2 人 30 分の会話、別設定での再現（`runtime/discord-template/docs/ACCEPTANCE.md`）。
- agent swarm、OKF control plane、Slack / Teams / Salesforce adapter（open PR と Issue の候補のみ）。
- live Compose / Proxmox / Cloudflare deployment、Public Beta、Final Human GO。

[Unreleased]: https://github.com/Kotodama-Project/Kotodama-project/compare/v0.1.0-preview...HEAD
[0.1.0-preview]: https://github.com/Kotodama-Project/Kotodama-project/releases/tag/v0.1.0-preview
