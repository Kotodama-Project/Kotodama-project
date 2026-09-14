# Organization のリポジトリ一覧（現状と lifecycle の提案）

`Kotodama-Project` organization の 17 リポジトリを、2026-09-14 の読取に基づいて一覧にします。lifecycle は提案であり、archive / transfer / delete は依存（配備、submodule、webhook、secret）を確認した上での owner 操作です。Issue #23 の受入はこの表に束縛します。

| リポジトリ | 公開 | 最終更新 | 観測した内容 | 提案 lifecycle |
|---|---|---|---|---|
| Kotodama-project | public | 2026-09 | 製品本体。docs、schema、validator、runtime 候補、Discord template の source | **keep**（製品事実の owner） |
| discord-voice-template | public | 2026-09-13 | Discord template の standalone コピー（is_template）。monorepo と 67 / 86 file が一致 | **keep** を生成物として。手編集せず monorepo から生成する |
| discord-bot-template | private | 2026-09-13 | 同 template の以前の standalone コピー | **archive**（discord-voice-template に置換済み） |
| kotodama-discord-template | private | 2026-09-13 | 同 template の private twin。PR #1〜#3 を別途 merge、monorepo と 17 file 相違 | **archive**（未 push の枝を公開側へ取り込むか破棄を決めてから） |
| BecomeOne | private | 2026-08-21 | 移行元（donor）。human commit は 8/21 が最後、human PR 8 件は全て Draft、nightly の reality-guard が失敗し続け、Dependabot PR 41 件 | **maintenance / frozen donor**（README に凍結宣言、schedule workflow 停止、Dependabot は security-only） |
| ktdm | private | 2026-08-25 | 凍結した evidence snapshot | **archive** |
| n8n-workflows | private | 2026-08-21 | n8n workflow の backup と復旧手順（運用系） | **keep** |
| Kotodama-Agent | private | 2026-08-21 | systemd unit、egress hardening、`vendor/kotodama-rag` submodule を持つ稼働系の source の疑い | **maintenance**（配備との一致を確認するまで archive しない） |
| kotodama-rag | private | 2025-12-29 | Kotodama-Agent の submodule | Kotodama-Agent と同時に判断 |
| plot-weaver-ai | private | 2026-08-21 | 小説生成アプリ（Kotodama と無関係） | **transfer** to personal |
| dragon | private | 2025-12-18 | 学習用アプリ、1 commit | **transfer** to personal |
| kotodama-db | private | 2025-12-02 | 初期の DB / 認証実験 | **archive** |
| kotodama-chat | private | 2025-12-19 | 初期の chat UI（deploy script あり。Cloud Run 停止確認後） | **archive** |
| otodama | private | 2025-12-07 | 初期の音声→テキスト実験、README なし | **archive** |
| n8n | private | 2025-12-07 | 5 file。n8n-workflows に置換済み（含まれる JSON の秘密情報確認後） | **archive** |
| KotodamaClaw | private | 2026-02-26 | 3 commits、README 1 行 | **delete** |
| demo-repository | private | 2025-11-16 | GitHub の雛形。main と共通祖先を持たない `feature/discord-bot-update` 枝が 2026-09-02 に push されている | 枝の内容を回収してから **delete** |

## 運用の約束

- Kotodama 由来の code と docs は organization 配下（既定 private）に置き、個人アカウントのリポジトリでは育てない。
- 公開する成果物は monorepo（Kotodama-project）を source とし、standalone repo は CI で生成する。
- 新しいリポジトリを作るときは、この表に owner、lifecycle、後継を 1 行追加する。
