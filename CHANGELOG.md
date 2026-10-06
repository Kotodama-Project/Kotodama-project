# Changelog

公開リポジトリの利用者向けの変更履歴です。形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は [Semantic Versioning](https://semver.org/lang/ja/) に従います。`-preview` の付く版は Incomplete Public Preview で、公開面の既定は `NO_GO_UNPUBLISHED` のままです。tag を push すると `.github/workflows/release.yml` が smoke report と source archive を作り、provenance attestation を付けて draft release を作ります。

This is the user-facing change log of the public repository (Keep a Changelog, Semantic Versioning). Versions with a `-preview` suffix are an Incomplete Public Preview.

## [Unreleased]

### Added

- offline agent診断のhardening試験、Linux/Windowsの限定CI、公開skillを追加。skill・実装・統合契約を同じcontent digestに束縛し、各検査のfailure・skipを隠さず報告する（#136後半）。

- Knowledge Work compilerを統一context v2へ接続。必須の主張・受入条件・成果物を落とさず、上限や分類・出典変更の拒否でWork情報を除去する。分離していたcompilerの回帰assertionと、実入力へ訂正を流す合成経路を復元（#137後半）。
- agentの状態をオフラインで投影するCLIを再配置。現在の責任索引に対応し、JSON・Markdownとも既定で名前・目的・Work/runを伏せる。未認証の観測、停止要求、実行終了を認可や独立検証へ格上げしない（#136前半）。

- 知識contextを同じ16欄のv2 envelopeへ統一し、KB producerとNode consumerを更新。内部digest、falseの権限claims、Work受入・成果物欄を定義し、旧版を自動変換せず拒否する。compilerは#137の後続。
- control-plane監査のfindingを現行Conceptと論理roleに束縛した修正候補へ変換するplanner、運用文書、関係pathだけを検査する任意CIを追加。Issue作成・Task実行・agent起動を行わない（#134）。
- Discordの会話候補を処理するInteraction Policyを共通関数へ抽出。現在のadmissionを維持し、不明話者・非明示依頼・雑談を実行権限にしない。確認の送信と記録は後続（#145前半）。

- 現行KBのcontextを、準備・session開始・完了の同じUTF-8 stdin digestへ束縛する限定adapterを再配置。未来時刻・撤回・不正shape・予算超過を拒否し、実子プロセスへの入力と訂正後の旧pin拒否を検査する（#130のruntime部分、元#59）。
- 公開ファイル分類と7役割の責任索引を既存知識へ接続した。98%分類gateを維持し、旧OKFの別定義と稼働宣言を持ち込まず、元のreview日付に基づく鮮度警告を保持する（#134）。
- Discordの既存4actionを固定のcapability laneへ対応付け、設定・analyzer・コマンドの語彙を一つにした。既定grantを維持し、編集の確認待ち・実際の読取境界・外部操作を表現しない条件を文書化（#146後半）。

- control-planeの監査道具と3 schemasを現行知識基盤へ向け直した。競合OKFを除去し、98%分類・未知Concept・有限読取り・責任索引からの稼働宣言拒否を検証する。台帳の接続は後続（#134）。
- 知識のlocal source pinを実際のcaptured bytesへ束縛し、古い非critical Conceptもcontextへ戻さないようにした。重要な文脈を先に確保し、現在の出典へ戻る再開手順を追加。古いGitHub観測のsnapshotは持ち込まない（#130の知識部分、元#59）。
- Codex brief bridgeの既存invocation journalへ、観測したsession開始を保存する。失敗・中断・再起動後も同じgrantで読み戻し、再送で二度目の実行を始めない。v1の元bytesをbackupに保持し、Task接続や再開可能なsessionとは区別する（#126、元#47）。

- 元#46のlocal model proxy、native Proxmox template、固定公式OSへの2patchをコード・契約だけ再配置。モデル予算・receipt保全、seal、archive integrityを検査し、旧snapshotや運用方針は再導入しない（#125）。

- 要件Gadgetと限定Codex brief bridgeを元#45から再配置。現在のcatalog v2を使い、保存済みinvocationの読取中の差替え・肥大化・消失を拒否する。権限・再送・取消を合成HTTPで検査し、native core／実モデルの受入とは分ける（#124）。

- Knowledge Workの監査CLIと明示source-rootの回帰試験を追加。原資料を複製せずに各成果のbytesを検証し、最大64package・4096entryで探索を止める。既存validatorを保持し、未統合compilerのassertionは#137へ追跡する（#133 R3b）。
- Cloudflare OSの任意の管理構成について、知識・会話・Task・agentの正本、読取adapter、訂正先、revision・grant境界と未接続部分を既存の設計契約へ明記。Dots-firstと単一Task ownerを保ち、native画面やprovider接続の完成とは区別する（#139）。
- Luna Task swarmの過去版`7df1aea`で実施済みのlive fixture受入記録（4 model calls、7 messages/ACK、4 accepted）を文書へ反映。#159の公開実施記録に基づくLOCAL_PASSで、現在版のlive受入へ流用しない。未統合の文書候補`2d1e099`を現行説明へ再配置し、再実行はしない（#159）。
- Git Stewardの業務演習を追加。69合成シナリオ、13回帰試験と実Git/SQLite/子プロセスによる訂正・再開を既存launcherと両OSのpath限定CIで検査する。現行の調整コアは維持し、実providerや新しいTask台帳は作らない（#132、元#58）。

- OpenMaus / Cloudflare OS の設計契約とread-only検証を追加。必要なagent表示項目・MCP能力境界・知識bundle参照を検査する契約候補で、UI・provider資源・実runtimeの有効化は含まない（元#56）。

- 正本 #48 の公開知識基盤と #61 の互換 verdict/readiness 修正を現行 main へ再配置。9つの公開Concept、出典に束縛した catalog/graph、字句検索と限定context、schema/profile/判断readinessを分ける監査を追加。除外した旧運用文書やCloudflare baseを取り込まず、内容・実agent入力・権限の独立検証を未成立のまま明示する（`docs/KNOWLEDGE-BASE.md`）。
- Discord runtimeに`integrity`を追加し、信頼済みの直接CLI起動でapplication import前後のsourceとmetadataを検査し、認証済みlocal controlで候補・現在のdiskと照合する。cached/direct API・preload起動とWindowsではsource証明を未成立とし、起動中変更・大きなsource集合を一致にせず制御応答の上限を守る。live切替・rollbackと`PB-G4`は未証明のまま（#157、元#182）。

- 複数の人・AI の作業範囲、lease/epoch、独立review、SQLite journal を扱う Git Steward の調整コア候補を、公開済み #179 の R1 から現行 main へ再配置。46 synthetic Node tests と Python launcher を含み、Linux の Repository checks は Node 24 を明示的に用意する。関連pathのPR・main pushでは、任意workflowがWindows/LinuxのNode試験だけを実行する。Git observerはpartial/promisor repositoryを拒否し、欠けたobjectを自動取得しない。非SHA-1 repositoryもrevision解決前に拒否する。Git・GitHub・provider への書込みや配備を行わず、設計文書・業務演習は #132 の後続（`runtime/git-steward/README.md`）。
- Local review gateway に分類・明示reader/reviewer・期限・取消のcatalog v2を追加。unclassified/secretの内容を返さず、人のreviewはhuman種別だけに保存する。kindとpolicyはoperatorのsnapshotであり、本人認証・Promotionではない（#123、元#44）。

- Dots pluginにcursor一覧とrevision/権限付き全文pageを追加。簡略一覧は合成SDK試験で転送JSONを約97.6%削減し、元の全文一覧を維持する。長文・多言語・複雑な依存の通信benchmarkを必須CIで検査する（#204）。

### Fixed

- mainのpushで検証runが作られなかった場合に、同じRepository validationを手動起動できる入口を追加。必須チェック・全検査・read-only権限を維持し、対象head SHAと結果の読戻しを文書化。

- Discordの複合依頼を現行grantで全件検査し、全Taskの再認可が完了するまで実行・受付通知を始めない。失敗したqueued revisionを比較付きで取消し、不明な後始末は新しい受付を止める（#146前半）。

- 要件Gadgetの再確認・変更要求より古い応答が新しい状態を上書きする問題を修正。未確定の候補を表示せず、短い画面でも長文を折り返す。Chromiumの304バリエーションと12職務のlocalhost journeyを、hash固定の専用環境で検査する（#127、元#66）。
- Windowsでintegration contractの正規Pathを誤拒否する不具合と、OSごとのPath並び順により知識のsource digestが変わる不具合を修正。文字列の危険な区切りは引き続き拒否する。検証fixtureのSQLite接続を明示的に閉じ、Git index入力のLFと子プロセスのUTF-8 decodeをOS共通にして既存の拒否・終了確認を保持する。
- Remote ownerのtimeout回帰試験を実HTTPの受信観測へ同期させ、遅いrunnerで受信前に80msが経過する誤失敗を修正。実timerによる期限と、書込結果不明・再送禁止・未終了処理の枠保持の確認は維持する。

- OKF v0.2の固定した公式仕様を参照し、日時のguidanceを最小conformanceと分離。判断readinessは明示した時刻・Taskへ束縛し、source・検証・鮮度・矛盾・access・attestation・必須contextを個別に報告する。未指定・未解決を準備完了にせず、Conceptの日時や履歴を書き換えない（#51）。

- 移行元の誤コピー検査をbatch外の追跡ファイルへ広げ、HEAD・index・working treeに残る元blobと非公開元pathを内容を出さずに検出する（#161）。

- Session/conversation ledgerの不正なenum・role型で例外終了せず、既存の理由コードと順序を保持した構造化拒否を返す。レコードshapeを1回の検証内で再利用し、明示bindingはOBSERVEDに限定する。peer message schemaは実send/receiveの`payload_state`を閉じたenumで受理する（[#221](https://github.com/Kotodama-Project/Kotodama-project/issues/221)）。
- Python個別監査の後続として、保存済みCompose候補の有限な通常file読取りと不正profile IDのreport抑制を追加。checkpoint署名、NONE decisionの個別ref、依存失敗後の独立pending jobのoracleを補強する（[#219](https://github.com/Kotodama-Project/Kotodama-project/issues/219)）。
- 公開候補validatorで深いJSON・不正な型・非有限数・上限超過を定型の拒否結果に統一。A022、protected handoff、executorの診断へ入力本文を反映せず、handoffは有限の通常ファイル読取りと確実なクローズを検査する。
- 履歴増加時のSQLite context、訂正、累積予算、Task swarm検索を索引化。原文と過去版を保持し、初回backfillと全件exportの制約を明記する（#205）。
- 遅いHTTP/ASR/通知の実未完了処理を有限化し、停止時は受付を止めて保存の所有権を確認する。不確実な書込みは再送せず、不確実な停止は同じプロセスで再試行する（#206）。
- 制御サーバーの待受に失敗した起動はSQLiteとhost lockを閉じ、同じ設定で再起動できるようにする。HTTPとDiscordのTask一覧は要求者とTaskのactorを照合し、現在の閲覧権限を確認する（#206）。
- 設定を読めない間のDiscord runtimeの`policy_unavailable`を障害開始時の一回に抑え、復旧時に`policy_restored`を記録する。毎秒の再確認と、読めない間の操作者・音声参加者の拒否は維持する。
- exact requirementを持つHTTP依存を同時更新し、生成hashと両lockの整合性を検査する。Dependabotでも同じgroupへまとめる（#207）。
- Uvicorn 0.54、csv-parse 7.0.3、ws 8.22を生成lockへ反映し、既存の設定と動作を検査する。実験的HTTP/2は有効にしない（#210、#211の更新を#209へ集約）。

### Changed

- MITの権利者決定、受入済みA017/A019/A022の出典・保持notice、draft releaseのSBOM検証記録をライセンス範囲の文書へ反映。未移植部分や将来の依存配布を一括で許可する説明にはせず、古い未決表示を解消する（#25）。

- 固定したPython監査の202改善候補を全件対応。154件の追加実装と48件の既存実装確認を独立レビューし、元の指摘・検証・負の対照・source hashを[個別対応表](docs/PYTHON-TEST-IMPROVEMENTS.json)へ束縛する。文書・CLI・schema・候補IO・通信計測のoracleを補強し、Task swarm依存導入前のtracked credential gateを追加（[#221](https://github.com/Kotodama-Project/Kotodama-project/issues/221)、[レビュー](docs/PYTHON-TEST-REVIEW.md)）。
- Python検査の全1,193 casesと3委譲表示を個別レビューし、運用手順・リンク・拒否時出力・UTF-8・実Git ignoreのoracleを改善。既存mutationと実CLI境界を保ってlifecycle/ledger/scannerの重複コストとpytest collectionを減らした（[#212](https://github.com/Kotodama-Project/Kotodama-project/issues/212)、[レビュー](docs/PYTHON-TEST-REVIEW.md)）。
- Discord CIを一つのLinux/Windows matrixへ統合し、全テスト・Docker probe・必須check名と失敗時の拒否を保持する。製品の理想との照合と、履歴を失わないbranch/parked候補の整理を改善ループに追加する。

## [0.2.0-preview] - 2026-10-04

Incomplete Public Preview の source release 候補です。Public Beta の受付、Discord 招待、公開 Voice Bot、live deployment、Final Human GO は含みません。

### Added

- Public agent lifecycle の公開契約を #36 の固定 source から再導入。Luna との概念対応と deep JSON の構造化 refusal を追加。実 registry・runtime・continuity は未検証。

- エージェントへの作業依頼用 Issue form を追加。目的、現状、担当、手順、確認コマンド、受入条件、操作範囲・停止条件を必須にし、作業ガイドと委任インデックスへ案内する（#163）。
- Release 候補に 3 つの依存 lock の CycloneDX 1.6 SBOM を追加。入力 digest、distribution hash、SHA256SUMS、build provenance、draft 添付を結び、未固定依存と成果物の上書きを拒否する。実 release での署名・添付の受入は残件（#166）。

- 作成済みOpenAI Dotを日常の入口とする方針と、Discord / Luma用のlocal plugin候補。指定operator/channelの受付、訂正・削除・取消、重複返答の抑止、Luma作成／更新候補の全文確認、一回の操作claimとDot報告を追加。Dots製品・live Bot・Luma websiteの受入、remote MCP Eventsは別途確認する。

- Discord の実音声受入の手順・記録様式と、既存 SQLite イベントを本文なしで集計する読み取り専用 CLI を追加（[#154](https://github.com/Kotodama-Project/Kotodama-project/issues/154)）。入力・ASR の観測と実聴を区別し、欠測・不正入力・上限超過を明示する。runtime の既定設定や受入結果は変更せず、実音声の受入は未実施。
- A019 の registry 契約候補（task contract、task decomposition、worker capability catalog、worker result）を、[公開 PR #115](https://github.com/Kotodama-Project/Kotodama-project/pull/115) の固定 head `040a9becf0463e69887f126e30af6d38bdc02988` から再配置。出典表と非公開の元履歴走査 receipt は公開元の歴史的記録として維持し、この候補の独立 review は別 gate で検証する。4 schemas は candidate-only で、runtime や Task owner の統合ではない。追加 review により validator と試験を補強し、manifest・出典表の全階層と著者・履歴件数を固定する（独立 review の許可済み状態のみ別判定）。重複 JSON key、通常・escaped 表記の利用者絶対 path を拒否し、サイズ上限と symlink・reparse point の拒否を読取り前に検査する。
- BecomeOne の A022 アーキテクチャ候補を再構成: 単一の記録 owner、複数 agent の協調、tool の監督、plan lifecycle の公開契約と、出典表・固定 bytes の validator。公開済み PR #114 の候補を現行 main に合わせ、今回の公開候補への独立 review を履歴証拠と分けて記録（`docs/architecture/README.md`）。

- Knowledge Work の package（一つの作業成果と根拠のファイルを SHA-256 で固定する）と検証 report の schema、読み取り専用の validator、下書きを作る initializer、合成の例と否定の試験を、[#58](https://github.com/Kotodama-Project/Kotodama-project/pull/58)・[#60](https://github.com/Kotodama-Project/Kotodama-project/pull/60) から main に当て直した（[#133](https://github.com/Kotodama-Project/Kotodama-project/issues/133)）。PASS は構造の検査だけで、承認・実行の許可・Promotion は作らない。実行器へ渡す文脈の compiler は含めない（[#137](https://github.com/Kotodama-Project/Kotodama-project/issues/137)）。
- Luna Task swarm を main に統合（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)。元は [#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67) と修復 [#85](https://github.com/Kotodama-Project/Kotodama-project/pull/85)）: owner に束縛した計画、予算（試行・同時実行・検証枠）、ACK 付きの agent 間通信、独立した検証者。offline fixture はモデルを呼ばずに動き、実 Codex / Luna の live 受入は未実施（`docs/LUNA-TASK-SWARM.md`）。
- このリポジトリの自動改善ループの運用契約（`docs/IMPROVEMENT-LOOP.md`）: 一周に一件、独立 review と必須 CI を通して merge し、main が赤くなれば revert する。agent がしないことと人が決めることを明記（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)）。
- 意図を抜き出して、すぐに走る: `discord.agentChannelIds` のテキストチャンネルでは、操作者の発言をBotへのメンションと同じに扱い、明確で実行に足りる依頼をすぐに仕事にする。会話（テキスト・音声）から仕事が走り始めると、依頼者へ即座にDMで件名と仕事のIDを届ける（[#101](https://github.com/Kotodama-Project/Kotodama-project/pull/101)）。
- 公開の Agent Skills（intent、plan、research、delegate、validate、implement、public review、surface audit、handoff の 9 件）と共通の運用契約 `docs/SKILL-OPERATING-CONTRACT.md`、読み取り専用の監査 `tools/audit_public_skills.py`。既存の `kotodama-luna-swarm` も同じ契約の形式にそろえた（[#17](https://github.com/Kotodama-Project/Kotodama-project/pull/17)）。
- OpenManus を Proxmox 上の限定 executor として評価するための候補: schema、例、読み取り専用の validator（必須の権限 binding と出力、文字列への秘密の混入、不正 UTF-8、空白だけの値を拒否）と試験。配備や採用は含まない（[#55](https://github.com/Kotodama-Project/Kotodama-project/pull/55)）。
- agent swarm と route binding の契約候補: schema、読み取り専用の preflight、否定の試験。main の Luna Task swarm との対応表を付けた（[#34](https://github.com/Kotodama-Project/Kotodama-project/pull/34)）。
- 公開移行台帳の契約（schema、読み取り専用の verifier、否定を含む試験、合成 fixture）を [#35](https://github.com/Kotodama-Project/Kotodama-project/pull/35) から main に合わせて取り込み。移行対象ごとの最終的な分類と移し方を別の項目に分け、hash chain と任意の trusted head anchor で改竄を検知する。台帳ファイルは private receipt の digest が確定するまで作らない。Luna Task swarm の実行記録とは別の記録であることを注記した（`docs/PUBLIC-MIGRATION-LEDGER.md`）。
- BecomeOne から移植した階層テンプレート（A017: project / phase / requirement / plan / task と session context）。移植元の固定 commit・作者の GitHub handle・ライセンスを載せた出典表（`migration/a017-hierarchy-templates.provenance.json`）と、Issue #25 の owner 判断・非公開の元履歴走査 receipt・独立 review による受入の記録を付けた（[#27](https://github.com/Kotodama-Project/Kotodama-project/pull/27) を main に合わせて取り込み）。
- GPT-Live の採用方針（`docs/GPT-LIVE-ADOPTION.md`）: [#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71) の方針文書だけを日本語で書き直し、main の Node runtime（`runtime/discord-template`）の現状に合わせて取り込んだ。#71・#69 の別 runtime は取り込まず、Node に無い考え方は #142〜#146 で扱う。candidate-only で、実 VC の受入ではない。

### Changed

- 公式 Cloudflare OS を知識・会話・Task・agent の共通フロントとする設計を明記。操作は既存の各 governed owner へ返し、BecomeOne は移植元から公開版に固定した consumer へ移る。画面構成・接続・provider 配備は未確定で、第二の正本や新たな実行権限は作らない。
- Cloudflare の文書を実装と記録に合わせた: 採用文書に edge Worker の Access 必須の経路と Context Gateway 経由の Voice review を書き、深刻度 High の advisory の是正をローカルで済んだ部分と残る独立 review・provider 側の是正に書き分け、[validator 一覧](docs/SCHEMA-VALIDATOR-MATRIX.md) に Cloudflare の検査 3 件を足した（[#165](https://github.com/Kotodama-Project/Kotodama-project/issues/165)）。記録の JSON とコードは変えず、`NO_GO_UNPUBLISHED` のまま。

- Discord runtime のレビュー指摘への対応を統合（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)。元は [#84](https://github.com/Kotodama-Project/Kotodama-project/pull/84)）: 会話解析の同時実行・待ち行列・日次/累計の上限、書込み Task の検証を Linux の固定 Docker image で隔離、成果ファイルの読込みを開いたファイルと名前の両方に束縛、再起動時は queued を paused・running を uncertain として保持（自動再実行しない）、必須 CI が Discord の Linux / Windows 試験を要求。`write_file` / `develop` には Linux・`worker.verify`・`worker.verification` の設定が必要になった（`runtime/discord-template/README.md`）。
- `/kotodama tasks` が一時停止中（paused）と状態確認中（uncertain）を日本語で表示し、`/kotodama ask` は解析を後回しにした場合にそう伝える（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)）。
- 必須チェック `Trusted repository validation` が Task swarm の Linux / Windows 試験も要求する。swarm の依存は共通 lock と分けた hash 付きの `requirements-task-swarm-ci.txt` から入れる（[#100](https://github.com/Kotodama-Project/Kotodama-project/pull/100)）。
- 公開面の識別子検査が、日本語に隣接して書かれた private host の番号も拾うようにした。残っていた 2 箇所を中立化し、`docs/REPOSITORIES.md` は公開リポジトリだけにした（[#108](https://github.com/Kotodama-Project/Kotodama-project/pull/108)）。
- README・STATUS・ROADMAP・CI などの文書を #99〜#102 後の main に合わせた。Task swarm を main 側へ移し、必須チェック 4 本、エージェント用チャンネル、知識基盤は #48 系・音声は Node runtime という owner 判断（2026-09-24）を反映した（[#112](https://github.com/Kotodama-Project/Kotodama-project/pull/112)）。

### Fixed

- Discordテンプレートの`doctor`を改善: pnpmの固定版とffmpeg、Linux専用の書込みworkerの前提を確認し、不足する項目と次の手順を日本語で表示。道具の確認に待ち時間・出力上限を設け、macOSをLinux用workerの対応OSと表示しない。`--json`は従来の項目を保持する（[#155](https://github.com/Kotodama-Project/Kotodama-project/issues/155)の導入準備）。
- Luna Task swarm の peer MCP server が POSIX の仮想環境の symlink を辿って環境外の Python を選ぶ不具合を修正。既存の interpreter 選択順を保持し、不正な指定は Codex の起動前に拒否する（[#184](https://github.com/Kotodama-Project/Kotodama-project/issues/184)）。
- A017・A022 の移植 validator で、manifest・出典表の固定内容と履歴 receipt digest を照合し、重複 JSON 項目・非有限数・通常のエスケープを含む Windows 個人 path を拒否。親を含む symlink・reparse point の拒否と上限付き読取りを統一。A017 の集計は検査済み bytes を使い、上限なしの再読取りを除いた（[#172](https://github.com/Kotodama-Project/Kotodama-project/issues/172)）。公開本文・出典表・過去の受入記録は変更せず、この validator 修正の review は別に行う。
- Cloudflare edge の preview upload は、退役した作業 branch ではなく現在の `main` の先頭 commit だけを受け付ける（手動起動・Environment 承認は従来どおり）。候補検証 workflow は `main` への push でも走る。Cloudflare の説明文から古い「draft」表記を直した。
- 別のサーバーや別の Voice channel での入退室・ミュート切替で、Bot の返答が止まっていた（[#91](https://github.com/Kotodama-Project/Kotodama-project/issues/91)）。
- 実行中 Task の毎秒の権限確認が Discord REST を大量に消費し、一時的な API エラーで Task を失敗させていた。確認をチャンネル単位にまとめて 3 秒だけ再利用し、確認不能は 5 秒・3 回まで猶予する（[#92](https://github.com/Kotodama-Project/Kotodama-project/issues/92)）。
- 想定外のエラーが `OPERATION_FAILED` だけになり原因を追えなかった。`--verbose` または `KOTODAMA_DEBUG=1` で、秘密値を伏せた詳細を `debug.log` に記録する（[#93](https://github.com/Kotodama-Project/Kotodama-project/issues/93)）。
- CodeQL の指摘 2 件（成果ファイル読込みの確認と使用の間の競合、検証テストのコード組立て）（[#99](https://github.com/Kotodama-Project/Kotodama-project/pull/99)）。
- Task swarm が Windows で失敗していた（ディレクトリ一覧の link 数を信用して既存 payload を拒否、SQLite 接続の閉じ忘れ）。
- Windows の CI で Chocolatey の配布元が一時的に 406 を返すと、ffmpeg が入らないまま導入の step が成功扱いになり、後の音声の試験が失敗していた。導入を 3 回まで試し、それでも無ければ導入の step で止める。
- Discord の音声会話で、一度返答した後の続きの質問に答えなくなる経路を直した。Live の命令が 1 件拒否されただけでは会話を閉じず、最後まで再生した返答のたびに停止の指示を Live へ送らず、Live の文字起こしでも会話の続きであることを返答の判断に渡す。原因を絞るため、本文・音声・Discord の ID を含まない診断記録を足した（`runtime/discord-template/docs/OPERATIONS.md`）。実マイクでの連続応答は未確認（[#147](https://github.com/Kotodama-Project/Kotodama-project/issues/147)）。

### Not included

- Voice の実マイク E2E、2 人 30 分の会話、別設定での再現。
- 実 Codex / Luna の受入、agent lifecycle の実 registry / identity / continuity。
- OKF 知識基盤と各 adapter の実接続、live Compose / Proxmox / Cloudflare deployment。
- Public Beta、招待、公開 Voice Bot、Final Human GO。

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
- release workflow（`.github/workflows/release.yml`）: tag push で smoke report と source archive を作り、provenance attestation を付けて draft release を作る（[#97](https://github.com/Kotodama-Project/Kotodama-project/pull/97)）。

### Changed

- 製品方向の補足（2026-09-13 / 14）: Company OS、Evidence Chain、Cloudflare edge と公式 Cloudflare OS 基盤を徹底して作りながら、Voice channel では「楽しく過ごす / 一緒に考える / 必要なときだけ仕事を進める」のモードを選べる。「OK」の後は agent swarm が許可範囲で自律的に進める体験を最重要とする（`docs/PRODUCT-DIRECTION.md`）。
- private な runtime 識別子を公開 template の文書・コメント・テストから除去（[#90](https://github.com/Kotodama-Project/Kotodama-project/pull/90)）。
- action の pin 検査を「action 名 + 40 桁 SHA + version コメント」に変え、正当な Dependabot の更新で必須 CI が壊れないようにした。`actions/checkout` を v7.0.1 に更新（[#82](https://github.com/Kotodama-Project/Kotodama-project/pull/82)。この版の tag の commit）。

### Not included

- Voice の実マイク E2E、2 人 30 分の会話、別設定での再現（`runtime/discord-template/docs/ACCEPTANCE.md`）。
- agent swarm、OKF control plane、Slack / Teams / Salesforce adapter（open PR と Issue の候補のみ）。
- live Compose / Proxmox / Cloudflare deployment、Public Beta、Final Human GO。

[Unreleased]: https://github.com/Kotodama-Project/Kotodama-project/compare/v0.2.0-preview...HEAD
[0.2.0-preview]: https://github.com/Kotodama-Project/Kotodama-project/releases/tag/v0.2.0-preview
[0.1.0-preview]: https://github.com/Kotodama-Project/Kotodama-project/releases/tag/v0.1.0-preview
