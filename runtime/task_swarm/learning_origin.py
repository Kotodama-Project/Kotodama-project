"""Invocation-local reuse of a completely verified local-executor origin.

Only deterministic interpretation is retained. Current authority, raw evidence,
filesystem topology and the execution DB are read again at every boundary.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory

from .loop_executor import MAX_PROOF_BYTES
from .protocol import SwarmError, canonical, digest
from .task_contract import require
from .task_runner import read_bytes, read_json, safe_directory


class ReadOnlyOrigin:
    """One public proposal's private scheduler copy and final live-file fence.

    The original DB and WAL are binary input; original SHM is never opened. Old scheduler
    table initialization is confined to the private copy and only after the
    anchored writer format and the original core schema have been validated.
    """

    def __init__(self, owner, input_path, input_sha, payload, receipt, anchor, directory, clock):
        self.owner, self.payload, self.receipt = owner, payload, receipt
        self.input_path, self.input_sha = Path(input_path), input_sha
        self.directory, self.anchor, self.clock = directory, anchor, clock
        self.database = directory / "execution.sqlite"
        self.executor = None

    def __enter__(self):
        from .repair_planning import _inspection_state, profile
        from .closed_loop_contract import evidence_version
        from .dependency_contract import execution_version
        from .loop_executor import executor_version
        self.temporary = TemporaryDirectory(prefix="kotodama-learning-read-")
        try:
            area = Path(self.temporary.name)
            self.cut = self._cut(area)
            self.owner_sha = read_json(self.owner.path, 1024 * 1024, with_digest=True)[1]
            self.binding = self.owner.read_task(self.payload["task_id"])
            self._inputs()
            plan = read_json(self.directory / "plan.json")
            template = read_json(self.directory / "r0-critic-template.json")
            require({"plan.json", "r0-critic-template.json"} <= self.receipt["artifact_sha256"].keys(),
                    "REUSE_ORIGIN_STATE")
            # Bind the format to the original stored plan before interpreting
            # its version or admitting any absent historical optional tables.
            with closing(sqlite3.connect((area / self.database.name).as_uri() + "?mode=ro", uri=True)) as db:
                run_id = "task-run-" + digest([self.payload["task_id"], self.payload["revision"]])[:32]
                row = db.execute("SELECT plan_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
                require(row is not None and isinstance(row[0], str), "REUSE_ORIGIN_STATE")
                require(canonical(json.loads(row[0])) == canonical(plan),
                        "REUSE_ORIGIN_PLAN_MISMATCH")
            evidence = evidence_version(plan, template)
            version = execution_version(plan) or evidence
            require(type(self.receipt.get("version")) is int and self.receipt["version"] == version
                    and self.receipt.get("coordinator") == f"closed_loop_v{version}", "LOOP_EVIDENCE_POLICY")
            legacy = ()
            if version in (1, 2) and profile(template) is None and executor_version(plan, template) is None:
                legacy = ("run_cancellations",)
                if version == 1 and "finalization_checkpoint_digest" not in self.receipt:
                    legacy += ("run_finalizations",)
            self.dependency, self.legacy = version == 3, legacy
            self.state = _inspection_state(area / self.database.name, self.owner, self.clock,
                                           dependency=self.dependency, legacy_optional=self.legacy)
            self.core_cut = self._evidence_cut(self.state)
            self.check()
            return self
        except (OSError, sqlite3.Error, ValueError, RecursionError) as exc:
            self.temporary.cleanup()
            raise SwarmError("REUSE_ORIGIN_STATE", "saved origin state is unavailable or invalid") from exc
        except BaseException:
            self.temporary.cleanup()
            raise

    def __exit__(self, *exc):
        self.temporary.cleanup()

    def _cut(self, destination):
        from .repair_planning import _inspection_cut
        # SHM is a derived WAL index, rebuilt only in the private copy. Other
        # legitimate readers may touch it or create an empty WAL concurrently;
        # neither carries committed state. Pin DB and nonempty WAL exactly.
        database, wal = _inspection_cut(self.database, destination, observe_shm=False)
        return database, wal if wal is not None and wal[0][3] else None

    def check(self):
        """Recheck live evidence using copies; never initialize the original."""
        from .repair_planning import _inspection_state
        try:
            safe_directory(self.directory)
            with TemporaryDirectory(prefix="kotodama-learning-current-") as area:
                if self._cut(Path(area)) != self.cut:
                    # Reviews/decisions share this DB under their own CAS. A
                    # physical change may be only that mutable learning store
                    # or a checkpoint of identical execution evidence.
                    current = _inspection_state(Path(area) / self.database.name, self.owner, self.clock,
                        dependency=self.dependency, legacy_optional=self.legacy)
                    require(self._evidence_cut(current) == self.core_cut, "FINALIZATION_STATE_CHANGED")
        except (OSError, sqlite3.Error) as exc:
            raise SwarmError("REUSE_ORIGIN_STATE", "saved origin state is unavailable") from exc
        self._inputs()

    def _evidence_cut(self, state):
        limits = {"runs": 1, "jobs": 8, "attempts": 8, "run_extensions": 1,
                  "run_finalizations": 1, "run_cancellations": 1}
        if self.dependency:
            limits["run_dependency_stages"] = 1
        run_id = "task-run-" + digest([self.payload["task_id"], self.payload["revision"]])[:32]
        result = {}
        # Only the private copy is connected. Include column names and raw
        # persisted values, not merely interpreted scheduler projections.
        with closing(sqlite3.connect(Path(state.db_path).as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * 1024 * 1024)
            for table, limit in limits.items():
                rows = db.execute("SELECT * FROM " + table + " WHERE run_id=? ORDER BY rowid", (run_id,)).fetchmany(limit + 1)
                require(len(rows) <= limit and (table != "runs" or len(rows) == 1), "REUSE_ORIGIN_STATE")
                result[table] = [dict(row) for row in rows]
        return digest(result)

    def _inputs(self):
        try:
            require(read_json(self.directory / "receipt.json", with_digest=True)[1] == self.anchor,
                    "REUSE_ORIGIN_ANCHOR_MISMATCH")
            artifacts = self.receipt["artifact_sha256"]
            require(isinstance(artifacts, dict) and len(artifacts) <= 32, "RUN_RECEIPT_INVALID")
            remaining = 2 * 1024 * 1024
            for name, expected in artifacts.items():
                require(isinstance(name, str) and Path(name).name == name and name.endswith(".json"),
                        "RUN_RECEIPT_INVALID")
                raw = read_bytes(self.directory / name, remaining)
                remaining -= len(raw)
                require(hashlib.sha256(raw).hexdigest() == expected,
                        "RUN_ARTIFACT_CHANGED")
            require(hashlib.sha256(read_bytes(self.input_path, 256 * 1024)).hexdigest() == self.input_sha,
                    "REUSE_ORIGIN_ARTIFACT_CHANGED")
            require(self.owner.read_task(self.payload["task_id"]) == self.binding, "STALE_BINDING")
            require(self.owner.storage()["root"] == self.directory.parent, "RUN_STORAGE_CHANGED")
            require(read_json(self.owner.path, 1024 * 1024, with_digest=True)[1] == self.owner_sha,
                    "OWNER_INPUT_CHANGED")
        except OSError as exc:
            raise SwarmError("REUSE_ORIGIN_STATE", "saved origin state is unavailable") from exc

    def current(self):
        if self.executor is not None:
            self.executor.current(after_policy=self.check)
        else:
            self.check()


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
