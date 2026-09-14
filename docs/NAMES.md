# 名前の系統（現状と提案）

同じものを指す名前が組織・リポジトリ・パッケージ・CLI で分かれています。この文書は 2026-09-14 時点の現状を 1 表にまとめ、提案を owner 判断待ちとして分けて記します。提案は決定ではありません。

## 現状

| 対象 | 現在の名前 | 出典 |
|---|---|---|
| 製品 | Kotodama / ことだま | README |
| GitHub organization | `Kotodama-Project` | GitHub |
| 公開の製品リポジトリ | `Kotodama-project`（大文字小文字が org と異なる） | GitHub |
| 移行後の公開リポジトリ名（計画） | `kotodama` | Issue #24 |
| 公開 Python package（計画） | `kotodama-core` / import `kotodama_core` | Issue #26、#28 |
| CLI（計画） | `kotodama`（alias `ktdm`） | Issue #26 |
| Discord template（monorepo 内） | `runtime/discord-template`、package.json name `kotodama-discord-template` | このリポジトリ |
| Discord template（公開 standalone） | repo `discord-voice-template`、package.json name `kotodama-discord-template` | GitHub |
| private 側の evidence snapshot | repo `ktdm` | GitHub |
| テストの一時ディレクトリ接頭辞 | `ktdm-` | `runtime/discord-template/tests` |
| 旧 URL | `dj-thank/Kotodama-project` は organization transfer の redirect（fork ではない） | GitHub |

## 提案（owner 判断待ち）

1. 製品名は Kotodama、org は `Kotodama-Project`、公開リポジトリは `kotodama` に統一する。rename は「移行完了後」ではなく、名前の決定と同時に行う（GitHub は web / git とも redirect する）。
2. Discord template は repo 名と package 名を一致させる（`discord-voice-template` を `kotodama-discord-template` に rename するか、package を `@kotodama-project/discord-template` にする）。source は monorepo の `runtime/discord-template` とし、standalone repo は CI が生成する成果物にする。
3. `kotodama-core` は公開 package が実在するまで文書に書かない。CLI は `kotodama` を umbrella とし、`ktdm` は短縮 alias と private 基盤の接頭辞に限る。
4. 個人アカウント側に `Kotodama-project` と同名のリポジトリを作らない（redirect が消え、旧 worktree の remote が別リポジトリを向く）。

決定したら、この表を更新し、他の文書はこの表へのリンクだけを持つようにします。
