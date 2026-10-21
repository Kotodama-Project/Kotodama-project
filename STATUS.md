# 現在地

方針更新: 2026-10-21

| 対象 | 状態 |
|---|---|
| 製品の役割 | OpenAI製品で仕事を進めるための最小の手順と判断記録 |
| active source | README、依頼の型、運用・移行文書、GitHub用の検査 |
| 独自Company OS | 開発終了。runtime、DB、swarm、GUI、配備・package・release入口をmainから削除 |
| 旧source | `50ca4d2cf0c0e0e64cba17d8f3bc34fba2634b5b`に保全。[復旧と取り扱い](docs/RETIREMENT.md) |
| 旧環境 | 稼働・consumerの参照先・DB・保持データは未移行。ソース削除で停止・削除したとは扱わない |
| OpenAIの利用 | Codex＋GitHubが基本。Dots/Space等は利用可能な場合に選択。全製品の接続・アカウント受入を主張しない |
| 旧Public Beta | 計画終了。公開Bot・会社OSの提供を約束しない |

検査結果は各PRのCIを正本とします。この文書にテスト件数や変わり続けるheadを複製しません。
旧版の検証実績は旧版に対する記録であり、新構成の実利用証拠ではありません。
[残る作業](ROADMAP.md) · [方針変更](docs/DECISIONS.md)
