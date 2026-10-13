"""Invocation-local reuse of a completely verified local-executor origin.

Only deterministic interpretation is retained. Current authority, raw evidence,
filesystem topology and the execution DB are read again at every boundary.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .loop_executor import MAX_PROOF_BYTES
from .protocol import SwarmError
from .task_contract import require
from .task_runner import read_bytes, safe_directory


class VerifiedOrigin:
    def __init__(self, executor, cut, input_path, input_sha):
        self.executor, self.cut = executor, cut
        self.input_path, self.input_sha = Path(input_path), input_sha
        self.layouts = []
        # These exact responses were verified against the DB. Do not learn new
        # hashes from a post-verification snapshot, including raw-only edits.
        for job, row in executor.snapshot["jobs"].items():
            response = executor.document(job + "-result.json", row["current_attempt"]["result_digest"])
            runtime = response["receipt"]["runtime"]
            paths = {Path(runtime["paths"][key]): sha for key, sha in runtime["receipt"]["artifact_digests"].items()}
            paths[Path(runtime["paths"]["receipt"])] = runtime["runtime_receipt_sha256"]
            paths[Path(runtime["receipt"]["runtime_receipt_path"])] = runtime["runtime_rollout_sha256"]
            consumed = 0
            for path, sha in paths.items():
                raw = read_bytes(path, MAX_PROOF_BYTES - consumed)
                require(hashlib.sha256(raw).hexdigest() == sha, "RUN_RUNTIME_ARTIFACT_CHANGED")
                consumed += len(raw)
            base = executor.directory / (job + "-attempt")
            self.layouts.append((base, Path(runtime["paths"]["attempt_dir"]), base / "sessions",
                                 Path(runtime["paths"]["diagnostics"]), MAX_PROOF_BYTES - consumed))
        self.layouts = tuple(self.layouts)
        self.current()

    def current(self, after_policy=None):
        def fresh():
            if after_policy is not None:
                after_policy()
            executor = self.executor
            require(executor.state.completed_evidence_cut(executor.plan["run_id"]) == self.cut,
                    "FINALIZATION_STATE_CHANGED")
            try:
                require(hashlib.sha256(read_bytes(self.input_path, 256 * 1024)).hexdigest() == self.input_sha,
                        "REUSE_ORIGIN_ARTIFACT_CHANGED")
                for base, attempt, sessions, diagnostics, remaining in self.layouts:
                    # Diagnostics are bounded readable data, not an authority
                    # hash. Keep the original per-invocation total byte limit.
                    for directory in (base, attempt, sessions):
                        safe_directory(directory)
                    read_bytes(diagnostics, remaining)
            except OSError as exc:
                raise SwarmError("RUN_RUNTIME_ARTIFACT_CHANGED", "origin evidence is unavailable") from exc
        self.executor.current(after_policy=fresh)
