# 公開リポジトリと更新のしかた

`Kotodama-Project` organization が公開しているリポジトリと、その関係です。非公開リポジトリの一覧と lifecycle（archive / transfer / delete の判断）は非公開側で管理します（Issue #23）。

| リポジトリ | 役割 | 更新のしかた |
|---|---|---|
| [Kotodama-project](https://github.com/Kotodama-Project/Kotodama-project) | 製品本体。docs、schema、validator、runtime 候補、Discord template の source | ここで開発する（製品事実の owner） |
| [discord-voice-template](https://github.com/Kotodama-Project/discord-voice-template) | Discord 音声 template の standalone 版（GitHub の template repository） | 手編集せず、このリポジトリの `runtime/discord-template` から書き出して更新する（移行中。Issue #30） |

## 運用の約束

- Kotodama 由来の code と docs は organization 配下（既定 private）に置き、個人アカウントのリポジトリでは育てない。
- 公開する成果物は monorepo（Kotodama-project）を source とし、standalone repo はそこから生成する。
- 公開リポジトリを増やすときは、この表に役割と更新のしかたを 1 行追加する。
