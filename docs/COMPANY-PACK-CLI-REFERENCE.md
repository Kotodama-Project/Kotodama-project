# Company Pack CLI Reference

このページは、公開Company Pack導線にある13個のCLI entrypointを、作成から
Decision Handoff検証まで一つの順序で辿るための索引です。各CLIは
`-h` / `--help`で共通境界を表示します。

> Boundary: read-only/candidate-only; Public Beta remains NO_GO_UNPUBLISHED.

The initializer is the only command that writes a candidate Pack directory.
It refuses an existing target. Help never writes. Catalog、check、plan、verifyは
read-onlyです。builderはJSONをstdoutへ出力し、保存するかどうかと保存先はcallerが
管理します。この導線はHuman reviewへ渡す候補を作りますが、does not create Human approval、
execution authority、Promotion、Current Truth、runtime verification、Public Beta GOを作りません。

## Create

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`create_company_pack.py`](../tools/create_company_pack.py) | `PACK_ID`、新規`TARGET_DIRECTORY`、任意のguided customization 3値 | validated candidateを作成／既存target・不完全なguided値・validation failureを拒否 | validator、customization checker |

## Inspect

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`validate_template_pack.py`](../tools/validate_template_pack.py) | Pack directory | `PASS` / `FAIL` | Catalog、customization checker |
| [`catalog_company_pack.py`](../tools/catalog_company_pack.py) | Pack directory、JSON/Markdown | `PASS` / `INVALID_PACK` | customization、Public Preview |
| [`check_company_pack_customization.py`](../tools/check_company_pack_customization.py) | Pack directory | `CUSTOMIZATION_REQUIRED` / `READY_FOR_GOVERNED_REVIEW` | candidate編集／Review Bundle |
| [`check_company_pack_public_preview.py`](../tools/check_company_pack_public_preview.py) | Pack directory、JSON/Markdown | `PASS` / `REFUSED` | Guided Next Steps |

## Plan

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`plan_company_pack_next_steps.py`](../tools/plan_company_pack_next_steps.py) | Pack directory、JSON/Markdown | `STATIC_CUSTOMIZATION` / `GOVERNED_REVIEW` / `INVALID_PACK` | report内のbounded next command |

## Bind

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`build_company_pack_review_bundle.py`](../tools/build_company_pack_review_bundle.py) | Pack directory | `CANDIDATE_FOR_GOVERNED_REVIEW` / `BUNDLE_REFUSED` | bytesを新規fileへ保存しverify |
| [`verify_company_pack_review_bundle.py`](../tools/verify_company_pack_review_bundle.py) | saved bundle、Pack directory | `MATCH` / `MISMATCH` | Review Request |

## Request

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`build_company_pack_review_request.py`](../tools/build_company_pack_review_request.py) | saved bundle、Pack directory | `CANDIDATE_REVIEW_REQUEST` / refusal | reviewer response candidate |

## Respond

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`build_company_pack_review_response.py`](../tools/build_company_pack_review_response.py) | Review Request | `REVIEW_RESPONSE_CANDIDATE` / refusal | outcomeを編集してverify |
| [`verify_company_pack_review_response.py`](../tools/verify_company_pack_review_response.py) | Review Request、Review Response | `ITEM_RESPONSES_MATCH_REQUEST` / mismatch | Decision Handoff candidate |

## Handoff

| Tool | Input | Success / stop state | Next handoff |
|---|---|---|---|
| [`build_company_pack_review_decision_handoff.py`](../tools/build_company_pack_review_decision_handoff.py) | Pack、bundle、request、responseと各schema | `CANDIDATE_DECISION_HANDOFF` / refusal | saved handoffをverify |
| [`verify_company_pack_review_decision_handoff.py`](../tools/verify_company_pack_review_decision_handoff.py) | 上記6入力とsaved handoff | `DECISION_HANDOFF_MATCH` / mismatch | 別のauthority-bound Human Decision |

## Help inventory — PowerShell / Python

```powershell
python tools/create_company_pack.py --help
python tools/validate_template_pack.py --help
python tools/catalog_company_pack.py --help
python tools/check_company_pack_customization.py --help
python tools/check_company_pack_public_preview.py --help
python tools/plan_company_pack_next_steps.py --help
python tools/build_company_pack_review_bundle.py --help
python tools/verify_company_pack_review_bundle.py --help
python tools/build_company_pack_review_request.py --help
python tools/build_company_pack_review_response.py --help
python tools/verify_company_pack_review_response.py --help
python tools/build_company_pack_review_decision_handoff.py --help
python tools/verify_company_pack_review_decision_handoff.py --help
```

## Help inventory — POSIX / Python 3

```bash
python3 tools/create_company_pack.py --help
python3 tools/validate_template_pack.py --help
python3 tools/catalog_company_pack.py --help
python3 tools/check_company_pack_customization.py --help
python3 tools/check_company_pack_public_preview.py --help
python3 tools/plan_company_pack_next_steps.py --help
python3 tools/build_company_pack_review_bundle.py --help
python3 tools/verify_company_pack_review_bundle.py --help
python3 tools/build_company_pack_review_request.py --help
python3 tools/build_company_pack_review_response.py --help
python3 tools/verify_company_pack_review_response.py --help
python3 tools/build_company_pack_review_decision_handoff.py --help
python3 tools/verify_company_pack_review_decision_handoff.py --help
```

実際のartifact引数と保存例は[Review Workflow](REVIEW-WORKFLOW.md)、最短の
Pack操作は[Starter Walkthrough](STARTER-WALKTHROUGH.md)を参照してください。
