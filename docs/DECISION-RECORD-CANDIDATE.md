# Company Pack Decision Record Candidate Contract

R28のreview handoffを、既存のgeneric Decision Recordへ進める前に必要なfieldと否定claimを固定する**schema-only**契約です。これはDecision builderでもverifierでもなく、Human Decision、approval、identity、authority、Promotion、Current Truth、runtime、Final Human GO、Public Beta GOを作成・検証しません。

## Ideal use

1. protected/content-addressed storeがexact Intent Candidate、R28 handoff、handoff verification、5件のevidenceをimmutableに保持する。
2. trusted identity/authority systemがreviewerとdecision makerの本人性、role、scope、expiry、必要なindependenceを検証する。
3. trusted clockとretention authorityがreviewed/decided/proposed-effective/expiry、retention policyを検証する。
4. authorized Humanが46件の個別outcomeとは別に、全体の`accept` / `request_changes` / `reject`を明示する。
5. 実Decision instance verifierが全source bytes、signature、authority、時刻、scope、5件の未解決evidenceを再検証する。
6. 別のprocessがexact approved DecisionをWork Order candidateへ束縛し、さらに別authorityが実行とPromotionを判断する。

## Current implementation

現在公開しているのは[`company-pack-decision-record-candidate.schema.json`](../schemas/company-pack-decision-record-candidate.schema.json)だけです。手入力candidateの形を閉じますが、source fileを読みません。builder、verifier、署名、identity provider、trusted clock、protected store、real Intent Candidate instance schemaはありません。test suiteはtest-onlyの`jsonschema[format-nongpl]` Draft 2020-12 validatorとformat checkerでvalid/invalid instanceを実検証しますが、schema consumerもdate-time format assertionを有効にする必要があります。

したがってschema validationが成功しても、次はすべて`NOT_VERIFIED`です。

- Intent Candidateの意味・schema・Human Intentとの一致
- R28 handoff/verificationの現在性・真正性
- reviewer/decision makerの本人性、role、authority、independence
- Human outcome entryの本人性と同意
- reviewed/decided/entered/proposed-effective/expiry時刻
- 5件のevidence referenceの真正性・十分性・解決状態
- retention enforcement
- Decision、Work Order authority、Promotion、Current Truth、GO

## Two candidate states

### `HUMAN_DECISION_REQUIRED`

exact source locator/hash/sizeを記録するための候補状態です。`human_outcome`、person evidence、scope、reason、times、review trigger、evidence refs、retentionは`null`または空です。これはDecision待ちであり、Decisionではありません。

### `HUMAN_OUTCOME_ENTERED_UNVERIFIED`

Human向け入力欄が埋まった形です。`human_outcome.state`は`UNVERIFIED_HUMAN_ENTRY`で、全体outcomeは三値の明示入力だけを受けます。46件の個別outcome数や多数決から導出しません。

この状態でも入力者がHumanだったことやauthorityは検証されません。statusは`CANDIDATE_ONLY`のままです。

## Exact source boundaries

`review_chain`は次の二つをlocatorとSHA-256/byte sizeへ束縛する形だけを定義します。

- handoff expected status: `CANDIDATE_DECISION_HANDOFF`
- handoff verification expected status: `DECISION_HANDOFF_MATCH`

expected status文字列をcandidateへ書くだけでは、実fileがその結果を持つことやcurrent Packに一致することを証明しません。将来のverifierはR28 CLIへ全sourceを渡して再計算する必要があります。

`intent_candidate_binding.schema_status`は常に`NOT_VERIFIED`です。現在の`records/intent-candidate.json`はRecord templateであり、実Intent Candidate instanceのschemaではありません。

## Human-entered fields

- `decision_candidate_id`: candidateの識別子。replay防止やregistry uniquenessは未実装。
- `human_outcome`: explicit overall outcome、entry evidence ref、entered-at。
- `reviewer_evidence`: opaque identity/role/authority/independence refs。
- `decision_maker_evidence`: opaque identity/role/authority refs。
- `scope`: in-scopeとout-of-scopeを分離。
- `reason`: 全体Decision候補の理由。個別review noteではない。
- `reviewed_at` / `decided_at`: RFC 3339 date-time形式のeditable時刻文字列。format妥当性はtrusted clock proofではない。
- `proposed_effective_at`: 提案時刻だけ。`effective_at`は存在しない。
- `expires_at`: candidate/authority/evidenceの再確認期限候補。
- `review_trigger`: Intent/handoff digest、evidence、scope、authority/expiry、retentionの変化を固定した6条件。
- `unresolved_evidence`: required count 5を維持。refsが5件あっても`EVIDENCE_REQUIRED`のままで、解決済みとは主張しない。
- `retention_policy_ref`: opaque reference。enforcementは別証拠。

referenceへcredential、token、個人情報、private absolute path、Human Intent本文、review note本文を埋めないでください。必要なら非公開のgoverned locatorを使い、このcandidate自体を公開しないでください。

## Generic Decision Record mapping

既存の[`decision-record.json`](../examples/company-starter/records/decision-record.json)は7つのrequired fieldを持つgeneric **Record template**です。R29 schemaはこのtemplateや[`record.schema.json`](../schemas/record.schema.json)を書き換えず、具体instanceの追加安全fieldを別契約にします。

| Generic field | R29 candidate source |
|---|---|
| `decision_id` | `decision_candidate_id`。実Decision採用時は新しいgoverned IDが必要 |
| `intent_candidate_ref` | `intent_candidate_binding.locator` + exact binding |
| `decision` | `human_outcome.selected_outcome`。現在はunverified |
| `approver_role` | `decision_maker_evidence.role`。authority proofではない |
| `evidence_ref` | review chain、person evidence、5 unresolved evidence bindings |
| `decided_at` | editable `decided_at`。trusted timeではない |
| `review_condition` | `expires_at` + fixed `review_trigger` |

schema-valid candidateをgeneric Recordへコピーしても、Human DecisionやCurrent Truthにはなりません。

## Claims and negative boundary

18個のclaimはすべて`false`固定です。unknown fieldは`additionalProperties: false`で拒否されるため、`approved`、`verified`、`effective_at`、`promotion`、`current_truth`、`execution_authority`を追加できません。

このcontractはfuture builderを許可する証拠ではありません。builder/verifierを追加する前に、少なくとも次を別contractで閉じます。

- real Intent Candidate instance schemaとverifier
- immutable/content-addressed source retrieval
- identity/authority scope/expiry/independence verification
- trusted timeとretention enforcement
- 5 evidence objectのinstance schema、authenticity、candidate binding
- self-approval、role alias、cross-candidate substitution、decision ID replayの拒否
- secret/PII/private locatorを成功・拒否・logへ反射しない処理
- exact approved DecisionからWork Orderへ進む別authority gate

それまではPublic Betaを`NO_GO_UNPUBLISHED`に保ちます。
