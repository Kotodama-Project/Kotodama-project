# Public Migration Ledger

公開移行台帳は、移行対象ごとの **disposition（処遇）** を、追記専用の hash chain
として公開側に記録するための契約です。移行そのものを実行するものではなく、素材を
公開するものでもありません。記録されるのは opaque な参照、digest、gate 結果、
集計だけです。hash chain の内部整合性と、独立に pin した既存 head への append-only
境界の検証は別の主張です。

- Schema: `schemas/public-migration-ledger.schema.json`
- Verifier: `tools/validate_public_migration_ledger.py`
- Tests: `tests/test_public_migration_ledger_contract.py`
- Fixture: `tests/fixtures/public-migration-ledger/valid.jsonl`
- Ledger location: `migration/public-migration-ledger.v1.jsonl`（現在は未作成。
  `migration/README.md` を参照）

## なぜ語彙を分けるのか

移行の議論では「最終的にどう分類したか」と「もし実行するならどう移すか」が
混ざりやすく、混ざったままでは *unclassified が 0 件である* ことを機械検証
できません。この契約では次を別フィールドとして持ちます。

| フィールド | 意味 | 値 |
|---|---|---|
| `terminal_classification` | 唯一の終端分類 | `PUBLIC_EXTRACT` / `PRIVATE_RETAIN` / `REGENERATE` / `DROP`、または `BLOCKED` 中だけ `null` |
| `transfer_mode` | 実行するとした場合の移送機構 | `REAUTHOR` / `GENERATE` / `NO_COPY`、または `null` |
| `proposed_action` | 提案された行為への opaque 参照 | `ref/...` または `null` |
| `supersession_reason` | 後続に置き換えられた理由 | 列挙値または `null` |
| `status` | 手続き上の状態 | `BLOCKED` / `PROPOSED` / `ACCEPTED` / `REJECTED` |

`RE_AUTHORED`、`PUBLIC_REAUTHOR`、`SUPERSEDED` のような語は移送機構または
置換理由であり、終端分類ではありません。verifier は片方の語彙をもう片方の
フィールドに入れることを拒否します。

## 公開安全性

- すべての識別子は `ref/<64桁の小文字 SHA-256 形式>` の opaque 参照です。
  descriptive な path segment、private path、repository path、URL、provider handle、
  host、参加者識別子は schema が拒否します。
- private な証跡は `private_receipt_ref` と `private_receipt_digest` の組でのみ
  参照します。参照を解決するには、この台帳が持たない private authority が必要です。
- 記録は素材そのものを持ちません。台帳は「何をどう処遇したか」の metadata です。

## 追記と改竄検知

各行は 1 レコードの JSONL です。

- `sequence` は 1 から始まり、欠番なく連続します。
- `prev_hash` は直前レコードの `content_hash` で、先頭レコードは 64 個の `0` です。
- `content_hash` は、`content_hash` を除いたレコードを
  `sort_keys=True` かつ区切りを `(",", ":")` にした UTF-8 の canonical JSON へ
  符号化した SHA-256 です。追記時は
  `tools/validate_public_migration_ledger.py` の `canonical_content_hash()` を
  唯一の実装として使います。
- レコードを 1 件削除・並べ替え・改変すると、そこから先の連鎖が壊れます。

### Trusted head anchor

Genesis (`64個の0`) からの chain だけでは、入力全体を編集して全 hash を再計算した
自己整合的な別履歴を見分けられません。append-only の境界を検証する場合は、台帳とは
別に保護された既存 head の digest を `--anchor` で渡します。

```text
python tools/validate_public_migration_ledger.py LEDGER_JSONL --anchor TRUSTED_HEAD_SHA256
```

verifier は trusted head が chain 内に一度だけ現れることを確認し、そのレコードより
後ろを append 部分として扱います。anchor の authority、署名、完全履歴、parallel
branch 不存在はこの verifier の責任範囲ではありません。`--anchor` を省略した結果は
内部整合性の candidate-only 検査であり、`chain_anchor.matched` は `null` になります。

## Gate の一貫性

`gates` は 5 つの独立した gate 結果（`license_provenance`、`secret_scan`、
`history_scan`、`dependency_baseline`、`independent_review`）を持ちます。

- `ACCEPTED` は全 gate が `PASS` のときだけ許されます（`GATE_BYPASS`）。
- `BLOCKED` は少なくとも 1 つ非 `PASS` の gate を必要とします。
- `FAIL` を含むレコードは `PROPOSED` や `ACCEPTED` に留まれません。
- `DROP` は `NO_COPY` を、`REGENERATE` は `GENERATE` を要求します。
- `supersession_reason` は `REJECTED` のときにだけ記録できます。

## 実行

```
python tools/validate_public_migration_ledger.py `
  migration/public-migration-ledger.v1.jsonl `
  --anchor <trusted-previous-head-sha256>
```

成功時の出力は次の形です。

```json
{
  "contract": "kotodama.public-migration-ledger/v1",
  "result": "LEDGER_CONSISTENT_UNVERIFIED",
  "reason_codes": [],
  "record_count": 5,
  "terminal_classification_counts": { "...": 0 },
  "zero_unclassified": false,
  "public_beta": "NO_GO_UNPUBLISHED",
  "chain_anchor": {"provided": true, "matched": true}
}
```

## Luna Task swarm との対応

main の [Luna Task swarm](LUNA-TASK-SWARM.md)（`runtime/task_swarm`）とこの台帳は、別の記録です。
Luna の SQLite（`runs`・`jobs`・`attempts`）は、Task を並列に進めるための実行の記録です。
この台帳は、移行対象ごとの処遇の記録です。どちらも相手を読み書きしないので、Luna の run が
終わっても台帳の record は増えません。考え方の近い項目は次のとおりです。

| 台帳の項目 | Luna Task swarm で近いもの | まだ対応していないこと |
|---|---|---|
| 記録の単位: `subject_ref` ごとの処遇を 1 行の JSONL に書く | run の中の job と、`claim` ごとの attempt（`(run_id, job_id, attempt)` で一意） | 移行対象と Luna の job を対応づける変換は無い |
| 改竄検知: `sequence`、`prev_hash`、`content_hash` の hash chain と `--anchor` | 現在でない attempt token の report を `STALE_ATTEMPT` で拒否する | Luna の記録に hash chain は無い。job と attempt の状態は同じ行を更新する |
| 受入: `status=ACCEPTED` は 5 つの gate がすべて `PASS` のときだけ | owner の `accept(run_id, job_id, result_digest, verification_ref, owner_ref)`。worker は自分の report を受け入れられない | Luna の `accept` は job の受入であり、台帳の `ACCEPTED` や `gates.independent_review=PASS` の証拠にはならない |
| 追記: `migration/README.md` の手順で、private receipt の digest が確定してから足す | 対応するものは無い | Luna の状態から台帳の record を書き出す経路は無い |

agent の実行を契約として比べる表は [Agent Swarm × Kotodama Adoption Candidate](AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md#luna-task-swarm-との対応) にあります。

## この検証が意味しないこと

`LEDGER_CONSISTENT_UNVERIFIED` は、記録された処遇が構造的・内部的に整合して
いることだけを示します。移行が実行されたこと、private 側の継続性、公開抽出物の
公開、依存関係の切り替え、rollback の予行、独立検証、Human Decision、Promotion、
Current Truth、Public Beta GO のいずれも意味しません。verifier の出力は claim を
すべて `false` として返し、`public_beta` は常に `NO_GO_UNPUBLISHED` です。

`zero_unclassified` が `true` になっても、それは各 `subject_ref` の最新 record に
「blocked のまま分類されていない record」が無いことだけを示します。過去 record が
残る append-only chain では、同じ subject の最新 disposition だけを集計します。
拒否された入力では `zero_unclassified` は `null` で、coverage の positive signal を
返しません。台帳に載っていない対象があるかどうかは、この契約の範囲外です。
