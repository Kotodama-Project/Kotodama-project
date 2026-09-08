# Cloudflare OS + OpenMaus Unified Agent Control Plane

> Status: **candidate-only architecture / no runtime deployment**  
> Reviewed: **2026-09-08**  
> Workforce contract: [`governance/openmaus-integration.json`](../governance/openmaus-integration.json)  
> OS / platform composition: [`governance/cloudflare-os-integration.json`](../governance/cloudflare-os-integration.json)

## 1. Decision candidate

**Cloudflare OSをKotodamaの共通ワークスペースとして使い、その中にOpenMausBotを活用した全Agent管理画面を組み込む。Cloudflareは管理・共有・接続を、Proxmoxは隔離された実行環境を担う。**

OpenMausBotだけの別ポータルを新設する案は、この構成で置き換える。
`openmausbot_kotodama_control_surface` は共通画面の論理IDとして維持し、
そのホストをCloudflare OS、実装形態をnative Gadgetとする。第二のログイン、Task台帳、
承認正本、Knowledge正本、スケジューラーを追加する意味ではない。

```text
Human / existing entry points
  -> Cloudflare OS workspace
       -> Kotodama Workforce Console (native Gadget)
            -> Cap'n Web -> native Gatekeeper
                 -> existing Kotodama authority / shared Work records
                 -> restricted dispatch adapter + durable invocation journal
                      -> OpenMausBot harness / approved CLI on Proxmox
                      -> OS-native agent adapter / other external executors
                      -> dedicated computer VM (Docker-over-SSH)
                 <- status / artifact references / independent verification
```

上図は採用目標であり、今回のPRでnative Consoleや実行adapterを配備した図ではない。

## 2. Reuse before rebuilding

| Layer | Reuse / extend | Do not duplicate |
|---|---|---|
| Cloudflare OS | Workspace、Gadget、Blueprint、Cap'n Web、Gatekeeper、共有・観測・承認の仕組み | 独自OS shell、汎用MCP proxy、別のユーザー台帳 |
| OpenMausBot | Bot/Channel/Task UX、対応CLI、活動観測、computer panel、MCP接続 | KotodamaのWork/Grant/Knowledge正本 |
| Kotodama | 意図、Work Order、Agent登録、権限、検証、採用、OKFによる共有知識 | BotごとのCompany DB |
| Proxmox | CLI、ブラウザ、Docker computer、必要なローカル推論の隔離 | 全権限を持つ統括Agent |

Cloudflare OSのGadgetは外部harnessをそのままiframeで開く枠ではない。
固定点の公式設計では、Gadget UIはsandboxed iframe、通信は親から渡されたCap'n Web、
外部資源へのアクセスは明示されたbindingを通る [S1]。
したがって、OpenMausBot UIの必要な部分をnative Gadgetへ移植・再利用するか、
同等の薄いnative Consoleを作る。CSP解除、任意URL fetch、ブラウザへのharness token配布で
「埋め込み済み」にしない。ソース再利用時はlicense/noticeとupstream差分を保持する。

## 3. Existing Kotodama integration is a dependency, not deployed proof

既存のPR #45–#47には、公式OSへのnative Gatekeeperと要件整理Gadget、
private Codex bridge、その実行sessionの観測記録がある [S2][S3]。
2026-09-08の確認時点で #47 は未マージのDraftであり、このブランチにはそのruntimeを移植していない。

再利用するものはnative package/Blueprint構造、認証済みprincipalの対応付け、
source/grantのrevisionとdigest束縛、`authorizeObservation`、承認queue、
不明な送信結果を再実行しないinvocation journalである。

ただし既存bridgeは要件整理専用であり、任意command実行や会社Task完了を提供しない。
同じOS accountだけがbindingを観測でき、チーム全体のACL照合も未実装である。
そのendpointを汎用実行用へ拡張したり、そのままTunnelで公開したりしない。
新しいworker adapterは別のscope・transport・評価を持つ。

互換性基準は既存addonが使用するOS commit
`c0b6f3e52ff0ab8d44d290647e256936e88e6b57`。
「現在の最新版」という意味ではない。更新時はcore、starter、bindings、型生成、
native approval、observer検証、lockfileをまとめて固定・再評価する。

## 4. Five groups, one workforce

分類は **受付・統括 / 知識・調査 / 開発・実行 / 検証・監査 / 運用・改善** の5つ。
全体、担当別、project別、要対応、runtime別、検証待ちを同じデータから表示する。
同じAgentは複数group/projectへ参加でき、分類ごとに独立した仕事や知識を作らない。

対象にはOpenMausBotのBotだけでなく、Cloudflare OS内蔵Agent、外部CLI/ワークフロー、
一時的な子Agentも含める。子Agentは親Workに紐付けて展開表示する。
初期inventoryは各実行基盤の実在する一覧と突合する。未接続の対象は`unsupported`、
未観測は`unknown`として残し、登録件数だけで「全Agent統合済み」とはしない。

Agent cardは共通ID、purpose、group/project、authority、activation、runtime、
current/parent Work、最終観測、成果物、検証、cost、可能な操作を持つ。
観測期限切れを過去の`running`表示のまま放置しない。
停止非対応のadapterには有効なStopボタンを出さない。

## 5. One canonical owner per concern

| Concern | Owner / treatment |
|---|---|
| Goal / KGI | `governance/okf.json` |
| Knowledge ownership / freshness | `governance/knowledge-registry.json` |
| Agent portfolio / authority / activation | `governance/agent-registry.json` |
| Audit / autonomy | `governance/audit-policy.json` |
| Human Intent / Task / Work Order / Grant / Promotion | 既存Kotodamaの各責任主体を維持。今回新しい正本を作らない |
| OS workspace / Gadget data | 権限付きview、UI状態、参照。会社台帳をworkspaceごとに複製しない |
| OpenMaus transcript / invocation journal | 作業履歴・実行観測。Taskや承認の正本ではない |
| OKF / D1 / search index | 正本から再生成できる共有・検索projection。ACL/実行権限ではない |

共有対象の知識は作業メモ、出典付きcandidate、検証・採用済みを区別する。
同じWorkを引き継ぎ、objective、constraints、Source/Decision/Artifact refs、open questions、
verification requirements、authority boundaryを保つ。会話のコピペを引き継ぎ正本にしない。
全Agentへ全情報を注入せず、actor・目的・resource・現在の権限に基づいて取得する。

## 6. Use Cloudflare where it removes work

以下は**構成案**であり、サービスの有効化や課金を行う設定ではない。

| Service | Proposed use | Initial position |
|---|---|---|
| Workers | OSとGatekeeper、限定された管理API | OS標準構成を再利用 |
| Durable Objects | OS workspaceのstate。必要ならcommand/outbox専用の一意なjournal | 既存workspaceと機能重複させない |
| Dynamic Workers / Facets | Gadget隔離と能力binding | OS標準構成を再利用 [S1] |
| Access + Tunnel | 許可された人・serviceとProxmox側の限定adapterを接続 | hybrid段階で別途接続審査 [S6][S7] |
| R2 | 許可されたartifact bytesとdigest付きmanifest | artifact段階でopt-in [S8] |
| Workflows | 長時間の待機・段階的処理・再開 | owner切替とretry検証後 [S5] |
| Queues | burst吸収・非同期配送・dead-letter対応 | 必要になった段階。実行証明にはしない [S4] |
| D1 | 横断検索・集計の再生成可能なprojection | 必要な場合のみ |
| AI Gateway | 対応するAPI呼出の観測候補 | privacy・互換性検証後。CLI契約を透過接続できるとは扱わない |

WorkersへOpenMausBotのCLI、Docker、デスクトップ、重い推論を押し込まない。
それらはProxmox上のworkerへ残す。全サービスを最初から追加するのではなく、
OS標準機能 -> native Console -> hybrid adapter -> artifact -> 必要な高度化の順とする。

## 7. Gatekeeper and approval contract

読み取りはnative observation authorizerを通す。変更は`submitAction`で保持し、
実際の実行要求は`applyAction`側で扱う。既存の有効な許可はそのscope内で再利用するが、
Gadget共有、transport認証、UI clickを新しいCapability Grantへ変換しない。

Gatekeeperのsimulationと実際の実行は区別する [S1]。
`approval_pending`、`simulated`、`submitted`、`running`、`execution_settled`、
`verification_pending`、`verified_candidate`は異なる意味を持つ。
`applyAction`が送信を受け付けても、Task完了・成果の正しさ・Promotionにはしない。

native承認receiptとWork/操作/対象/payload digest/policy/grant revision/期限を束縛し、
実行直前にも現在の許可を確認する。送信結果が不明ならaction IDを保持して照合する。
元producerは独立検証が必要な結果を自己承認できない。

共有時はobserver本人の元資源へのアクセスを再確認する。会社内の別account、
同一project、閲覧リンクの所有だけでprivate結果を開かない。
metadata一覧、検索、status stream、成果DL、cacheにも同じ境界を適用する。
撤回後の新しい配信を止めるが、既に見た情報を取り戻せたとは主張しない。

## 8. Private networking without opening the management plane

推奨hybrid経路は、Proxmox側の限定adapterへ向くoutbound TunnelとAccess、
さらにアプリ側のWork/Grant検証。Tunnel自体は業務権限ではない [S6][S7]。
service接続は配備先を固定し、originでassertionの署名・issuer・audience・期限を検証する。
利用者指定URL、redirectによる資格情報転送、広いLAN routeを許可しない。

Proxmox API、SSH、Docker socket、OpenMausBot harnessをそのまま公開しない。
管理credentialは専用adapterだけに保持し、Agent、Gadget、prompt、public sourceへ渡さない。
harnessのloopback信頼を会社全体の認証境界として扱わない。

既存private brief bridgeのloopback/SSH構成は変更しない。現行pilotを残し、
新transportを別の合成入力環境で検証してから切替案を作る。
新しい接続にはallowlisted target/operation、最小権限、rate/byte/time/cost上限、
拒否テスト、mutation後readback、credential失効、緊急復旧経路が必要である。

## 9. Durable dispatch, not several schedulers

共通IDはcompany/work/agent/run/actionを分け、logical actionにidempotency keyと
request digestを固定する。単なるWork ID一つでは、一つのWork内の別操作を区別できない。
UI、OS Agent、OpenMaus routines、n8n、Webhookからの依頼も同じadmissionへ入れる。

実装時は一つのdurable command ownerがjournalとoutboxを同じtransactionで記録し、
consumer側も重複を拒否する。Workflowsを採用する対象では旧schedulerを停止・参照専用化し、
owner lease/epochで古い実行者をfenceする。Queuesはat-least-once配送であり、
外部side effectをexactly-onceにはしない [S4][S5]。

OpenMaus側が同一requestを確実に照合できない場合、送信後timeoutで盲目的に再送しない。
`unknown`で止め、履歴/receiptで照合する。停止要求と停止観測も分け、接続断は`unknown`。
承認待ち、取消、grant失効、予算枯渇を再起動後も保持する。

## 10. Proxmox execution and evidence

management、worker、verificationの3 trust zoneは維持する。
管理側に一般作業Agentを置かず、workerに正本や検証記録の書換え権限を持たせない。

OpenMaus BYO-VPSはDocker-over-SSHでcomputer containerを置く機能であり、
Agent processはharness側に残る。Docker groupは接続先でroot相当なので、
重要な既存サーバーと兼用しない。computer filesystemはdisposableとして成果を回収する [S9]。
Proxmox API操作はallowlisted VMと操作だけを専用adapterへ許可し、実機readbackを残す。

R2等へ保存する前に分類・redaction・保持方針を適用する。秘密情報、原会話、
provider session ID、任意のローカルファイルを自動的にcloudへ複製しない。
object key/digest/size/work/run/source revisionを束縛し、同じkeyへの無条件上書きを許可しない。
受領サービスがbytesを検査し、独立verifierがreceiptを出す。R2の整合性やファイル保存だけでは
意味の正しさ、監査記録の不変性、採用の権限を証明しない [S8]。
private storeを残す構成も同じref契約で扱える。

## 11. Hosting and migration

採用目標の第一候補は、**自社Cloudflare accountにOSを配備し、Proxmoxを実行基盤にする構成**。
公式starter経由の配備、必要な製品・plan・bindings・costを固定環境で確認する。
Cloudflare OS自体はearly accessである [S1]。

既存local pilotは残す。`pnpm run-local`やWrangler開発サーバーが起動したことを
production自前hostingの証拠にしない。固定点の公式READMEでは自前workerdの配備支援は
未完成である [S1]。Proxmox上の完全self-hostを選ぶ場合は、別の起動・更新・backup・
ACL・復元・障害試験を通す。今回どちらの配備も行わない。

cutoverは対象ごとに、inventory -> read-only比較 -> 合成Workの一往復 ->
既存owner停止とlease切替 -> canary -> 独立検証の順で行う。
rollback時も新ownerをfenceし、実行中/不明なactionを照合してから旧経路を戻す。
Cloudflare停止時は未許可の新規実行を止め、Proxmoxの緊急管理経路を残す。
二つの書込み経路を同時に復旧しない。

## 12. Implementation slices and acceptance

以下は**未実装の後続作業**。候補の格納先は、既存addon統合後の
`runtime/cloudflare-os-kotodama/`配下とする。現在のbrief packageは上書きしない。

| Slice | Deliverable | Acceptance before advancing |
|---|---|---|
| C0 / P0 | upstream/既存PR整合、native Workforce Blueprint、identity map、共通一覧 | 正式なOS上で構築。5groupとprojectを切替えても同じWork。未接続/期限切れ/権限外を区別 |
| C1 / P1 | native workforce Gatekeeper + private dispatch adapter + journal | 一つの合成Workが調査→実装→検証を同じIDで通る。重複/timeout/再起動/取消/権限撤回を試験 |
| C2 / P2 | observer ACL、検索/配信の権限、artifact回収、独立検証 | 別accountへの漏洩0。simulation/送信成功を実行証拠にしない。改変bytesと自己検証を拒否 |
| C3 / P3 | Cloudflare managed hosting、Access/Tunnel、限定Proxmox lifecycle | 未認証origin/不正audience/期限切れ/未知VMを拒否。実機停止readbackと隔離復元、cost上限を確認 |

core addonの受入には固定lockfile、型生成、RPC検証、authored-source typecheck、
Wrangler dry-run、native approve/reject/restart試験が必要。
Web画像が表示されたことだけではnative統合の合格としない。
既存 #45–#47 のacceptanceを本PRで満たしたとは扱わず、merge順を再確認する。

## 13. What this PR actually provides

既存OpenMaus構成契約と、本追記のOS/platform構成契約、JSON Schema、read-only validator、
合成入力による22件のオフラインテストを提供する。

```sh
python tools/validate_openmaus_integration.py --format markdown
python tools/validate_cloudflare_os_integration.py
python -m unittest discover -s tests -p 'test_cloudflare_os_integration.py' -v
```

追加テストは構成のguard、並行管理、shared Work、service段階、虚偽の配備主張、
未知field、重複key、非有限値、深すぎる/大きすぎるJSON、symlink/FIFO、CLIの拒否を確認する。
**runtimeの競合、Access JWT、native RPC、実機隔離を試験するコードではない。**
OpenMaus側の入力は明示的なsynthetic contract fixtureであり、実Agent一覧ではない。
このスライスで配備、課金、DNS、既存credential、Cloudflare設定、Proxmox設定を変更しない。
全Agent統合、正式採用、Capability Grant、Promotion、Current Truth変更、Human GO、Public Beta GOを宣言しない。

## 14. Sources and fixed points

- [S1: Cloudflare OS README / architecture, fixed compatibility point](https://github.com/cloudflare/cloudflare-os/blob/c0b6f3e52ff0ab8d44d290647e256936e88e6b57/README.md)
- [S2: Existing native Kotodama OS addon, pinned PR #47 snapshot](https://github.com/Kotodama-Project/Kotodama-project/blob/9a5b616c7974a37b123e024334a69dd4964ad017/runtime/cloudflare-os-kotodama/README.md)
- [S3: Existing bounded Codex bridge at the same snapshot](https://github.com/Kotodama-Project/Kotodama-project/blob/9a5b616c7974a37b123e024334a69dd4964ad017/runtime/codex-task-bridge/README.md)
- [S4: Cloudflare Queues delivery guarantees](https://developers.cloudflare.com/queues/reference/delivery-guarantees/)
- [S5: Cloudflare Workflows sleeping and retrying](https://developers.cloudflare.com/workflows/build/sleeping-and-retrying/)
- [S6: Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
- [S7: Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [S8: Cloudflare R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/)
- [S9: OpenMaus BYO-VPS at reviewed commit](https://github.com/milind-soni/OpenMausBot/blob/600e315cb7c3f61c214488678f7e6a99a7be157d/docs/byo-vps.md)
- [S10: OpenMaus MCP tool and authentication boundary](https://github.com/milind-soni/OpenMausBot/blob/600e315cb7c3f61c214488678f7e6a99a7be157d/docs/mcp-server.md)

S10のMCPはBot/Channel/Taskの確認・作成・変更、送信、wait、interrupt、model変更を提供するが、
approval grant、credential変更、削除、team import、computer/VM lifecycleは公開しない。
必要な未対応操作は別の認可adapterを実装するまでunsupportedのままにする。
source固定点の更新時はlicense/notice、認証、observer、MCP、computer、保存・復元、
upstream security差分を再確認し、固定点変更を自動採用にしない。
