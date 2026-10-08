# 名前の系統（現状と提案）

同じものを指す名前が組織・リポジトリ・パッケージ・CLI で分かれています。2026-10-08の#26に対する実装方式の委任に従い、Python配布候補と既存Node CLIの並存方針を反映しました。未採用のrename案は別に残します。

## 現状

| 対象 | 現在の名前 | 出典 |
|---|---|---|
| 製品 | Kotodama / ことだま | README |
| GitHub organization | `Kotodama-Project` | GitHub |
| 公開の製品リポジトリ | `Kotodama-project`（大文字小文字が org と異なる） | GitHub |
| 移行後の公開リポジトリ名（計画） | `kotodama` | Issue #24 |
| 公開 Python package（未公開の配布候補） | `kotodama-core` / import `kotodama_core` | [package契約](../python/README.md)、Issue #26、#28 |
| user-facing CLI | Nodeの`kotodama`を維持 | `runtime/discord-template/package.json` |
| Python診断CLI | `kotodama-core`。`ktdm`は追加しない | `pyproject.toml`、private互換はIssue #26 |
| Discord template（monorepo 内） | `runtime/discord-template`、package.json name `kotodama-discord-template` | このリポジトリ |
| Discord template（公開 standalone） | repo `discord-voice-template`、package.json name `kotodama-discord-voice-template` | GitHub |
| private 側の evidence snapshot | repo `ktdm` | GitHub |
| テストの一時ディレクトリ接頭辞 | `ktdm-` | `runtime/discord-template/tests` |
| 旧 URL | `dj-thank/Kotodama-project` は organization transfer の redirect（fork ではない） | GitHub |

## 提案（owner 判断待ち）

1. 製品名は Kotodama、org は `Kotodama-Project`、公開リポジトリは `kotodama` に統一する。rename は「移行完了後」ではなく、名前の決定と同時に行う（GitHub は web / git とも redirect する）。
2. Discord template は repo 名と package 名を一致させる（`discord-voice-template` を `kotodama-discord-template` に rename するか、package を `@kotodama-project/discord-template` にする）。source は monorepo の `runtime/discord-template` とし、standalone repo は CI が生成する成果物にする。
3. Python配布候補と既存Node CLIの名前は上表へ反映済み。privateの`ktdm`互換とumbrella routerは実consumer inventoryと移行受入の後で扱う。
4. 個人アカウント側に `Kotodama-project` と同名のリポジトリを作らない（redirect が消え、旧 worktree の remote が別リポジトリを向く）。

決定したら、この表を更新し、他の文書はこの表へのリンクだけを持つようにします。
