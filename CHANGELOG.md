# Changelog

公開リポジトリの利用者向けの変更履歴です。形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は [Semantic Versioning](https://semver.org/lang/ja/) に従います。`-preview` の付く版は Incomplete Public Preview で、公開面の既定は `NO_GO_UNPUBLISHED` のままです。tag を push すると `.github/workflows/release.yml` が smoke report と source archive を作り、provenance attestation を付けて draft release を作ります。

This is the user-facing change log of the public repository (Keep a Changelog, Semantic Versioning). Versions with a `-preview` suffix are an Incomplete Public Preview.

## [Unreleased]

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
