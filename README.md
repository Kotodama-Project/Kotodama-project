# Kotodama

**会話を、監査できる意図・仕事・成果・学習へつなぐ Local-first Company OS。**

Kotodama is a local-first Company OS that turns conversation into auditable intent, work, results, and learning. English summary: [README.en.md](README.en.md).

> [!IMPORTANT]
> このリポジトリは **Incomplete Public Preview** です。公開しているのは Company Pack の schema・validator・review chain、runtime と evidence の候補、Discord runtime の候補です。Public Beta の受付、Discord 招待、公開 Voice Bot は提供していません。公開面の既定は `NO_GO_UNPUBLISHED` で、validator や CI の PASS は install、deploy、provider 接続、Promotion、Current Truth、Final Human GO を意味しません。最新の境界は [STATUS.md](STATUS.md)、未完了の gate は [ROADMAP.md](ROADMAP.md) にあります。

## 何を作っているか

会話・音声・Issue・文書から意図を検知し、足りない要件だけを確認して仕事へ分解し、成果と検証証拠を残して採用を判断し、会社の知識へ戻す。この鎖を短絡しないまま速く回すための部品を、Evidence Chain、Company Pack、Context Platform、AI Workforce、そして Cloudflare edge と公式 Cloudflare OS を基盤として作っています。

同じ製品の中で、利用の場面を選べます。

- **仕事を進める**: Company Pack と review chain で、依頼を Work Order、Verification Receipt、Promotion まで辿る。
- **「OK」の後は agent に任せる**: 人が一度許可した範囲で agent swarm が調査・実装・検証を自律的に進め、判断材料や権限が足りないときだけ人へ戻す。設計方向であり、`main` にあるのは限定 Task 実行までです。
- **Voice channel で過ごす**: 楽しく過ごす、一緒に考える、必要なときだけ仕事を進める、のモードを選ぶ。雑談を勝手に仕事や追加の権限へ変えません。

設計の全文は [docs/OVERVIEW.md](docs/OVERVIEW.md)、方向と現在地の対応は [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md) と [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md) にあります。

## 5 分で試す

Git と Python 3.12 だけで、Company Pack の review chain（13 steps）を一時 workspace で完走させます。外部接続、credential、runtime は不要です。

```bash
git clone https://github.com/Kotodama-Project/Kotodama-project.git
cd Kotodama-project
python -S -B tools/smoke_company_pack_review_chain.py
```

PowerShell では `python3` の代わりに `python` を使います。成功すると `"status": "PASS"` と `"public_beta": "NO_GO_UNPUBLISHED"` を含む一行 JSON が返り、`claims` はすべて `false` です。読み方と次の一歩は [5-minute tour](docs/FIVE-MINUTE-TOUR.md) にあります。

## 使い方を選ぶ

| やりたいこと | 今日 `main` でできること | 入口 |
|---|---|---|
| Company Pack を自分の会社の候補として編集し検査する | initializer、customization checker、validator、Catalog、Review Bundle（read-only / candidate-only） | [Starter Walkthrough](docs/STARTER-WALKTHROUGH.md)、[CLI Reference](docs/COMPANY-PACK-CLI-REFERENCE.md) |
| Discord / Voice で使う | `runtime/discord-template`。Node 24、Discord Bot、モデル接続が前提。local ASR と Live 会話、限定 Task worker。実マイクの連続応答、2 人 30 分の会話、別設定での再現は未受入 | [Discord runtime](docs/DISCORD-RUNTIME.md) |
| 既存 Task に結び付けて Company Pack を実生成し、確認・訂正する | `tools/run_company_pack_task.py` と local review gateway | [Task-bound execution](docs/COMPANY-PACK-TASK-EXECUTION.md)、[Gateway](runtime/local-review-gateway/README.md) |
| 会社の runtime を配備する | Compose minimum / Proxmox segmented の lifecycle contract と validator（live receipt なし）。Cloudflare edge と公式 Cloudflare OS の候補（未 upload、未 deploy） | [Installation Lifecycle](docs/INSTALLATION-LIFECYCLE.md)、[Cloudflare OS](docs/CLOUDFLARE-OS-ADOPTION.md) |
| agent swarm に任せる、知識基盤を使う | open PR の候補（#67、#34〜#36 と #48、#49、#61）。`main` には未統合 | [PROJECT-MAP](docs/PROJECT-MAP.md) |

## 今 `main` にあるもの、候補、方向

| 面 | `main` | 候補（未統合） | 方向 |
|---|---|---|---|
| Company Pack / Evidence Chain | 9 Blocks、9 Records、3 MOCs の starter、schema と validator、review chain、smoke | | lane ごとの Promotion policy |
| Session / conversation ledger | schema と validator | | runtime への取込 |
| Discord / Voice | `runtime/discord-template` | Live 制御と room 別 workspace（#69、#71） | 15 分 rotation、Voice-to-Verified-Handoff、GrillU |
| Agent swarm / 自律実行 | 限定 Task 実行 | Task swarm、agent lifecycle、migration ledger（#67、#34〜#36） | 「OK」後の Goal Completion Loop、reversible delegation |
| 知識・Context | | OKF control plane（#48、#49、#61） | Context Gateway、TiDB 評価 |
| Runtime | Compose / Proxmox contract、Cloudflare candidate | | Cloudflare edge と公式 Cloudflare OS を基盤にした配備 |
| 組織・事業 | | | Resident Clone、Agent Foundry、AI Business Loop |

状態の正本は [STATUS.md](STATUS.md) です。README は projection であり、Human Decision や Current Truth ではありません。

## 仕組みの骨格

```text
Source Evidence → Intent Candidate → Human Decision → Work Order → Capability Grant
→ Change Candidate → Verification Receipt → Promotion Decision → Current Truth
```

各段階がそれだけでは何を作らないか、Company Pack の Blocks / Records / MOCs との対応、Voice と GrillU の設計、Local-first architecture の表は [docs/OVERVIEW.md](docs/OVERVIEW.md) に全文があります。用語は [docs/OVERVIEW.md#用語](docs/OVERVIEW.md#用語) を参照してください。

## 文書の地図

- 現在地と gate: [STATUS.md](STATUS.md)、[ROADMAP.md](ROADMAP.md)、[docs/HISTORY.md](docs/HISTORY.md)（過去の revision 履歴）
- 方向: [docs/PRODUCT-DIRECTION.md](docs/PRODUCT-DIRECTION.md)、[docs/OWNER-INTENT-COMPANY-AGI.md](docs/OWNER-INTENT-COMPANY-AGI.md)、[docs/PROJECT-MAP.md](docs/PROJECT-MAP.md)
- 使う: [5-minute tour](docs/FIVE-MINUTE-TOUR.md)、[Discord runtime](docs/DISCORD-RUNTIME.md)、[Template Guide](docs/TEMPLATE-GUIDE.md)、[Validation Guide](docs/VALIDATION.md)、[Runtime candidates](runtime/README.md)
- 設計の全文: [docs/OVERVIEW.md](docs/OVERVIEW.md)

## 参加する

Issue と Pull Request の手順は [CONTRIBUTING.md](CONTRIBUTING.md)、相談は GitHub Discussions、脆弱性は [SECURITY.md](SECURITY.md)、それ以外の問い合わせは [SUPPORT.md](SUPPORT.md)、行動規範は [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) にあります。エージェントの開始手順は [AGENTS.md](AGENTS.md) です。

## ライセンス

Kotodama がライセンスを設定できるコードは [MIT License](LICENSE)（SPDX identifier: `MIT`）で提供します。第三者の条件と移植部分の出典は [docs/LICENSE-SCOPE.md](docs/LICENSE-SCOPE.md) を参照してください。
