#!/usr/bin/env python3
"""Exercise the public Company Pack review chain in one temporary workspace."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_template_pack import emit_help_if_requested


STEP_IDS = (
    "create",
    "validate",
    "catalog",
    "customization",
    "public_preview",
    "next_steps",
    "review_bundle",
    "review_bundle_verify",
    "review_request",
    "review_response",
    "review_response_verify",
    "decision_handoff",
    "decision_handoff_verify",
)
REFUSAL_REASONS = {
    "CHILD_REFUSED",
    "CHILD_TIMEOUT",
    "CHILD_OUTPUT_LIMIT",
    "CHILD_OUTPUT_INVALID",
    "CHILD_CONTRACT_MISMATCH",
    "TEMPORARY_CLEANUP_UNVERIFIED",
    "INTERNAL_REFUSAL",
}
CLAIMS = {
    "human_approval_verified": False,
    "reviewer_identity_verified": False,
    "execution_authority_verified": False,
    "runtime_verified": False,
    "promotion_verified": False,
    "current_truth_changed": False,
    "final_human_go": False,
    "public_beta_go": False,
}
MAX_CHILD_OUTPUT_BYTES = 1024 * 1024
CHILD_TIMEOUT_SECONDS = 30
EXPECTED_KINDS = {
    "create": "company_pack_creation_report",
    "catalog": "company_pack_catalog",
    "customization": "company_pack_customization_report",
    "public_preview": "company_pack_public_preview_check",
    "next_steps": "company_pack_next_steps_plan",
    "review_bundle": "company_pack_review_bundle",
    "review_bundle_verify": "company_pack_review_bundle_verification",
    "review_request": "company_pack_review_request",
    "review_response": "company_pack_review_response",
    "review_response_verify": "company_pack_review_response_verification",
    "decision_handoff": "company_pack_review_decision_handoff",
    "decision_handoff_verify": "company_pack_review_decision_handoff_verification",
}


class SmokeRefusal(Exception):
    """Carry only a fixed reason and step ID across the refusal boundary."""

    def __init__(self, step_id: str, reason: str) -> None:
        self.step_id = step_id
        self.reason = reason


def report(
    status: str,
    completed_steps: tuple[str, ...] = (),
    failed_step: str | None = None,
    refusal_reason: str | None = None,
    temporary_workspace_deleted: bool = True,
) -> dict[str, Any]:
    if refusal_reason is not None and refusal_reason not in REFUSAL_REASONS:
        raise ValueError("unsupported refusal reason")
    step_states = []
    for step_id in STEP_IDS:
        if step_id in completed_steps:
            step_status = "PASS"
        elif step_id == failed_step:
            step_status = "REFUSED"
        else:
            step_status = "NOT_RUN"
        step_states.append({"id": step_id, "status": step_status})
    return {
        "kind": "company_pack_review_chain_smoke",
        "version": "1.0",
        "status": status,
        "steps": step_states,
        "failed_step": failed_step,
        "refusal_reason": refusal_reason,
        "temporary_workspace_deleted": temporary_workspace_deleted,
        "artifacts_persisted": False,
        "claims": dict(CLAIMS),
        "public_beta": "NO_GO_UNPUBLISHED",
    }


def write_stdout(value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = payload.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(payload)
        sys.stdout.flush()
    else:
        buffer.write(encoded)
        buffer.flush()


def capture_child(
    step_id: str, command: list[str]
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise SmokeRefusal(step_id, "INTERNAL_REFUSAL") from exc

    outputs: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    total_bytes = 0
    output_limit_exceeded = False
    lock = threading.Lock()

    def drain(name: str, stream: Any) -> None:
        nonlocal total_bytes, output_limit_exceeded
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            exceeded_now = False
            with lock:
                remaining = MAX_CHILD_OUTPUT_BYTES - total_bytes
                if remaining > 0:
                    outputs[name].append(chunk[:remaining])
                total_bytes += len(chunk)
                if total_bytes > MAX_CHILD_OUTPUT_BYTES and not output_limit_exceeded:
                    output_limit_exceeded = True
                    exceeded_now = True
            if exceeded_now:
                try:
                    process.kill()
                except OSError:
                    pass

    stdout_thread = threading.Thread(
        target=drain, args=("stdout", process.stdout), daemon=True
    )
    stderr_thread = threading.Thread(
        target=drain, args=("stderr", process.stderr), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=CHILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        process.kill()
        raise SmokeRefusal(step_id, "INTERNAL_REFUSAL")
    if timed_out:
        raise SmokeRefusal(step_id, "CHILD_TIMEOUT")
    if output_limit_exceeded:
        raise SmokeRefusal(step_id, "CHILD_OUTPUT_LIMIT")
    return returncode, b"".join(outputs["stdout"]), b"".join(outputs["stderr"])


def run_tool(step_id: str, tool: str, *arguments: str) -> tuple[dict[str, Any], str]:
    returncode, stdout_bytes, stderr_bytes = capture_child(
        step_id,
        [sys.executable, "-S", "-B", str(TOOLS_DIR / tool), *arguments],
    )
    try:
        stdout = stdout_bytes.decode("utf-8")
        stderr = stderr_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SmokeRefusal(step_id, "CHILD_OUTPUT_INVALID") from exc
    if returncode != 0 or stderr:
        raise SmokeRefusal(step_id, "CHILD_REFUSED")
    try:
        value = json.loads(stdout)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise SmokeRefusal(step_id, "CHILD_OUTPUT_INVALID") from exc
    if not isinstance(value, dict):
        raise SmokeRefusal(step_id, "CHILD_OUTPUT_INVALID")
    return value, stdout


def require_contract(
    step_id: str,
    value: dict[str, Any],
    *,
    expected_status: str,
) -> None:
    if value.get("status") != expected_status:
        raise SmokeRefusal(step_id, "CHILD_CONTRACT_MISMATCH")
    expected_kind = EXPECTED_KINDS.get(step_id)
    if expected_kind is None:
        return
    claims = value.get("claims")
    if (
        value.get("kind") != expected_kind
        or value.get("version") != "1.0"
        or value.get("public_beta") != "NO_GO_UNPUBLISHED"
        or not isinstance(claims, dict)
        or not claims
        or any(claim is not False for claim in claims.values())
    ):
        raise SmokeRefusal(step_id, "CHILD_CONTRACT_MISMATCH")


def save_exact(path: Path, payload: str, step_id: str) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload.encode("utf-8"))
    except (OSError, UnicodeError) as exc:
        raise SmokeRefusal(step_id, "INTERNAL_REFUSAL") from exc


def run_chain(workspace: Path) -> tuple[str, ...]:
    completed: list[str] = []
    target = workspace / "candidate"
    bundle_path = workspace / "review-bundle.json"
    bundle_verification_path = workspace / "review-bundle-verification.json"
    request_path = workspace / "review-request.json"
    response_path = workspace / "review-response.json"
    response_verification_path = workspace / "review-response-verification.json"
    handoff_path = workspace / "decision-handoff.json"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat().replace("+00:00", "Z")

    created, _ = run_tool(
        "create",
        "create_company_pack.py",
        "smoke-candidate",
        str(target),
        "--human-intent-ref",
        "human-intent:synthetic-smoke-v1",
        "--authority-expires-at",
        expires_at,
        "--retention-policy-ref",
        "retention-policy:synthetic-smoke-v1",
    )
    require_contract("create", created, expected_status="PASS")
    if created.get("customization_status") != "READY_FOR_GOVERNED_REVIEW":
        raise SmokeRefusal("create", "CHILD_CONTRACT_MISMATCH")
    completed.append("create")

    validated, _ = run_tool("validate", "validate_template_pack.py", str(target))
    require_contract("validate", validated, expected_status="PASS")
    if validated.get("errors") != [] or not isinstance(
        validated.get("validated_files"), int
    ) or validated["validated_files"] < 1:
        raise SmokeRefusal("validate", "CHILD_CONTRACT_MISMATCH")
    completed.append("validate")

    catalog, _ = run_tool("catalog", "catalog_company_pack.py", str(target))
    require_contract("catalog", catalog, expected_status="PASS")
    completed.append("catalog")

    customization, _ = run_tool(
        "customization", "check_company_pack_customization.py", str(target)
    )
    require_contract(
        "customization",
        customization,
        expected_status="READY_FOR_GOVERNED_REVIEW",
    )
    completed.append("customization")

    preview, _ = run_tool(
        "public_preview", "check_company_pack_public_preview.py", str(target)
    )
    require_contract("public_preview", preview, expected_status="PASS")
    completed.append("public_preview")

    next_steps, _ = run_tool(
        "next_steps", "plan_company_pack_next_steps.py", str(target)
    )
    require_contract(
        "next_steps", next_steps, expected_status="READY_FOR_GOVERNED_REVIEW"
    )
    current_state = next_steps.get("current_state")
    if not isinstance(current_state, dict) or current_state.get("stage") != "CANDIDATE_BINDING":
        raise SmokeRefusal("next_steps", "CHILD_CONTRACT_MISMATCH")
    completed.append("next_steps")

    bundle, bundle_payload = run_tool(
        "review_bundle", "build_company_pack_review_bundle.py", str(target)
    )
    require_contract(
        "review_bundle", bundle, expected_status="CANDIDATE_FOR_GOVERNED_REVIEW"
    )
    save_exact(bundle_path, bundle_payload, "review_bundle")
    completed.append("review_bundle")

    bundle_verification, bundle_verification_payload = run_tool(
        "review_bundle_verify",
        "verify_company_pack_review_bundle.py",
        str(bundle_path),
        str(target),
    )
    require_contract(
        "review_bundle_verify", bundle_verification, expected_status="MATCH"
    )
    save_exact(
        bundle_verification_path,
        bundle_verification_payload,
        "review_bundle_verify",
    )
    completed.append("review_bundle_verify")

    request, request_payload = run_tool(
        "review_request",
        "build_company_pack_review_request.py",
        str(bundle_path),
        str(target),
    )
    require_contract(
        "review_request", request, expected_status="CANDIDATE_REVIEW_REQUEST"
    )
    save_exact(request_path, request_payload, "review_request")
    completed.append("review_request")

    response, _ = run_tool(
        "review_response", "build_company_pack_review_response.py", str(request_path)
    )
    require_contract(
        "review_response", response, expected_status="REVIEW_RESPONSE_CANDIDATE"
    )
    review_response = response.get("review_response")
    items = review_response.get("items") if isinstance(review_response, dict) else None
    if not isinstance(items, list) or not items:
        raise SmokeRefusal("review_response", "CHILD_CONTRACT_MISMATCH")
    for item in items:
        if not isinstance(item, dict):
            raise SmokeRefusal("review_response", "CHILD_CONTRACT_MISMATCH")
        item["outcome"] = "accept"
    response_payload = json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n"
    save_exact(response_path, response_payload, "review_response")
    completed.append("review_response")

    response_verification, response_verification_payload = run_tool(
        "review_response_verify",
        "verify_company_pack_review_response.py",
        str(request_path),
        str(response_path),
    )
    require_contract(
        "review_response_verify",
        response_verification,
        expected_status="ITEM_RESPONSES_MATCH_REQUEST",
    )
    save_exact(
        response_verification_path,
        response_verification_payload,
        "review_response_verify",
    )
    completed.append("review_response_verify")

    handoff, handoff_payload = run_tool(
        "decision_handoff",
        "build_company_pack_review_decision_handoff.py",
        str(bundle_path),
        str(target),
        str(bundle_verification_path),
        str(request_path),
        str(response_path),
        str(response_verification_path),
    )
    require_contract(
        "decision_handoff", handoff, expected_status="CANDIDATE_DECISION_HANDOFF"
    )
    save_exact(handoff_path, handoff_payload, "decision_handoff")
    completed.append("decision_handoff")

    handoff_verification, _ = run_tool(
        "decision_handoff_verify",
        "verify_company_pack_review_decision_handoff.py",
        str(bundle_path),
        str(target),
        str(bundle_verification_path),
        str(request_path),
        str(response_path),
        str(response_verification_path),
        str(handoff_path),
    )
    require_contract(
        "decision_handoff_verify",
        handoff_verification,
        expected_status="DECISION_HANDOFF_MATCH",
    )
    completed.append("decision_handoff_verify")
    return tuple(completed)


def execute_smoke() -> tuple[dict[str, Any], int]:
    completed: tuple[str, ...] = ()
    failed_step: str | None = None
    refusal_reason: str | None = None
    temporary_path: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="kotodama-review-chain-smoke-") as raw:
            temporary_path = Path(raw)
            completed = run_chain(temporary_path)
    except SmokeRefusal as refusal:
        failed_step = refusal.step_id
        refusal_reason = refusal.reason
    except (OSError, RuntimeError, ValueError, TypeError, RecursionError):
        refusal_reason = "INTERNAL_REFUSAL"

    cleanup_verified = temporary_path is not None and not temporary_path.exists()
    if not cleanup_verified:
        refusal_reason = "TEMPORARY_CLEANUP_UNVERIFIED"
    if refusal_reason is not None:
        return (
            report(
                "REFUSED",
                completed_steps=completed,
                failed_step=failed_step,
                refusal_reason=refusal_reason,
                temporary_workspace_deleted=cleanup_verified,
            ),
            1,
        )
    if completed != STEP_IDS:
        return (
            report(
                "REFUSED",
                completed_steps=completed,
                refusal_reason="INTERNAL_REFUSAL",
                temporary_workspace_deleted=cleanup_verified,
            ),
            1,
        )
    return report("PASS", completed_steps=completed), 0


def main(argv: list[str]) -> int:
    if emit_help_if_requested(
        argv,
        usage="usage: smoke_company_pack_review_chain.py",
        purpose=(
            "Run the thirteen-step Company Pack review-chain smoke in a "
            "temporary workspace."
        ),
    ):
        return 0
    if len(argv) != 1:
        print("usage: smoke_company_pack_review_chain.py", file=sys.stderr)
        return 2
    result, exit_code = execute_smoke()
    write_stdout(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
