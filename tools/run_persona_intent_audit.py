"""Offline persona acceptance checks: real kernels, synthetic inputs, no live actions.

Natural-language prompts are review context, NOT sent to or understood by an LLM.
Parameter variants are reported separately from behavioral families and blocked journeys.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import html
import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
PERSONAS = [
    ("executive", "経営者", "取締役会の判断材料をまとめて", "推測と実績を分け、意思決定に未承認の数字を使わない"),
    ("operations", "業務管理者", "引継ぎ後に残る作業を教えて", "担当・期限・未完了条件が引継ぎ先に残る"),
    ("sales", "営業担当", "この顧客向け提案を準備して", "見積の有効期限と未承認の値引きを区別する"),
    ("support", "顧客対応担当", "問い合わせに回答する案を作って", "回答案と送信済みを混同せず、不明点を明記する"),
    ("finance", "経理担当", "月次照合の差異を整理して", "未照合の差異を解消済みと表示しない"),
    ("hr", "人事担当", "入社初日の案内を準備して", "権限のない従業員情報を案内へ含めない"),
    ("manager", "プロジェクト管理者", "優先順位を訂正した仕事を確認して", "訂正後の受入条件と担当するWorkが一致する"),
    ("developer", "開発担当", "修正の成果をレビューへ渡して", "実装完了と独立検証済みを分ける"),
    ("operator", "システム運用担当", "止めた処理の状況を教えて", "停止要求だけで停止済みとは判断しない"),
    ("legal", "契約審査担当", "契約の確認事項を整理して", "未回答の重要事項があるまま合格にしない"),
    ("research", "調査担当", "この調査の根拠を引き継いで", "出典の版・期限・合格条件を保持する"),
    ("contractor", "外部協力者", "自分の担当と次の手順を教えて", "閲覧範囲を広げず、次に確認することを示す"),
]
CONTEXT_FAMILIES = ("criteria-retained", "deliverable-binding", "source-changed", "source-expired", "restricted-refused", "blocking-question", "byte-budget", "correction-retained", "criteria-affects-digest")
DIAGNOSTIC_FAMILIES = ("running-visible", "stop-requested", "stop-observed", "self-verification", "stale-report", "missing-report", "inert-display")
BLOCKED = {
    "conversation-to-work": "No authenticated conversation-to-current-Work/NLU executor is exercised by this runner.",
    "real-business-action": "No authorized live company connector or full native OS session is exercised; no send/refund/merge/deploy is attempted.",
}

def diagnostic_inputs(persona):
    pid, name, prompt, criterion = persona
    registry = {"version": 1, "status": "promoted", "agents": [{"id": pid, "name": name, "purpose": prompt,
        "activation_state": "active", "authority": "read_only", "implementation": {"kind": "external_adapter", "path": "fixture://adapter"}}]}
    contract = {"version": 1, "status": "candidate_only", "common_agent_view": {
        "required_fields": ["kotodama_agent_id", "connection_state", "verification_state"],
        "connection_states": ["unknown", "offline", "idle", "running", "needs_user", "failed", "stalled", "interrupted"],
        "execution_completion_is_not_verification": True}, "work_contract": {
        "stop_request_requires_stop_observation": True,
        "result_states": ["queued", "running", "needs_user", "execution_settled", "verification_pending", "verified_candidate", "failed", "cancelled", "stalled"]},
        "adapters": {"external_agents": {"state": "planned"}}}
    observations = {"version": 1, "observations": [{"kotodama_agent_id": pid, "observation_ref": f"fixture:{pid}-observation",
        "adapter_id": "external_agents", "observed_at": "2026-09-11T00:00:00Z", "connection_state": "running",
        "current_work_ref": f"fixture:{pid}-work", "run_ref": f"fixture:{pid}-run", "work_state": "running",
        "stop_requested_at": None, "stop_observed_at": None}]}
    return registry, contract, observations

def inventory(root):
    """AST inventory is a coverage map, not a claim of semantic test review."""
    records = []
    for path in sorted((root / "tests").rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            calls = sorted({ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)})
            records.append({"path": path.relative_to(root).as_posix(), "line": node.lineno,
                "test": node.name, "docstring": ast.get_docstring(node),
                "assertion_calls": [c for c in calls if "assert" in c.lower()],
                "other_calls": [c for c in calls if "assert" not in c.lower()],
                "decorators": [ast.unparse(d) for d in node.decorator_list],
                "review_status": "structurally_inventoried_not_individually_semantically_certified"})
    return records

def run(root=ROOT):
    root = Path(root).resolve()
    # Only the operator-selected repository's existing implementation is called.
    sys.path.insert(0, str(root / "tools"))
    compiler = importlib.import_module("compile_knowledge_context")
    projector = importlib.import_module("project_agent_status")
    schema = json.loads((root / "schemas/knowledge-context-bundle.schema.json").read_text())
    from jsonschema import Draft202012Validator, FormatChecker
    output_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    records = []
    for persona in PERSONAS:
        pid, name, prompt, criterion = persona
        for family in CONTEXT_FAMILIES + DIAGNOSTIC_FAMILIES + tuple(BLOCKED):
            record = {"id": f"{pid}/{family}", "persona": name, "prompt_for_review_only": prompt,
                      "family": family, "user_intent": criterion, "status": "BLOCKED" if family in BLOCKED else "FAIL",
                      "scope": "synthetic-input real implementation; not natural-language or live-business E2E"}
            if family in BLOCKED:
                record.update(expected="A real user completes the authorized journey with traceable evidence.",
                              actual=BLOCKED[family], failures=[])
                records.append(record); continue
            failures = []
            def check(condition, message):
                if not condition:
                    failures.append(message)
            try:
                if family in CONTEXT_FAMILIES:
                    with tempfile.TemporaryDirectory(prefix="kotodama-persona-") as temp:
                        workspace = Path(temp) / "package"
                        shutil.copytree(root / "examples/knowledge-work/business-rehearsal", workspace)
                        manifest = workspace / "knowledge-work.json"
                        package = json.loads(manifest.read_text(encoding="utf-8"))
                        package["objective"] = prompt
                        package["criteria"][0]["description"] = criterion
                        limits = {}
                        expected = "READY_CANDIDATE"
                        if family == "source-changed":
                            (workspace / "source.txt").write_text("Synthetic changed evidence", encoding="utf-8"); expected = "REFUSED"
                        elif family == "source-expired":
                            package["sources"][0].update(kind="local_snapshot", expires_at="2026-09-10T00:00:00Z"); expected = "REFUSED"
                        elif family == "restricted-refused":
                            package["sensitivity"] = "restricted"
                            package["sources"][0]["sensitivity"] = "restricted"
                            for c in package["claims"]: c["sensitivity"] = "restricted"
                            expected = "REFUSED"
                        elif family == "blocking-question":
                            package["questions"][0]["blocking"] = True; expected = "REFUSED"
                        elif family == "byte-budget":
                            limits["max_bytes"] = 256; expected = "REFUSED"
                        elif family == "correction-retained":
                            criterion += "。訂正: 外部送信は実行しない"
                            package["criteria"][0]["description"] = criterion
                        manifest.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
                        before = {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file()}
                        output = compiler.compile_context(workspace, now=NOW, **limits)
                        check(output["status"] == expected, "wrong readiness/refusal outcome")
                        check(not list(output_validator.iter_errors(output)), "output violates shipped schema")
                        check(not any(output["claims"].values()), "candidate improperly claims approval/authorization")
                        check(before == {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file()}, "read-only compilation changed fixture")
                        if expected == "READY_CANDIDATE":
                            check(criterion in [x.get("description") for x in output.get("acceptance_criteria", [])], "user acceptance criterion missing from actual executor context")
                            check(output.get("deliverable_bindings") == [{"id": d["id"], "sha256": d["sha256"], "criterion_refs": d["criterion_refs"]} for d in package["deliverables"]], "deliverable/criterion binding missing or changed")
                            check(all("reported_state" in x and "state" not in x for x in output.get("acceptance_criteria", [])), "producer claim not labeled reported")
                            if family == "criteria-affects-digest":
                                previous = output["context_sha256"]
                                package["criteria"][0]["description"] += "。訂正された条件"
                                manifest.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
                                changed = compiler.compile_context(workspace, now=NOW)
                                check(changed["context_sha256"] != previous, "context identity ignores acceptance changes")
                                check(changed.get("acceptance_criteria", [{}])[0].get("description") == package["criteria"][0]["description"], "changed context still omits corrected criterion")
                        else:
                            check(output.get("work_ref") is None and output.get("objective") is None, "refusal leaks Work/intent")
                            check(not output.get("acceptance_criteria") and not output.get("deliverable_bindings"), "refusal leaks acceptance or deliverable metadata")
                        record.update(expected=expected + "; retain definition of done or redact all context on refusal", actual={"status": output["status"], "errors": output["errors"], "criterion_count": len(output.get("acceptance_criteria", []))})
                else:
                    registry, contract, observations = diagnostic_inputs(persona)
                    obs = observations["observations"][0]
                    if family in ("stop-requested", "stop-observed"):
                        obs["stop_requested_at"] = "2026-09-10T23:59:50Z"
                    if family == "stop-observed":
                        obs.update(connection_state="interrupted", work_state="cancelled", stop_observed_at="2026-09-10T23:59:55Z")
                    if family == "self-verification": obs["work_state"] = "verified_candidate"
                    if family == "missing-report": observations["observations"] = []
                    if family == "inert-display": registry["agents"][0]["name"] = "![untrusted](https://example.invalid/pixel)<script>|`unsafe`"
                    report = projector.project(registry, contract, observations,
                        as_of="2026-09-11T00:02:00Z" if family == "stale-report" else "2026-09-11T00:00:30Z")
                    row = report["agents"][0]
                    # Capability adaptation only; expected facts remain independent of output.
                    kwargs = {"include_context": True} if "include_context" in inspect.signature(projector.markdown).parameters else {}
                    raw_markdown = projector.markdown(report, **kwargs)
                    rendered = html.unescape(raw_markdown)
                    expected_state = "unknown" if family in ("stale-report", "missing-report") else "interrupted" if family == "stop-observed" else "running"
                    check(row["connection_state"] == expected_state, "connection misrepresents freshness")
                    check(row["verification_state"] == "not_evaluated" and not row["controls"], "self-report grants verification or control")
                    check(not report["mutations_enabled"] and not report["runtime_evidence_verified"], "offline diagnostic claims live authority")
                    for text in ("Work", "Run", "Stop", "Verification", "Last observed", report["as_of"], row["verification_state"]):
                        check(text in rendered, "decision-critical display field missing: " + text)
                    if family not in ("stale-report", "missing-report"):
                        check(obs["current_work_ref"] in rendered and obs["run_ref"] in rendered, "operator cannot identify Work/run")
                    if family in ("stop-requested", "stop-observed"):
                        stop = "requested" if family == "stop-requested" else "observed"
                        check(row["stop_state"] == stop and stop in rendered, "stop request/confirmation not distinguishable")
                    if family == "inert-display":
                        check("example.invalid/pixel" in rendered, "explicit synthetic context display omits name")
                        private_default = projector.markdown(report)
                        check("example.invalid/pixel" not in private_default, "default display exposes private narrative")
                        check("![untrusted](" not in raw_markdown and "<script>" not in raw_markdown, "untrusted text becomes active markup")
                    record.update(expected="Decision-critical facts remain visible without conferring authority", actual={"connection": row["connection_state"], "stop": row["stop_state"], "verification": row["verification_state"]})
            except Exception as exc:
                failures.append("unhandled exception: " + type(exc).__name__)
            record.update(status="FAIL" if failures else "PASS", failures=failures)
            records.append(record)
    counts = {state: sum(r["status"] == state for r in records) for state in ("PASS", "FAIL", "BLOCKED")}
    files = ["tools/compile_knowledge_context.py", "tools/knowledge_work_validator.py", "tools/project_agent_status.py", "schemas/knowledge-context-bundle.schema.json"]
    return {"version": 1, "kind": "offline_persona_intent_audit", "counts": counts,
            "personas": len(PERSONAS), "executed_behavior_families": len(CONTEXT_FAMILIES + DIAGNOSTIC_FAMILIES),
            "blocked_families": len(BLOCKED), "source_sha256": {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files},
            "claims": {"natural_language_understanding_tested": False, "full_native_os_e2e_tested": False,
                       "live_company_actions_tested": False, "independent_human_review": False}, "cases": records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    if args.inventory:
        result = {"scope": "AST inventory, not semantic certification", "tests": inventory(args.root)}
    else:
        result = run(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("counts", {}).get("FAIL", 0) else 0

if __name__ == "__main__":
    raise SystemExit(main())
