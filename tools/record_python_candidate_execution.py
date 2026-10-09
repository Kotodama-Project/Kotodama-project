"""Bind a candidate build to read-only GitHub run/job/artifact metadata; never attest it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = "Kotodama-Project/Kotodama-project"
WORKFLOW = ".github/workflows/python-package-candidate.yml"


def require(condition):
    if not condition:
        raise ValueError("EXECUTION_BINDING_REFUSED")


def bind(build_bytes, context, run, jobs, artifact):
    build = json.loads(build_bytes)
    require(build["kind"] == "kotodama/python-candidate-build/v1" and build["status"] == "BUILT_NOT_RELEASED")
    require(context["repository"] == REPOSITORY and run["repository"]["full_name"] == REPOSITORY)
    require(re.fullmatch(r"[a-f0-9]{40}", context["sha"]) and build["source_commit"] == context["sha"])
    require(re.fullmatch(r"[a-f0-9]{40}", context["workflow_sha"]))
    require(context["workflow_ref"] == f"{REPOSITORY}/{WORKFLOW}@{context['ref']}")
    require(run["id"] == context["run_id"] and run["run_attempt"] == context["run_attempt"])
    require(run["path"] == WORKFLOW)
    require(jobs["total_count"] == len(jobs["jobs"]))
    matched = [job for job in jobs["jobs"] if job["name"] == context["job_name"]
               and job["run_id"] == context["run_id"] and job["run_attempt"] == context["run_attempt"]]
    require(len(matched) == 1 and type(matched[0]["id"]) is int and matched[0]["id"] > 0)
    require(artifact["id"] == context["artifact_id"] and artifact["name"] == context["artifact_name"])
    require(artifact["workflow_run"]["id"] == run["id"] and artifact["workflow_run"]["head_sha"] == run["head_sha"])
    require(artifact["expired"] is False and re.fullmatch(r"sha256:[a-f0-9]{64}", artifact["digest"]))
    require(artifact["digest"] == "sha256:" + context["artifact_digest"])
    return {"kind": "kotodama/python-candidate-execution/v1", "status": "GITHUB_METADATA_BOUND_NOT_ATTESTED",
            "repository": REPOSITORY, "source_commit": build["source_commit"], "source_tree": build["source_tree"],
            "workflow_ref": context["workflow_ref"], "workflow_sha": context["workflow_sha"],
            "run_id": run["id"], "run_attempt": run["run_attempt"], "job_id": matched[0]["id"],
            "job_name": context["job_name"], "event_head_sha": run["head_sha"],
            "artifact_id": artifact["id"], "artifact_name": artifact["name"], "artifact_archive_digest": artifact["digest"],
            "build_receipt_sha256": hashlib.sha256(build_bytes).hexdigest(), "builder_inputs": build["builder_inputs"],
            "signature_verified": False, "release_authorized": False, "public_beta": "NO_GO_UNPUBLISHED"}


def api(path):
    raw = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/{path}"], check=True, capture_output=True, timeout=30).stdout
    require(len(raw) <= 4 * 1024 * 1024)
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        fields = {"repository": "GITHUB_REPOSITORY", "sha": "GITHUB_SHA", "ref": "GITHUB_REF",
                  "workflow_ref": "GITHUB_WORKFLOW_REF", "workflow_sha": "GITHUB_WORKFLOW_SHA",
                  "run_id": "GITHUB_RUN_ID", "run_attempt": "GITHUB_RUN_ATTEMPT", "job_name": "CANDIDATE_JOB_NAME",
                  "artifact_id": "CANDIDATE_ARTIFACT_ID", "artifact_name": "CANDIDATE_ARTIFACT_NAME",
                  "artifact_digest": "CANDIDATE_ARTIFACT_DIGEST"}
        context = {key: os.environ[value] for key, value in fields.items()}
        require(context["repository"] == REPOSITORY)
        for key in ("run_id", "run_attempt", "artifact_id"):
            require(context[key].isascii() and context[key].isdigit())
            context[key] = int(context[key]); require(context[key] > 0)
        run_id, attempt = context["run_id"], context["run_attempt"]
        raw = args.build_receipt.read_bytes(); require(len(raw) <= 1024 * 1024)
        result = bind(raw, context, api(f"actions/runs/{run_id}"),
                      api(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"),
                      api(f"actions/artifacts/{context['artifact_id']}"))
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('{"status":"EXECUTION_BINDING_REFUSED"}')
        return 1
    print('{"status":"GITHUB_METADATA_BOUND_NOT_ATTESTED"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
