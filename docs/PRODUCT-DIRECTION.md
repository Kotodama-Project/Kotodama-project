# Kotodamaで過ごす、考える、必要なら頼む

Kotodamaは一つの製品です。公開のKotodama-projectを、製品統合・説明・導入の最優先の中心にします。カジュアル利用は最小構成、組織機能は追加構成です。カジュアルな環境だけを改善して公開本体への統合を後回しにはしません。

## 選べる体験

雑談を楽しむだけでもよく、新しい実行依頼や追加の許可とみなして仕事や生産性へ誘導しません。一緒に考え、許可資料を使って新しい人やagentが目的・経緯・決定・未完へ追いつくこともできます。既存の目的・許可がある読取調査、知識整理、改善提案、ToDo確認、継続作業は、新しい命令を毎回待たずに進められます。元発話や推測を候補として整理することと、新しい仕事の実行権限は別です。新しい依頼も継続作業も現在の許可範囲に照合し、検証した成果を会話へ返します。catch-upや成果化は利用例であり強制ファネルではありません。

人とagentは同じSource、Context、Knowledge、permission、correction、resultを扱います。人向け説明は同じ根拠の読みやすい表示です。別々の真実や訂正履歴を増やしません。

人は承認や訂正をするだけでなく、いつでも新しい意図、条件、変数、視点、思いつきやインスピレーションを持ち込み、目標や進め方を変えられます。その新情報を既存の文脈・知識・仕事・人向け説明へ反映し、何が変わったかを辿れることが設計目標です。

## 始め方と参加

目指すsetupはgoalと資料を中心に進み、agentが既存環境を保ちながら最小設定を準備します。login、2FA、CAPTCHAなど本人しか行えない操作はhuman_requiredです。初回許可内の通常処理は自律的に進め、目的・判断材料・権限が不足するときは、その理由と具体的な選択肢を示します。

Markdownだけへ固定せず、各surfaceのnative componentsで選択肢、補足入力、進捗、成果、根拠を読みやすく示します。固定wizardやcomponentの詰め込み、工程ごとの再承認を増やしません。自由文・音声・button・select・modalによる訂正を同じ履歴へ戻すことが目標です。このUI全体はmainで完成した機能ではありません。

voice agentはまず静かに場と許可contextを理解し、役立つ場合はagentと分かる自己紹介で自発参加できる方向です。現行候補は呼びかけ中心で、自発参加は未実装・未受入です。聞く／話す／記録／仕事実行と、発話停止／会話終了／仕事取消を分けます。

専門agentは必要な役割への限定委任、統合、独立検証として使います。基盤modelの訓練や無制限増殖を意味しません。会話や資料を毎回丸ごと送り直すことを避け、許可された必要context、実token使用量、Live時間、再試行も受入で確認します。

分担するだけでなく、異なる観点を意図的に持たせ、反証・相互確認・統合を通じて注意や判断の偏りを補います。LLMが必要な整理・分類・仕事分解・役割構成・委任・統括を柔軟に判断できる土台を目指します。固定フローを過剰に作り込まず、将来モデルが進歩した際にもその能力を生かせる構成にします。これは設計目標であり、AGI化や人間を超える性能を保証するものではありません。実行は現在の権限と資源上限に従います。

## 任意の入口と情報

Discord、Slack、OS、webは任意adapterです。[Slack parity #70](https://github.com/Kotodama-Project/Kotodama-project/issues/70)でtext・資料・音声会議・Source・Context・permission・依頼・継続・訂正・停止・成果・通知・native UI・social-only・静音と必要時参加まで追跡します。provider固有の差はunsupportedまたはunknownとして示します。Issueの存在はSlack接続・機能同等性の証明ではありません。

顧客・組織・関係・活動も共通知識として扱う方向です。[Salesforce #77](https://github.com/Kotodama-Project/Kotodama-project/issues/77)は任意adapterで、現在は未接続・同期未実施、双方向同期も未確約です。object情報、agent整理、人向け表示で固定画面中心のCRMをどこまで代替できるかは設計仮説です。CRM不要・置換済みとは主張しません。

localとcloudの双方を認めます。Tailscaleはprivate接続の強い候補ですが、それだけで保存先、host、外部LLM処理、権限、保持、incident対応の安全性は証明できません。security受入までは実顧客情報、NDA対象、業務機密を入れず、合成データで検証します。個人local利用は別laneとし、privacy、viewer、processing scope、owner責任、stop、revocationを持たせます。setup/statusから保存場所・外部処理・閲覧scopeが分かる方向です。

## 実装と候補の現在地

2026-09-13に公開main `4abe890`と以下のopen PRを照合しました。mainはコードを含む状態、candidateは未統合、unconnectedは接続未確認、hypothesisは未実証の設計仮説です。CI成功を実利用成功へ読み替えません。

| 対象 | 状態 | 根拠と残件 |
|---|---|---|
| Company Pack作成と確認・訂正Gateway | main | [Task-bound実行](COMPANY-PACK-TASK-EXECUTION.md)、[Gateway](../runtime/local-review-gateway/README.md)。実ファイル／local HTTPの限定経路。自動Voice-to-Taskは未接続 |
| 知識訂正とexecutor入力binding | candidate | [#59](https://github.com/Kotodama-Project/Kotodama-project/pull/59)、head `b962196`。現在pin・入力digestの候補。Task owner接続は残件 |
| OKF適合と判断readyの分離 | candidate | [#61](https://github.com/Kotodama-Project/Kotodama-project/pull/61)、head `05c947a`。構造PASSは内容・権限・意思決定の証明ではない |
| 診断／Knowledge Work合流 | candidate | [#64](https://github.com/Kotodama-Project/Kotodama-project/pull/64)、head `e0460b3`。読取診断の候補。GUI、live observer、実Work接続は未受入 |
| 専門agent協調 | candidate | [#67](https://github.com/Kotodama-Project/Kotodama-project/pull/67)、head `6ac299f`。非candidate受入と拒否payload保存など修復待ち。全利用の必須構成にしない |
| room別Live／workspace | candidate | [#69](https://github.com/Kotodama-Project/Kotodama-project/pull/69)、head `b2fd317`。Source/Task/mediaの実接続は未受入 |
| 静音Liveと会話制御 | candidate | [#71](https://github.com/Kotodama-Project/Kotodama-project/pull/71)、head `b3fda59`。継続発話、退出と仕事の分離を#69と合流して検証する |
| Slack／Salesforce | unconnected | #70／#77。公開mainで接続済みとはしない |
| 自発参加／native UI統合 | goal | 個別候補があっても、同じ実会話での統合受入は未達 |
| object情報からCRM体験を構成 | hypothesis | 対象用途・権限・同期方向・人向け表示の実証が必要 |

各PRのチェック・レビューはheadに束縛された観測です。#67の既存CI成功でも修復待ちの指摘は残っています。他候補のレビューなしを承認済みと扱いません。[プロジェクト地図](PROJECT-MAP.md)と[現在の公開境界](../STATUS.md)から既存実装へ進めます。

## 説明と入口を保つ運用

READMEを一つの入口として、現在地と必要な根拠へ進める状態を保ちます。コード・資料・訂正が変わるたびに担当が説明・索引・入口も更新し、古さ・矛盾・欠落を見つけ、更新した表示を読み戻して確認する運用までが実装ToDoです。現在は静的な一覧と導線を作った段階で、自動更新や全体を継続して保つ運用は未完です。この文書は公開用の意図の表示であり、別のTask台帳は作りません。

## 最初の受入

同じ実会話で、次の経路をそれぞれ確認します。特定の友人グループは提案例であり、唯一のproof対象ではありません。

1. social-onlyなら新しいTaskへ誘導されず終われる。同時に、既存の目的・許可に基づく調査・整理・ToDo確認・継続作業は新しい命令待ちにならない。
2. 許可資料から出典付きcatch-upができる。
3. 新しい依頼と既存の継続作業を区別し、現在の目的・許可に合う限定workを実行して検証した結果を返す。雑談や推測候補から追加の実行権限を作らない。
4. 訂正と新しい意図・条件・視点を同じKnowledge／Task／agent context／人向け説明へ反映し、目標や進め方の変更を辿れる。
5. native UI／自由文／音声の訂正が同じ履歴へ戻る。

全部のadapter、CRM、組織を先に作りません。この受入は目標であり達成報告ではありません。公開previewは引き続きread-only/candidate-only、`NO_GO_UNPUBLISHED`です。
