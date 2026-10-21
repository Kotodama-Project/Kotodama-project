# OpenAIへの役割分担

確認日: 2026-10-21。公式資料が説明する能力と、このアカウントで実際に接続・受入した結果は区別します。
**まず製品を直接使います。Agents APIで旧runtimeを作り直すことはしません。**

| 仕事 | 既定の手段 | 終了する独自開発 |
|---|---|---|
| 調査、実装、分担、長い仕事の継続 | Codex。長い仕事では利用可能な[Goal mode](https://learn.chatgpt.com/docs/long-running-work) | Task loop、swarm、worker/critic管理、retry/checkpoint基盤 |
| 継続責務と複数仕事の追跡 | 必要時に[Dots](https://learn.chatgpt.com/docs/dots) | resident agent、agent registry、A2A hub |
| 定期点検・follow-up | [Scheduled tasks](https://learn.chatgpt.com/docs/automations) | 独自scheduler・監視UI |
| 資料作成と共有 | [Work](https://learn.chatgpt.com/docs/get-started-with-work)、必要時に[Space](https://learn.chatgpt.com/docs/space) | 独自GUI・Company OS・Cloudflare OS |
| プロジェクト整理 | [Projects](https://learn.chatgpt.com/docs/projects)と対象GitHub repo | Project DB、Task関連付けAPI、全8階層engine |
| 背景の想起 | [Memories](https://learn.chatgpt.com/docs/customization/memories)と元資料 | 汎用memory、OKF検索・Context Platform |
| 外部サービスへの接続 | 既存の[plugins](https://learn.chatgpt.com/docs/plugins) | 先回りしたDiscord/Luma/CRM adapter |
| 目的・訂正・採否・根拠 | 対象repoの文書・Issue・PR・CI | Company Pack審査engine、独自causal ledger |

Dots/Spaceなどが利用できなくても、Codex＋GitHubの基本経路はそのまま使います。
新しいpluginや連携を必要条件にせず、実際に必要な機能と権限だけを確認します。

## APIを使う条件

実案件で製品の不足が再現し、専用製品への組込みが必要な場合にのみ[Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview)を候補にします。公式のharnessへsession・実行管理を任せます。APIの認証・課金・実行環境は製品のログインとは別に確認します。

専用の音声体験が必要な個別案件では[GPT-Live](https://developers.openai.com/api/docs/guides/live)または[Realtime API](https://developers.openai.com/api/docs/guides/realtime)を評価します。汎用の言霊Botを先に復活させません。Discord固有の多人会話・発話者識別・録音の要求がnative機能で満たされるとは、この資料だけでは断定しません。

## 保持する境界

- Codex local memory、ChatGPT memory、Dotのnotesは同じstoreではありません。必須ルールと現在の判断は元の文書に置きます。
- OpenAI製品を使っても、旧local-first・権限・保持・監査・復元保証を自動で継承しません。業務データを無条件に移送しません。
- 公式資料上の対応は、特定accountでの接続・業務受入の証拠ではありません。利用可否を確認し、成果を読戻します。
- 独自接続を減らす判断は[2026-10-21の方針](DECISIONS.md)です。OpenAIが旧言霊の全機能を同一仕様で実装済みだという主張ではありません。
