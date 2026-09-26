# Changelog

公開リポジトリの利用者向けの変更履歴です。形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は [Semantic Versioning](https://semver.org/lang/ja/) に従います。`-preview` の付く版は Incomplete Public Preview で、公開面の既定は `NO_GO_UNPUBLISHED` のままです。tag を push すると `.github/workflows/release.yml` が smoke report と source archive を作り、provenance attestation を付けて draft release を作ります。

This is the user-facing change log of the public repository (Keep a Changelog, Semantic Versioning). Versions with a `-preview` suffix are an Incomplete Public Preview.

## [Unreleased]

### Added

- A019 の registry 契約候補（task contract、task decomposition、worker capability catalog、worker result）を、[公開 PR #115](https://github.com/Kotodama-Project/Kotodama-project/pull/115) の固定 head `040a9becf0463e69887f126e30af6d38bdc02988` から再配置。出典表と非公開の元履歴走査 receipt は公開元の歴史的記録として維持し、この候補の独立 review は別 gate で検証する。4 schemas は candidate-only で、runtime や Task owner の統合ではない。追加 review により validator と試験を補強し、出典表の項目・既知の説明・receipt digest を固定して、サイズ上限と symlink・reparse point の拒否を読取り前に検査する。
- BecomeOne の A022 アーキテクチャ候補を再構成: 単一の記録 owner、複数 agent の協調、tool の監督、plan lifecycle の公開契約と、出典表・固定 bytes の validator。公開済み PR #114 の候補を現行 main に合わせ、今回の公開候補への独立 review を履歴証拠と分けて記録（`docs/architecture/README.md`）。

- Luna Task swarm を main に統合（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)。元は [#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67) と修復 [#85](https://github.com/Kotodama-Project/Kotodama-project/pull/85)）: owner に束縛した計画、予算（試行・同時実行・検証枠）、ACK 付きの agent 間通信、独立した検証者。offline fixture はモデルを呼ばずに動き、実 Codex / Luna の live 受入は未実施（`docs/LUNA-TASK-SWARM.md`）。
- このリポジトリの自動改善ループの運用契約（`docs/IMPROVEMENT-LOOP.md`）: 一周に一件、独立 review と必須 CI を通して merge し、main が赤くなれば revert する。agent がしないことと人が決めることを明記（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)）。
- 意図を抜き出して、すぐに走る: `discord.agentChannelIds` のテキストチャンネルでは、操作者の発言をBotへのメンションと同じに扱い、明確で実行に足りる依頼をすぐに仕事にする。会話（テキスト・音声）から仕事が走り始めると、依頼者へ即座にDMで件名と仕事のIDを届ける（[#101](https://github.com/Kotodama-Project/Kotodama-project/pull/101)）。
- 公開の Agent Skills（intent、plan、research、delegate、validate、implement、public review、surface audit、handoff の 9 件）と共通の運用契約 `docs/SKILL-OPERATING-CONTRACT.md`、読み取り専用の監査 `tools/audit_public_skills.py`。既存の `kotodama-luna-swarm` も同じ契約の形式にそろえた（[#17](https://github.com/Kotodama-Project/Kotodama-project/pull/17)）。
- OpenManus を Proxmox 上の限定 executor として評価するための候補: schema、例、読み取り専用の validator（必須の権限 binding と出力、文字列への秘密の混入、不正 UTF-8、空白だけの値を拒否）と試験。配備や採用は含まない（[#55](https://github.com/Kotodama-Project/Kotodama-project/pull/55)）。
- agent swarm と route binding の契約候補: schema、読み取り専用の preflight、否定の試験。main の Luna Task swarm との対応表を付けた（[#34](https://github.com/Kotodama-Project/Kotodama-project/pull/34)）。
- BecomeOne から移植した階層テンプレート（A017: project / phase / requirement / plan / task と session context）。移植元の固定 commit・作者の GitHub handle・ライセンスを載せた出典表（`migration/a017-hierarchy-templates.provenance.json`）と、Issue #25 の owner 判断・非公開の元履歴走査 receipt・独立 review による受入の記録を付けた（[#27](https://github.com/Kotodama-Project/Kotodama-project/pull/27) を main に合わせて取り込み）。

### Changed

- 公式 Cloudflare OS を知識・会話・Task・agent の共通フロントとする設計を明記。操作は既存の各 governed owner へ返し、BecomeOne は移植元から公開版に固定した consumer へ移る。画面構成・接続・provider 配備は未確定で、第二の正本や新たな実行権限は作らない。

- Discord runtime のレビュー指摘への対応を統合（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)。元は [#84](https://github.com/Kotodama-Project/Kotodama-project/pull/84)）: 会話解析の同時実行・待ち行列・日次/累計の上限、書込み Task の検証を Linux の固定 Docker image で隔離、成果ファイルの読込みを開いたファイルと名前の両方に束縛、再起動時は queued を paused・running を uncertain として保持（自動再実行しない）、必須 CI が Discord の Linux / Windows 試験を要求。`write_file` / `develop` には Linux・`worker.verify`・`worker.verification` の設定が必要になった（`runtime/discord-template/README.md`）。
- `/kotodama tasks` が一時停止中（paused）と状態確認中（uncertain）を日本語で表示し、`/kotodama ask` は解析を後回しにした場合にそう伝える（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)）。
- 必須チェック `Trusted repository validation` が Task swarm の Linux / Windows 試験も要求する。swarm の依存は共通 lock と分けた hash 付きの `requirements-task-swarm-ci.txt` から入れる（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)）。
- 公開面の識別子検査が、日本語に隣接して書かれた private host の番号も拾うようにした。残っていた 2 箇所を中立化し、`docs/REPOSITORIES.md` は公開リポジトリだけにした（[#108](https://github.com/Kotodama-Project/Kotodama-project/pull/108)）。
- README・STATUS・ROADMAP・CI などの文書を #99〜#102 後の main に合わせた。Task swarm を main 側へ移し、必須チェック 4 本、エージェント用チャンネル、知識基盤は #48 系・音声は Node runtime という owner 判断（2026-09-24）を反映した（[#112](https://github.com/Kotodama-Project/Kotodama-project/pull/112)）。

### Fixed

- Cloudflare edge の preview upload は、退役した作業 branch ではなく現在の `main` の先頭 commit だけを受け付ける（手動起動・Environment 承認は従来どおり）。候補検証 workflow は `main` への push でも走る。Cloudflare の説明文から古い「draft」表記を直した。
- 別のサーバーや別の Voice channel での入退室・ミュート切替で、Bot の返答が止まっていた（[#91](https://github.com/Kotodama-Project/Kotodama-project/issues/91)）。
- 実行中 Task の毎秒の権限確認が Discord REST を大量に消費し、一時的な API エラーで Task を失敗させていた。確認をチャンネル単位にまとめて 3 秒だけ再利用し、確認不能は 5 秒・3 回まで猶予する（[#92](https://github.com/Kotodama-Project/Kotodama-project/issues/92)）。
- 想定外のエラーが `OPERATION_FAILED` だけになり原因を追えなかった。`--verbose` または `KOTODAMA_DEBUG=1` で、秘密値を伏せた詳細を `debug.log` に記録する（[#93](https://github.com/Kotodama-Project/Kotodama-project/issues/93)）。
- CodeQL の指摘 2 件（成果ファイル読込みの確認と使用の間の競合、検証テストのコード組立て）（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)）。
- Task swarm が Windows で失敗していた（ディレクトリ一覧の link 数を信用して既存 payload を拒否、SQLite 接続の閉じ忘れ）。
- Windows の CI で Chocolatey の配布元が一時的に 406 を返すと、ffmpeg が入らないまま導入の step が成功扱いになり、後の音声の試験が失敗していた。導入を 3 回まで試し、それでも無ければ導入の step で止める。

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
- release workflow（`.github/workflows/release.yml`）: tag push で smoke report と source archive を作り、provenance attestation を付けて draft release を作る（[#97](https://github.com/Kotodama-Project/Kotodama-project/pull/97)）。

### Changed

- 製品方向の補足（2026-09-13 / 14）: Company OS、Evidence Chain、Cloudflare edge と公式 Cloudflare OS 基盤を徹底して作りながら、Voice channel では「楽しく過ごす / 一緒に考える / 必要なときだけ仕事を進める」のモードを選べる。「OK」の後は agent swarm が許可範囲で自律的に進める体験を最重要とする（`docs/PRODUCT-DIRECTION.md`）。
- private な runtime 識別子を公開 template の文書・コメント・テストから除去（[#90](https://github.com/Kotodama-Project/Kotodama-project/pull/90)）。
- action の pin 検査を「action 名 + 40 桁 SHA + version コメント」に変え、正当な Dependabot の更新で必須 CI が壊れないようにした。`actions/checkout` を v7.0.1 に更新（[#82](https://github.com/Kotodama-Project/Kotodama-project/pull/82)。この版の tag の commit）。

### Not included

- Voice の実マイク E2E、2 人 30 分の会話、別設定での再現（`runtime/discord-template/docs/ACCEPTANCE.md`）。
- agent swarm、OKF control plane、Slack / Teams / Salesforce adapter（open PR と Issue の候補のみ）。
- live Compose / Proxmox / Cloudflare deployment、Public Beta、Final Human GO。

[Unreleased]: https://github.com/Kotodama-Project/Kotodama-project/compare/v0.1.0-preview...HEAD
[0.1.0-preview]: https://github.com/Kotodama-Project/Kotodama-project/releases/tag/v0.1.0-preview
