# 68項目の受入チェックリスト

2026-09-06。**現在の作業を区切った後、全体を照合して必要な仕事を継続する。** 製品全体の完了、各Taskの全受入、mainへの統合、Public Betaの開始を宣言する資料ではない。

既存のR01–R68を維持して全件読解した。68はREADMEを重複排除してまとめた受入群で、細かな条件の総数や完成率ではない。各詳細に、正常系、拒否・復旧、根拠、未完、既存ownerへの再開経路を置く。

「ローカル検証済」「評価で実測済」は、その限定範囲の証拠を表す。全体受入のチェックは未宣言のまま残す。過去receiptには時刻とsourceを保ち、現在稼働の証明に読み替えない。

- [最新の運営方針](../OPERATING-POLICY-2026-09-06.md)
- [READMEとの対応・段階整理](../CLOSING-2026-09-06.md)
- [要件漏れと追加条件](GAPS.md)
- [根拠と読取範囲](EVIDENCE.md)
- [全Issue対応](ISSUES.md)
- [機械可読68項目](requirements.json)

## 利用体験別の入口

| 群 | 対象 | 主な再開先 |
|---|---|---|
| [C01 一般チャットと実仕事の往復](C01.md) | R01, R02, R14, R15, R37, R38, R39, R40, R44, R45, R46 | Proxmox / OS運用担当（private resolverで解決） |
| [C02 Voiceから保存・検索・返却](C02.md) | R03, R04, R08, R09, R10, R11, R12, R13, R56, R57, R61 | Voice実装・運用の担当（認可されたprivate Task resolverで解決） |
| [C03 同じTaskを各入口で扱う](C03.md) | R05, R16, R18, R20, R42, R54 | Task契約の既存ownerと各adapter担当（private resolverで解決） |
| [C04 原資料・情報アクセス・記憶](C04.md) | R06, R07, R19, R29, R30, R31, R32, R33, R34, R55, R58 | 情報アクセス・Context担当（private resolverで解決） |
| [C05 Proxmoxの再現可能な日常運用](C05.md) | R47, R48, R50, R51, R52, R53 | Proxmox / OS運用担当（private resolverで解決） |
| [C06 GitHub候補・README・移植の統合](C06.md) | R17, R21, R22, R23, R24, R25, R26, R27, R28, R35, R36, R41, R59, R60, R67, R68 | 公開統合の担当 / GitHub #24 #30 |
| [C07 Cloudflareの運用・費用・公開境界](C07.md) | R43, R49, R62, R63 | Cloudflare担当 / GitHub #2〜#16 |
| [C08 成果の利用・改善・事業化](C08.md) | R64, R65, R66 | 成果受入の既存owner（private resolverで解決） |

## 個別項目の索引

| 項目 | 現在の証拠段階 | 全体受入 |
|---|---|---|
| [R01 自然な相談から要件・実行・成果・学習を同じ仕事として完走する](C01.md#r01) | 未接続 | 未宣言 |
| [R02 目的・受益者・制約・受入・停止条件を仕事へ保持する](C01.md#r02) | 部分実装 | 未宣言 |
| [R03 Discord textから依頼を受け同じ場所へ結果を返す](C02.md#r03) | 実環境未確認 | 未宣言 |
| [R04 Discord Voiceの人の発話へ継続して応答する](C02.md#r04) | 実聴未確認 | 未宣言 |
| [R05 Codex・Claudeの会話を同じSource/Taskへ結ぶ](C03.md#r05) | 部分実装 | 未宣言 |
| [R06 Notion・GitHub・Drive・n8nからsource-bound入力を受ける](C04.md#r06) | 契約のみ | 未宣言 |
| [R07 Teams・Meet・Zoomの話者付き記録を取り込む](C04.md#r07) | 契約のみ | 未宣言 |
| [R08 参加者別の音声・発話・時刻・出典を対応させる](C02.md#r08) | 部分実装 | 未宣言 |
| [R09 自然な900秒境界で区切り次の区間を継続する](C02.md#r09) | 実環境未確認 | 未宣言 |
| [R10 退出・再参加後にlistenerとrotationが復旧する](C02.md#r10) | 部分実装 | 未宣言 |
| [R11 話者・時刻付きtranscriptをprivate channelへ返す](C02.md#r11) | 部分実装 | 未宣言 |
| [R12 発話根拠からIntent/ToDo/Goal/Verified Handoffへ進む](C02.md#r12) | 部分実装 | 未宣言 |
| [R13 rawと補正transcript・議事録を別々に保持する](C02.md#r13) | 部分実装 | 未宣言 |
| [R14 必要な不確実性だけ質問し十分なら先へ進む](C01.md#r14) | 部分実装 | 未宣言 |
| [R15 訂正・撤回・保留・unknownを旧提案より優先し保持する](C01.md#r15) | 部分実装 | 未宣言 |
| [R16 Kotodama関連の依頼をSource/Intent Candidateとして自動記録する](C03.md#r16) | 部分実装 | 未宣言 |
| [R17 Source→Intent→Decision→Work→Receipt→Promotionを追跡する](C06.md#r17) | ローカル検証済 | 未宣言 |
| [R18 append-only causal ledgerが訂正・権限・競合・replayを保持する](C03.md#r18) | 部分実装 | 未宣言 |
| [R19 OKFを根拠・revision付きの再生成可能な読取表現にする](C04.md#r19) | 部分実装 | 未宣言 |
| [R20 SQLite pilotでSTOP・期限・snapshot/restore・replay拒否を実行する](C03.md#r20) | 部分実装 | 未宣言 |
| [R21 Human Intentのvision/mission/outcome/constraintを保存する](C06.md#r21) | 部分実装 | 未宣言 |
| [R22 9 Blocksと9 Recordsを同じmanifest/flowで検証する](C06.md#r22) | ローカル検証済 | 未宣言 |
| [R23 3 MOCから通常業務・公開・復旧の同じ記録へ辿る](C06.md#r23) | ローカル検証済 | 未宣言 |
| [R24 starterを上書きせず複製し必要な値だけ設定する](C06.md#r24) | ローカル検証済 | 未宣言 |
| [R25 customization/validator/catalogで候補の不足を示す](C06.md#r25) | ローカル検証済 | 未宣言 |
| [R26 exact bytesのReview Bundleを作り照合する](C06.md#r26) | ローカル検証済 | 未宣言 |
| [R27 Review Request/Response/Decision Handoffを通して再検証する](C06.md#r27) | ローカル検証済 | 未宣言 |
| [R28 会社候補をTask/Work Orderへ結び実生成・検証する](C06.md#r28) | ローカル検証済 | 未宣言 |
| [R29 People/Goals/ToDos/files/conversationを許可範囲で横断する](C04.md#r29) | 部分実装 | 未宣言 |
| [R30 identity/purpose/grant/revocationを検索前に検査する](C04.md#r30) | 部分実装 | 未宣言 |
| [R31 引用をsource/revision/byte range/digestへ遡れる](C04.md#r31) | 部分実装 | 未宣言 |
| [R32 metadata/lexical/optional encoderでSessionを再利用候補にする](C04.md#r32) | 部分実装 | 未宣言 |
| [R33 変更・撤回・削除したsourceを引用し続けない](C04.md#r33) | 部分実装 | 未宣言 |
| [R34 TiDBのstructured/vector/hybrid queryを評価する](C04.md#r34) | 実環境未確認 | 未宣言 |
| [R35 目的・境界・personaを持つResident Cloneを作る](C06.md#r35) | 契約のみ | 未宣言 |
| [R36 仕事に必要な専門role/skillを選ぶ](C06.md#r36) | 部分実装 | 未宣言 |
| [R37 Task/Plan/Requirement/Invocation/Contextを同じ仕事へ束縛する](C01.md#r37) | 部分実装 | 未宣言 |
| [R38 Completion Ownerが受入まで再計画し重複writerを拒否する](C01.md#r38) | 部分実装 | 未宣言 |
| [R39 self-owned環境で限定された実作業を実行する](C01.md#r39) | ローカル検証済 | 未宣言 |
| [R40 選択されたモデルとInvocationのprovenanceを残して実行する](C01.md#r40) | 部分実装 | 未宣言 |
| [R41 local ASR/encoder等を補助に使い勝手なモデルfallbackをしない](C06.md#r41) | 部分実装 | 未宣言 |
| [R42 AI-only/human-auditedを同じ記録と異なるpromotion policyで扱う](C03.md#r42) | 部分実装 | 未宣言 |
| [R43 Access付きEdgeから許可されたGatewayへ到達する](C07.md#r43) | 部分実装 | 未宣言 |
| [R44 同じhandoffを識別して訂正・再読する](C01.md#r44) | ローカル検証済 | 未宣言 |
| [R45 OSのGadget/BlueprintからKotodamaの仕事を扱う](C01.md#r45) | 部分実装 | 未宣言 |
| [R46 Gatekeeperの権限・操作履歴をCompany証拠へ結ぶ](C01.md#r46) | 部分実装 | 未宣言 |
| [R47 固定upstream/lockでOS一式を起動・再起動する](C05.md#r47) | 実環境検証済（評価） | 未宣言 |
| [R48 source/dependency/security overlayを再現して検証する](C05.md#r48) | 部分実装 | 未宣言 |
| [R49 Workersの料金・quota・telemetryを制限し運用する](C07.md#r49) | 要判断 | 未宣言 |
| [R50 ProxmoxでCloudflare OSを含め自己ホストできる](C05.md#r50) | 部分実装 | 未宣言 |
| [R51 Compose/Proxmox profileを検証する](C05.md#r51) | ローカル検証済 | 未宣言 |
| [R52 実install/migration/restart/rollback/restoreが再現できる](C05.md#r52) | 部分実装 | 未宣言 |
| [R53 Proxmox保護compute/dataと交換可能なedgeを分離する](C05.md#r53) | 部分実装 | 未宣言 |
| [R54 一つのactive home/writerでTaskを再開する](C03.md#r54) | 部分実装 | 未宣言 |
| [R55 source/derivedを暗号化packageで保存・restoreする](C04.md#r55) | 部分実装 | 未宣言 |
| [R56 capture/transcribe/transfer/reuseを目的別に同意管理する](C02.md#r56) | 部分実装 | 未宣言 |
| [R57 音声/文字起こし/derivedの保持期限と削除を実行する](C02.md#r57) | 部分実装 | 未宣言 |
| [R58 capabilityをidentity/resource/action/time/stopへ限定する](C04.md#r58) | 部分実装 | 未宣言 |
| [R59 機微情報とprivate sourceを公開しない](C06.md#r59) | ローカル検証済 | 未宣言 |
| [R60 attestation/nonce/checkpointの束縛を検証する](C06.md#r60) | 部分実装 | 未宣言 |
| [R61 distinct real peopleを含むVoice受入を通す](C02.md#r61) | 実聴未確認 | 未宣言 |
| [R62 protected reconciliationと独立した採否を揃える](C07.md#r62) | 実環境未確認 | 未宣言 |
| [R63 candidate-bound GO後に限定Public Beta accessを開く](C07.md#r63) | 未提供 | 未宣言 |
| [R64 idea→市場検証→offer→build→distribution→fulfillmentを回す](C08.md#r64) | 構想段階 | 未宣言 |
| [R65 契約・入金・margin・継続利益を証拠で管理する](C08.md#r65) | 構想段階 | 未宣言 |
| [R66 成果とfeedbackからagent/skillを版管理して改善する](C08.md#r66) | 部分実装 | 未宣言 |
| [R67 初参加agentが正本・実装・PR・次の一手に辿れる](C06.md#r67) | ローカル検証済 | 未宣言 |
| [R68 BecomeOneを選択移植し第二Product SSOTを作らない](C06.md#r68) | 部分実装 | 未宣言 |

## 再開するagentへ

最初にREADME → この索引 → 対象詳細 → Evidence/Issueを読む。Taskの状態は既存record/eventsへ解決する。ここにあるownerは経路であって、現在のleaseを保証しない。次の作業を選ぶ際にGitHub head/base/checks、実Task revision/owner、必要なruntimeと権限を確認し、対象一件のWork Orderへ固定する。古いPID、期限切れgrant、過去のレビュー承認を再利用しない。
