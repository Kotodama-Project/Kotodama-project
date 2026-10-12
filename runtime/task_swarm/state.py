"""Durable, owner-bound scheduler state for a local Task swarm.

The scheduler is deliberately an execution ledger rather than a Task store.  It
keeps immutable run plans and an append-only attempt history in SQLite, while
the owner callback remains the source of the current Task binding.  Worker
reports are candidates; only the explicit owner ``accept`` transition makes a
job accepted.
"""
from __future__ import annotations

import copy
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from . import protocol


_PLAN_KEYS = {"run_id", "task_id", "binding_digest", "budget", "jobs"}
_BUDGET_KEYS = {"attempt_budget", "concurrency", "deadline"}
_JOB_KEYS = {
    "job_id",
    "kind",
    "dependencies",
    "exclusive_keys",
    "payload_ref",
    "payload_digest",
}
_OUTCOMES = {"candidate", "needs_data", "identity_conflict"}
_CANCELLATION_KEYS = {"version", "run_id", "binding_digest", "initial_execution_plan_digest",
                      "owner_ref", "requested_at"}
_LEASE_MAX = 86_400.0
_PER_JOB_LIMIT_MAX = 1_000


class SwarmState:
    """Persist and schedule one bounded swarm run.

    ``binding_reader`` is intentionally the only owner integration point.  It
    receives a Task id and must return the protocol Task fields.  This class
    never inserts or updates a Task record and does not import transport or any
    model/backend implementation.
    """

    def __init__(
        self,
        db_path: str | Path,
        binding_reader: Callable[[str], Mapping[str, Any]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(binding_reader):
            raise protocol.SwarmError("INVALID_BINDING_READER", "binding_reader must be callable")
        if not callable(clock):
            raise protocol.SwarmError("INVALID_CLOCK", "clock must be callable")
        self.db_path = str(db_path)
        self.binding_reader = binding_reader
        self.clock = clock
        # A private shared-memory URI keeps ``:memory:`` useful for a single
        # SwarmState instance while still opening a fresh SQLite connection
        # for every operation.  The anchor is never inherited by workers.
        self._memory_uri: str | None = None
        self._memory_anchor: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._memory_uri = f"file:task-swarm-{id(self)}?mode=memory&cache=shared"
            self._memory_anchor = sqlite3.connect(self._memory_uri, uri=True, timeout=5.0)
            self._memory_anchor.execute("PRAGMA busy_timeout=5000")
        if self.db_path != ":memory:":
            parent = Path(self.db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # ------------------------------------------------------------------
    # SQLite lifecycle
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        target = self._memory_uri or self.db_path
        conn = sqlite3.connect(
            target,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
            uri=self._memory_uri is not None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            binding_digest TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            attempt_budget INTEGER NOT NULL,
            concurrency INTEGER NOT NULL,
            deadline REAL NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            run_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            dependencies_json TEXT NOT NULL,
            exclusive_keys_json TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            accepted_digest TEXT,
            verification_ref TEXT,
            accepted_owner_ref TEXT,
            accepted_at REAL,
            PRIMARY KEY (run_id, job_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS attempts (
            token TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            epoch INTEGER NOT NULL,
            worker_ref TEXT NOT NULL,
            state TEXT NOT NULL,
            lease_until REAL NOT NULL,
            identity_json TEXT,
            result_ref TEXT,
            result_digest TEXT,
            outcome TEXT,
            runtime_receipt_ref TEXT,
            reason TEXT,
            retryable INTEGER,
            per_job_limit INTEGER,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (run_id, job_id, attempt),
            FOREIGN KEY (run_id, job_id) REFERENCES jobs(run_id, job_id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS attempts_run_job ON attempts(run_id, job_id, attempt);
        CREATE INDEX IF NOT EXISTS attempts_running ON attempts(run_id, state);
        CREATE INDEX IF NOT EXISTS jobs_leased ON jobs(run_id, exclusive_keys_json)
            WHERE state = 'leased';
        CREATE TABLE IF NOT EXISTS run_extensions (
            run_id TEXT PRIMARY KEY,
            extension_json TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS run_dependency_stages (
            run_id TEXT PRIMARY KEY,
            stage_json TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS run_finalizations (
            run_id TEXT PRIMARY KEY,
            checkpoint_json TEXT NOT NULL,
            progress_json TEXT NOT NULL,
            receipt_json TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS run_cancellations (
            run_id TEXT PRIMARY KEY,
            cancellation_json TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        );
        """
        for retry in range(6):
            conn: sqlite3.Connection | None = None
            try:
                conn = self._connect()
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("BEGIN IMMEDIATE")
                conn.executescript(schema)
                conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if conn is not None:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise protocol.SwarmError("STATE_INIT_FAILED", "unable to initialize scheduler state") from exc
                if retry == 5:
                    raise protocol.SwarmError("STATE_BUSY", "scheduler state remained locked") from exc
                time.sleep(0.05 * (retry + 1))
            except sqlite3.Error as exc:
                if conn is not None:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                raise protocol.SwarmError("STATE_INIT_FAILED", "unable to initialize scheduler state") from exc
            finally:
                if conn is not None:
                    conn.close()

    def _transaction(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            return conn
        except sqlite3.OperationalError as exc:
            conn.close()
            raise protocol.SwarmError("STATE_BUSY", "scheduler state is busy") from exc
        except sqlite3.Error as exc:
            conn.close()
            raise protocol.SwarmError("STATE_READ_FAILED", "unable to open scheduler transaction") from exc

    @staticmethod
    def _finish(conn: sqlite3.Connection, ok: bool) -> None:
        try:
            if ok:
                conn.commit()
            else:
                conn.rollback()
        finally:
            conn.close()

    def _now(self) -> float:
        try:
            value = self.clock()
        except Exception as exc:  # an unavailable host clock is fail-closed
            raise protocol.SwarmError("INVALID_CLOCK", "host clock is unavailable") from exc
        return protocol.finite(value, "host clock")

    # ------------------------------------------------------------------
    # Owner and plan validation
    # ------------------------------------------------------------------
    def _owner_binding(self, task_id: str, now: float) -> dict[str, Any]:
        try:
            supplied = self.binding_reader(task_id)
        except protocol.SwarmError:
            raise
        except Exception as exc:
            raise protocol.SwarmError("BINDING_UNAVAILABLE", "owner binding is unavailable") from exc
        try:
            binding = protocol.validate_binding(supplied, now=now)
        except protocol.SwarmError:
            raise
        except Exception as exc:
            raise protocol.SwarmError("BINDING_UNAVAILABLE", "owner binding is invalid") from exc
        if binding["task_id"] != task_id:
            raise protocol.SwarmError("WRONG_TASK", "owner binding belongs to another Task")
        return binding

    def _prefetch_owner(self, now: float, *, run_id: str | None = None, token: str | None = None) -> tuple[str, dict[str, Any]] | None:
        """Read the owner binding before taking the write lock.

        The owner adapter may be slow (it re-reads and hashes pinned sources),
        so it must not run under BEGIN IMMEDIATE, where it would block every
        other process's scheduler writes.  Inside the lock only the cheap
        expiry re-check and digest comparison remain.
        """
        conn = self._connect()
        try:
            if token is not None:
                row = conn.execute(
                    "SELECT runs.task_id AS task_id FROM attempts JOIN runs ON runs.run_id = attempts.run_id WHERE attempts.token = ?",
                    (token,),
                ).fetchone()
            else:
                row = conn.execute("SELECT task_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        except sqlite3.Error as exc:
            raise protocol.SwarmError("STATE_READ_FAILED", "unable to read scheduler state") from exc
        finally:
            conn.close()
        if row is None:
            return None  # the locked path reports the usual unknown run/token error
        task_id = str(row["task_id"])
        return task_id, self._owner_binding(task_id, now)

    def _run_owner(self, run: sqlite3.Row, now: float, prefetched: tuple[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        if prefetched is not None and prefetched[0] == str(run["task_id"]):
            binding = protocol.validate_binding(prefetched[1], now=now)
        else:
            binding = self._owner_binding(str(run["task_id"]), now)
        if protocol.digest(binding) != run["binding_digest"]:
            raise protocol.SwarmError("STALE_BINDING", "owner binding no longer matches the run")
        return binding

    @staticmethod
    def _closed(value: Mapping[str, Any], keys: set[str], name: str) -> None:
        if not isinstance(value, Mapping) or set(value) != keys:
            raise protocol.SwarmError("INVALID_PLAN", f"{name} has an unexpected shape")

    def _normalize_plan(
        self,
        plan: Mapping[str, Any],
        now: float,
        owner: Mapping[str, Any],
    ) -> dict[str, Any]:
        from .dependency_contract import EXECUTION_FIELDS, execution_version
        execution = execution_version(plan)
        self._closed(plan, _PLAN_KEYS | (EXECUTION_FIELDS if execution else set()), "plan")
        run_id = protocol.ref(plan["run_id"], "run id")
        task_id = protocol.ref(plan["task_id"], "task id")
        if task_id != owner["task_id"]:
            raise protocol.SwarmError("WRONG_TASK", "plan Task does not match owner binding")
        binding_digest = protocol.digest_ref(plan["binding_digest"], "binding digest")
        expected_binding = protocol.digest(owner)
        if binding_digest != expected_binding:
            raise protocol.SwarmError("BINDING_MISMATCH", "plan binding digest does not match owner binding")

        budget = plan["budget"]
        self._closed(budget, _BUDGET_KEYS | ({"verifier_reserve"} if "verifier_reserve" in budget else set()), "budget")
        # A zero-attempt plan is useful for a persisted, owner-resume-only
        # run (and is distinct from a malformed negative budget).
        attempt_budget = protocol.integer(budget["attempt_budget"], "attempt budget", minimum=0, maximum=1_000)
        concurrency = protocol.integer(budget["concurrency"], "concurrency", maximum=40)
        deadline = protocol.timestamp(budget["deadline"])
        if deadline > float(owner["expires_at"]):
            raise protocol.SwarmError("INVALID_DEADLINE", "run deadline exceeds owner expiry")

        raw_jobs = plan["jobs"]
        if not isinstance(raw_jobs, list) or len(raw_jobs) > 1_000:
            raise protocol.SwarmError("INVALID_PLAN", "jobs must contain at most 1000 entries")
        jobs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_job in raw_jobs:
            self._closed(raw_job, _JOB_KEYS, "job")
            job_id = protocol.ref(raw_job["job_id"], "job id")
            if job_id in seen:
                raise protocol.SwarmError("INVALID_PLAN", "job ids must be unique")
            seen.add(job_id)
            kind = raw_job["kind"]
            if kind not in ("work", "review"):
                raise protocol.SwarmError("INVALID_PLAN", "job kind must be work or review")
            dependencies = raw_job["dependencies"]
            if not isinstance(dependencies, list) or len(dependencies) > 1_000:
                raise protocol.SwarmError("INVALID_PLAN", "dependencies must be a bounded list")
            dep_ids = [protocol.ref(dep, "dependency") for dep in dependencies]
            if len(set(dep_ids)) != len(dep_ids):
                raise protocol.SwarmError("INVALID_PLAN", "duplicate dependency")
            exclusive = raw_job["exclusive_keys"]
            if not isinstance(exclusive, list) or len(exclusive) > 1_000:
                raise protocol.SwarmError("INVALID_PLAN", "exclusive keys must be a bounded list")
            keys = [protocol.ref(key, "exclusive key") for key in exclusive]
            if len(set(keys)) != len(keys):
                raise protocol.SwarmError("INVALID_PLAN", "duplicate exclusive key")
            jobs.append(
                {
                    "job_id": job_id,
                    "kind": kind,
                    "dependencies": sorted(dep_ids),
                    "exclusive_keys": sorted(keys),
                    "payload_ref": protocol.ref(raw_job["payload_ref"], "payload reference"),
                    "payload_digest": protocol.digest_ref(raw_job["payload_digest"], "payload digest"),
                }
            )
        job_ids = {job["job_id"] for job in jobs}
        for job in jobs:
            missing = [dep for dep in job["dependencies"] if dep not in job_ids]
            if missing:
                raise protocol.SwarmError("INVALID_PLAN", f"missing dependency for {job['job_id']}")
        self._reject_cycles(jobs)
        if execution:
            initial = [job for job in jobs if job["job_id"].startswith("r0-")]
            work = [job for job in initial if job["kind"] == "work"]
            first = [job for job in work if not job["dependencies"]]
            if not (4 <= attempt_budget <= 6 and len(initial) == 4 and len(work) == 2 and len(first) == 1):
                raise protocol.SwarmError("LOOP_DEPENDENCY_PLAN", "two work jobs and two reviews required")
            a = first[0]["job_id"]
            b = next(job for job in work if job["job_id"] != a)
            reviews = {job["job_id"]: job for job in initial if job["kind"] == "review"}
            if (b["dependencies"] != [a] or set(reviews) != {"r0-prerequisite", "r0-critic"}
                    or reviews["r0-prerequisite"]["dependencies"] != [a]
                    or set(reviews["r0-critic"]["dependencies"]) != {a, b["job_id"]}):
                raise protocol.SwarmError("LOOP_DEPENDENCY_PLAN", "invalid prerequisite topology")
        review_count = sum(job["kind"] == "review" for job in jobs)
        reserve = protocol.integer(budget.get("verifier_reserve", min(attempt_budget, review_count)),
                                   "verifier reserve", minimum=0, maximum=1_000)
        if reserve > attempt_budget or (review_count and attempt_budget and reserve < 1):
            raise protocol.SwarmError("INVALID_PLAN", "review attempts require a reserve within the total budget")
        return {
            **({key: plan[key] for key in EXECUTION_FIELDS} if execution else {}),
            "run_id": run_id,
            "task_id": task_id,
            "binding_digest": binding_digest,
            "budget": {
                "attempt_budget": attempt_budget,
                "concurrency": concurrency,
                "deadline": deadline,
                "verifier_reserve": reserve,
            },
            "jobs": jobs,
        }

    @staticmethod
    def _reject_cycles(jobs: list[dict[str, Any]]) -> None:
        graph = {job["job_id"]: set(job["dependencies"]) for job in jobs}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise protocol.SwarmError("INVALID_PLAN", "job dependencies contain a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    # ------------------------------------------------------------------
    # Run creation and row helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _plan_from_run(run: sqlite3.Row) -> dict[str, Any]:
        try:
            plan = json.loads(run["plan_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise protocol.SwarmError("CORRUPT_STATE", "stored run plan is not JSON") from exc
        if not isinstance(plan, dict):
            raise protocol.SwarmError("CORRUPT_STATE", "stored run plan is not an object")
        return plan

    @staticmethod
    def _receipt_from_run(run: sqlite3.Row) -> dict[str, Any]:
        plan = SwarmState._plan_from_run(run)
        return copy.deepcopy(plan)

    @staticmethod
    def _get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise protocol.SwarmError("UNKNOWN_RUN", "run does not exist")
        return row

    @staticmethod
    def _cancellation_record(conn: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any] | None:
        row = conn.execute("SELECT cancellation_json FROM run_cancellations WHERE run_id = ?",
                           (run["run_id"],)).fetchone()
        if row is None:
            return None
        try:
            raw = row["cancellation_json"]
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
                raise ValueError("cancellation record exceeds its bound")
            record = json.loads(raw)
            if (not isinstance(record, dict) or set(record) != _CANCELLATION_KEYS
                    or type(record["version"]) is not int or record["version"] != 1
                    or record["run_id"] != run["run_id"]
                    or record["binding_digest"] != run["binding_digest"]
                    or record["initial_execution_plan_digest"] != protocol.digest(SwarmState._plan_from_run(run))
                    or type(record["requested_at"]) not in (int, float)):
                raise ValueError("cancellation record does not match its run")
            protocol.ref(record["owner_ref"], "cancellation owner")
            protocol.finite(record["requested_at"], "cancellation time")
        except (ValueError, TypeError, KeyError, OverflowError, protocol.SwarmError) as exc:
            raise protocol.SwarmError("CORRUPT_STATE", "stored cancellation is invalid") from exc
        return record

    @staticmethod
    def _require_not_cancelled(conn: sqlite3.Connection, run: sqlite3.Row) -> None:
        if SwarmState._cancellation_record(conn, run) is not None:
            raise protocol.SwarmError("RUN_CANCELLED", "run was durably cancelled")

    def cancellation(self, run_id: str) -> dict[str, Any] | None:
        """Read a bounded cancellation record without granting execution.

        Status remains readable after owner expiry. Execution paths must still
        perform their current owner, source and deadline checks.
        """
        run_id = protocol.ref(run_id, "run id")
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            return self._cancellation_record(conn, self._get_run(conn, run_id))
        finally:
            conn.close()

    def _record_cancellation(self, run_id: str, *, expected_binding_digest: str,
                             expected_initial_execution_plan_digest: str,
                             owner_ref: str) -> dict[str, Any]:
        """Internal database step, NOT a public cancellation acknowledgement.

        The owner adapter must hold the shared finalization OS lock, recheck
        current input/source and the absence of a published receipt, then call
        this method. Only that adapter may acknowledge cancellation; this
        database-only helper cannot serialize the filesystem publication cut.
        """
        run_id = protocol.ref(run_id, "run id")
        expected_binding_digest = protocol.digest_ref(expected_binding_digest, "binding digest")
        expected_initial_execution_plan_digest = protocol.digest_ref(
            expected_initial_execution_plan_digest, "initial execution plan digest")
        owner_ref = protocol.ref(owner_ref, "cancellation owner")
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn, ok = self._transaction(), False
        try:
            now = self._now()
            run = self._get_run(conn, run_id)
            owner = self._run_owner(run, now, prefetched)
            if owner_ref != owner["owner_ref"]:
                raise protocol.SwarmError("WRONG_OWNER", "cancellation caller is not the current owner")
            if (expected_binding_digest != run["binding_digest"]
                    or expected_initial_execution_plan_digest != protocol.digest(self._plan_from_run(run))):
                raise protocol.SwarmError("CANCELLATION_CONFLICT", "cancellation does not match the existing run")
            previous = self._cancellation_record(conn, run)
            if previous is not None:
                if previous["owner_ref"] != owner_ref:
                    raise protocol.SwarmError("CANCELLATION_CONFLICT", "cancellation owner cannot change")
                ok = True
                return previous
            if now >= float(run["deadline"]):
                raise protocol.SwarmError("DEADLINE_EXPIRED", "incomplete run has expired")
            record = {"version": 1, "run_id": run_id, "binding_digest": expected_binding_digest,
                      "initial_execution_plan_digest": expected_initial_execution_plan_digest,
                      "owner_ref": owner_ref, "requested_at": now}
            conn.execute("INSERT INTO run_cancellations(run_id,cancellation_json) VALUES (?,?)",
                         (run_id, protocol.canonical(record)))
            ok = True
            return record
        except sqlite3.Error as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to persist cancellation") from exc
        finally:
            self._finish(conn, ok)

    @staticmethod
    def _decode_list(raw: Any, name: str) -> list[str]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise protocol.SwarmError("CORRUPT_STATE", f"stored {name} is not JSON") from exc
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise protocol.SwarmError("CORRUPT_STATE", f"stored {name} is invalid")
        return value

    @staticmethod
    def _job_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "kind": row["kind"],
            "dependencies": SwarmState._decode_list(row["dependencies_json"], "dependencies"),
            "exclusive_keys": SwarmState._decode_list(row["exclusive_keys_json"], "exclusive keys"),
            "payload_ref": row["payload_ref"],
            "payload_digest": row["payload_digest"],
            "state": row["state"],
            "status": row["state"],
            "reason": row["reason"],
            "accepted_digest": row["accepted_digest"],
            "verification_ref": row["verification_ref"],
            "accepted_owner_ref": row["accepted_owner_ref"],
            "accepted_at": row["accepted_at"],
        }

    @staticmethod
    def _attempt_public(row: sqlite3.Row) -> dict[str, Any]:
        identity = None
        if row["identity_json"] is not None:
            try:
                identity = json.loads(row["identity_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise protocol.SwarmError("CORRUPT_STATE", "stored attempt identity is not JSON") from exc
        return {
            "token": row["token"],
            "run_id": row["run_id"],
            "job_id": row["job_id"],
            "attempt": row["attempt"],
            "epoch": row["epoch"],
            "worker_ref": row["worker_ref"],
            "state": row["state"],
            "lease_until": row["lease_until"],
            "identity": identity,
            "result_ref": row["result_ref"],
            "result_digest": row["result_digest"],
            "outcome": row["outcome"],
            "runtime_receipt_ref": row["runtime_receipt_ref"],
            "reason": row["reason"],
            "retryable": bool(row["retryable"]) if row["retryable"] is not None else None,
            "per_job_limit": row["per_job_limit"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def dependency_stage(self, run_id):
        from .dependency_state import read_stage
        return read_stage(self, run_id)

    def commit_dependency_stage(self, run_id, stage, *, expected_state_digest, cancel_event=None):
        from .dependency_state import commit_stage
        return commit_stage(self, run_id, stage, expected_state_digest, cancel_event)

    def create_run(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        now = self._now()
        # Validate the shape enough to obtain the owner Task id before calling
        # the owner.  The complete closed-plan validation follows below.
        if not isinstance(plan, Mapping) or "task_id" not in plan:
            raise protocol.SwarmError("INVALID_PLAN", "plan must include task_id")
        task_id = protocol.ref(plan["task_id"], "task id")
        owner = self._owner_binding(task_id, now)
        normalized = self._normalize_plan(plan, now, owner)
        plan_json = protocol.canonical(normalized)

        conn = self._transaction()
        ok = False
        try:
            existing = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (normalized["run_id"],)
            ).fetchone()
            if existing is not None:
                self._require_not_cancelled(conn, existing)
                if existing["plan_json"] != plan_json:
                    raise protocol.SwarmError("RUN_IMMUTABLE", "run id is already bound to another plan")
                ok = True
                return self._receipt_from_run(existing)
            conn.execute(
                """INSERT INTO runs
                   (run_id, task_id, binding_digest, plan_json, attempt_budget,
                    concurrency, deadline, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    normalized["run_id"],
                    normalized["task_id"],
                    normalized["binding_digest"],
                    plan_json,
                    normalized["budget"]["attempt_budget"],
                    normalized["budget"]["concurrency"],
                    normalized["budget"]["deadline"],
                    now,
                ),
            )
            for job in normalized["jobs"]:
                conn.execute(
                    """INSERT INTO jobs
                       (run_id, job_id, kind, dependencies_json, exclusive_keys_json,
                        payload_ref, payload_digest)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        normalized["run_id"],
                        job["job_id"],
                        job["kind"],
                        protocol.canonical(job["dependencies"]),
                        protocol.canonical(job["exclusive_keys"]),
                        job["payload_ref"],
                        job["payload_digest"],
                    ),
                )
            ok = True
            return copy.deepcopy(normalized)
        except sqlite3.IntegrityError as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to persist run") from exc
        except sqlite3.Error as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to persist run") from exc
        finally:
            self._finish(conn, ok)

    def extend_run(self, run_id: str, extension: Mapping[str, Any]) -> dict[str, Any]:
        """Append one owner-bound repair frontier without renewing its budget.

        The coordinator validates the critic's artifact before this CAS. The
        initial plan stays immutable; extension and new jobs commit together.
        This is execution history in the same database, never another Task.
        """
        run_id = protocol.ref(run_id, "run id")
        self._closed(extension, {"round", "initial_plan_digest", "critic_job_id",
                                 "critic_result_digest", "proposal_digest", "jobs"}, "extension")
        if type(extension["round"]) is not int or extension["round"] != 1:
            raise protocol.SwarmError("ROUND_LIMIT", "only one corrective round is admitted")
        for key in ("initial_plan_digest", "critic_result_digest", "proposal_digest"):
            protocol.digest_ref(extension[key], key)
        protocol.ref(extension["critic_job_id"], "critic job")
        if not isinstance(extension["jobs"], list) or not 2 <= len(extension["jobs"]) <= 4:
            raise protocol.SwarmError("INVALID_PLAN", "repair needs one to three work jobs and one critic")
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn, ok = self._transaction(), False
        try:
            now = self._now()
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            owner = self._run_owner(run, now, prefetched)
            initial = self._plan_from_run(run)
            if protocol.digest(initial) != extension["initial_plan_digest"]:
                raise protocol.SwarmError("ROUND_CONFLICT", "initial plan changed")
            combined = dict(initial, jobs=initial["jobs"] + extension["jobs"])
            normalized = self._normalize_plan(combined, now, owner)
            new_jobs = normalized["jobs"][len(initial["jobs"]):]
            new_work = [job for job in new_jobs if job["kind"] == "work"]
            new_reviews = [job for job in new_jobs if job["kind"] == "review"]
            previous_work = {job["job_id"] for job in initial["jobs"] if job["kind"] == "work"}
            dependency = initial.get("execution_contract_version") == 3
            stage = None
            if dependency:
                from .dependency_state import stage_row
                stage = stage_row(self, conn, run)
                if (stage is None or stage["status"] != "released" or len(new_work) != 1
                        or new_work[0]["job_id"] != "r1-repair-" + stage["certificate"]["b_job_id"][3:]):
                    raise protocol.SwarmError("LOOP_RELEASE_INVALID", "repair needs one released prerequisite")
            invalid_dependencies = (any(job["dependencies"] != [stage["certificate"]["a_job_id"]] for job in new_work)
                                    if dependency else any(job["dependencies"] for job in new_work))
            if (not new_work or len(new_reviews) != 1 or invalid_dependencies
                    or set(new_reviews[0]["dependencies"]) != previous_work | {job["job_id"] for job in new_work}):
                raise protocol.SwarmError("INVALID_PLAN", "repair requires work and one independent critic")
            # The persisted manifest describes the same normalized rows that
            # will be scheduled. Equivalent dependency/key ordering is an
            # idempotent replay, including after the round has finished.
            encoded = protocol.canonical(dict(extension, jobs=new_jobs))
            previous = conn.execute("SELECT extension_json FROM run_extensions WHERE run_id=?", (run_id,)).fetchone()
            if previous is not None:
                if previous[0] != encoded:
                    raise protocol.SwarmError("ROUND_CONFLICT", "repair round is already bound")
                ok = True
                return json.loads(previous[0])
            if conn.execute("SELECT 1 FROM run_finalizations WHERE run_id=?", (run_id,)).fetchone():
                raise protocol.SwarmError("FINALIZATION_SEALED", "terminal run cannot admit another round")
            if now >= float(run["deadline"]):
                raise protocol.SwarmError("ROUND_BUDGET", "run deadline elapsed")
            if conn.execute("SELECT 1 FROM jobs WHERE run_id=? AND state='leased'", (run_id,)).fetchone():
                raise protocol.SwarmError("ROUND_BUSY", "outstanding work must settle first")
            if conn.execute("SELECT 1 FROM jobs WHERE run_id=? AND state NOT IN ('reported','accepted')",
                            (run_id,)).fetchone():
                raise protocol.SwarmError("ROUND_UNSETTLED", "every initial job must have a settled report")
            critic = conn.execute("SELECT * FROM jobs WHERE run_id=? AND job_id=?",
                                  (run_id, extension["critic_job_id"])).fetchone()
            proof = conn.execute("SELECT * FROM attempts WHERE run_id=? AND job_id=? ORDER BY attempt DESC LIMIT 1",
                                 (run_id, extension["critic_job_id"])).fetchone()
            if (critic is None or critic["kind"] != "review" or critic["state"] != "reported"
                    or proof is None or proof["outcome"] != "candidate"
                    or proof["result_digest"] != extension["critic_result_digest"]):
                raise protocol.SwarmError("ROUND_CRITIC_REQUIRED", "repair needs the reported critic artifact")
            previous_reviews = [job for job in initial["jobs"] if job["kind"] == "review"]
            terminal_reviews = [job for job in previous_reviews if job["job_id"] == extension["critic_job_id"]]
            if (len(previous_reviews) != (2 if dependency else 1) or len(terminal_reviews) != 1
                    or set(terminal_reviews[0]["dependencies"]) != previous_work):
                raise protocol.SwarmError("ROUND_CRITIC_REQUIRED", "repair follows the terminal initial critic")
            used = conn.execute("SELECT COUNT(*) FROM attempts WHERE run_id=?", (run_id,)).fetchone()[0]
            remaining_work, _ = self._work_remaining(conn, run)
            if (used + len(new_jobs) > int(run["attempt_budget"])
                    or sum(j["kind"] == "work" for j in new_jobs) > remaining_work):
                raise protocol.SwarmError("ROUND_BUDGET", "repair exceeds the original total budget")
            for job in new_jobs:
                conn.execute("""INSERT INTO jobs
                    (run_id,job_id,kind,dependencies_json,exclusive_keys_json,payload_ref,payload_digest)
                    VALUES (?,?,?,?,?,?,?)""", (run_id, job["job_id"], job["kind"],
                    protocol.canonical(job["dependencies"]), protocol.canonical(job["exclusive_keys"]),
                    job["payload_ref"], job["payload_digest"]))
            conn.execute("INSERT INTO run_extensions VALUES (?,?)", (run_id, encoded))
            ok = True
            return json.loads(encoded)
        except sqlite3.Error as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to append repair round") from exc
        finally:
            self._finish(conn, ok)

    def extension(self, run_id: str) -> dict[str, Any] | None:
        """Read the persisted repair manifest; this does not admit work."""
        run_id = protocol.ref(run_id, "run id")
        conn = self._connect()
        try:
            row = conn.execute("SELECT extension_json FROM run_extensions WHERE run_id=?", (run_id,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()

    @staticmethod
    def _finalization_evidence(conn, run_id):
        """Raw execution rows, including every timestamp and attempt identity.

        Unlike snapshot(), this never recomputes pending jobs. Finalization
        may only advance the expressly listed accepts in this same database.
        """
        extension = conn.execute("SELECT extension_json FROM run_extensions WHERE run_id=?", (run_id,)).fetchone()
        run = SwarmState._get_run(conn, run_id)
        extra = {}
        if json.loads(run["plan_json"]).get("execution_contract_version") == 3:
            stage = conn.execute("SELECT stage_json FROM run_dependency_stages WHERE run_id=?", (run_id,)).fetchone()
            extra["dependency_stage"] = stage[0] if stage else None
        return {**extra, "run": dict(run),
                "jobs": [dict(row) for row in conn.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY job_id", (run_id,))],
                "attempts": [dict(row) for row in conn.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY job_id,attempt", (run_id,))],
                "extension": extension[0] if extension else None}

    @staticmethod
    def _checked_finalization(conn, run_id):
        row = conn.execute("SELECT * FROM run_finalizations WHERE run_id=?", (run_id,)).fetchone()
        if row is not None and protocol.canonical(SwarmState._finalization_evidence(conn, run_id)) != row["progress_json"]:
            raise protocol.SwarmError("FINALIZATION_STATE_CHANGED", "execution changed outside finalization")
        return row

    def finalization_evidence_digest(self, run_id: str) -> str:
        """Capture a read-only CAS token; no leases or Task records change."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            return protocol.digest(self._finalization_evidence(conn, run_id))
        finally:
            conn.close()

    def prepare_finalization(self, run_id: str, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        """Freeze a fully reported terminal run, never grant new execution."""
        run_id = protocol.ref(run_id, "run id")
        if not isinstance(checkpoint, Mapping):
            raise protocol.SwarmError("FINALIZATION_INVALID", "checkpoint must be an object")
        encoded = protocol.canonical(checkpoint)
        if len(encoded.encode("utf-8")) > 262144:
            raise protocol.SwarmError("FINALIZATION_INVALID", "checkpoint is too large")
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn, ok = self._transaction(), False
        try:
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            owner = self._run_owner(run, self._now(), prefetched)
            previous = self._checked_finalization(conn, run_id)
            if previous is not None:
                if previous["checkpoint_json"] != encoded:
                    raise protocol.SwarmError("FINALIZATION_CONFLICT", "terminal checkpoint is immutable")
                ok = True
                return json.loads(encoded)
            evidence = self._finalization_evidence(conn, run_id)
            if self._now() >= float(run["deadline"]):
                raise protocol.SwarmError("DEADLINE_EXPIRED", "incomplete run has expired")
            if (checkpoint.get("run_id") != run_id or checkpoint.get("binding_digest") != run["binding_digest"]
                    or checkpoint.get("owner_ref") != owner["owner_ref"]
                    or checkpoint.get("state_digest") != protocol.digest(evidence)):
                raise protocol.SwarmError("FINALIZATION_STATE_CHANGED", "checkpoint CAS does not match this execution")
            jobs, attempts = evidence["jobs"], evidence["attempts"]
            preaccepted = {}
            if self._plan_from_run(run).get("execution_contract_version") == 3:
                from .dependency_state import stage_row, preaccepted_proof
                stage = stage_row(self, conn, run)
                if stage is None or stage["status"] != "released" or checkpoint.get("version") != 3:
                    raise protocol.SwarmError("LOOP_RELEASE_INVALID", "terminal stage is not released")
                preaccepted = preaccepted_proof(stage)
                if checkpoint.get("preaccepted") != preaccepted:
                    raise protocol.SwarmError("LOOP_RELEASE_CHANGED", "preaccepted evidence changed")
            if (not jobs or len(jobs) != len(attempts)
                    or any(job["state"] != ("accepted" if job["job_id"] in preaccepted else "reported") for job in jobs)
                    or any(a["state"] != ("accepted" if a["job_id"] in preaccepted else "reported") or a["outcome"] != "candidate" or not a["identity_json"] for a in attempts)):
                raise protocol.SwarmError("FINALIZATION_UNSETTLED", "every job needs exactly one identified report")
            accepts = checkpoint.get("accepts")
            results = {a["job_id"]: a["result_digest"] for a in attempts}
            if not isinstance(accepts, dict) or set(accepts).intersection(preaccepted) or any(results.get(job) != result for job, result in accepts.items()):
                raise protocol.SwarmError("FINALIZATION_INVALID", "accepted results must be current reports")
            protocol.ref(checkpoint.get("verification_ref"), "verification reference")
            conn.execute("INSERT INTO run_finalizations(run_id,checkpoint_json,progress_json) VALUES (?,?,?)",
                         (run_id, encoded, protocol.canonical(evidence)))
            ok = True
            return json.loads(encoded)
        finally:
            self._finish(conn, ok)

    def finalization(self, run_id: str) -> dict[str, Any] | None:
        """Read the checkpoint only if its exact durable progress still matches."""
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn, ok = self._transaction(), False
        try:
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            self._run_owner(run, self._now(), prefetched)
            row = self._checked_finalization(conn, run_id)
            ok = True
            if row is None:
                return None
            checkpoint = json.loads(row["checkpoint_json"])
            receipt = json.loads(row["receipt_json"]) if row["receipt_json"] is not None else None
            return {"checkpoint": checkpoint, "checkpoint_digest": protocol.digest(checkpoint), "receipt": receipt}
        finally:
            self._finish(conn, ok)

    def pin_final_receipt(self, run_id: str, checkpoint_digest: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Pin the complete receipt preimage before any receipt file is written."""
        encoded = protocol.canonical(receipt)
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn, ok = self._transaction(), False
        try:
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            self._run_owner(run, self._now(), prefetched)
            row = self._checked_finalization(conn, run_id)
            if row is None or protocol.digest(json.loads(row["checkpoint_json"])) != checkpoint_digest:
                raise protocol.SwarmError("FINALIZATION_CONFLICT", "checkpoint changed")
            checkpoint = json.loads(row["checkpoint_json"])
            if (self._now() >= float(run["deadline"]) or receipt.get("run_id") != run_id
                    or receipt.get("binding_digest") != run["binding_digest"]
                    or receipt.get("finalization_checkpoint_digest") != checkpoint_digest):
                raise protocol.SwarmError("FINALIZATION_CONFLICT", "receipt scope is not current")
            accepted = {r["job_id"] for r in conn.execute("SELECT job_id FROM jobs WHERE run_id=? AND state='accepted'", (run_id,))}
            if accepted != set(checkpoint["accepts"]) | set(checkpoint.get("preaccepted", {})):
                raise protocol.SwarmError("FINALIZATION_UNSETTLED", "verified acceptance is incomplete")
            if row["receipt_json"] is not None and row["receipt_json"] != encoded:
                raise protocol.SwarmError("FINALIZATION_CONFLICT", "receipt preimage is immutable")
            conn.execute("UPDATE run_finalizations SET receipt_json=? WHERE run_id=?", (encoded, run_id))
            ok = True
            return json.loads(encoded)
        finally:
            self._finish(conn, ok)

    # ------------------------------------------------------------------
    # Claims and attempt lifecycle
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_worker(worker_ref: Any) -> str:
        return protocol.ref(worker_ref, "worker reference")

    @staticmethod
    def _validate_token(token: Any) -> str:
        return protocol.ref(token, "attempt token")

    @staticmethod
    def _validate_lease(lease_seconds: Any) -> float:
        return protocol.finite(lease_seconds, "lease seconds", minimum=1.0, maximum=_LEASE_MAX)

    @staticmethod
    def _validate_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(identity, Mapping) or "kind" not in identity:
            raise protocol.SwarmError("INVALID_IDENTITY", "identity must include kind")
        kind = identity["kind"]
        if kind == "process":
            if set(identity) != {"kind", "pid", "created_at"}:
                raise protocol.SwarmError("INVALID_IDENTITY", "process identity has an unexpected shape")
            pid = protocol.integer(identity["pid"], "process id", maximum=2**53 - 1)
            created_at = protocol.finite(identity["created_at"], "process creation time")
            return {"kind": kind, "pid": pid, "created_at": created_at}
        if kind == "native":
            if set(identity) != {"kind", "thread_id"}:
                raise protocol.SwarmError("INVALID_IDENTITY", "native identity has an unexpected shape")
            return {"kind": kind, "thread_id": protocol.ref(identity["thread_id"], "thread id")}
        raise protocol.SwarmError("INVALID_IDENTITY", "identity kind must be process or native")

    @staticmethod
    def _run_values(run: sqlite3.Row) -> tuple[float, int, int]:
        return float(run["deadline"]), int(run["attempt_budget"]), int(run["concurrency"])

    @staticmethod
    def _work_remaining(conn: sqlite3.Connection, run: sqlite3.Row) -> tuple[int, int]:
        plan = json.loads(run["plan_json"])
        reserve = plan["budget"].get("verifier_reserve", min(int(run["attempt_budget"]),
            sum(job["kind"] == "review" for job in plan["jobs"])))
        used, work_used = conn.execute("""SELECT COUNT(*), COALESCE(SUM(j.kind='work'), 0)
            FROM attempts a JOIN jobs j ON a.run_id=j.run_id AND a.job_id=j.job_id
            WHERE a.run_id=?""", (run["run_id"],)).fetchone()
        pending_reviews = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE run_id=? AND kind='review' AND state='pending'",
            (run["run_id"],)).fetchone()[0]
        # Preserve the initial declared review budget, while also reserving
        # an actual remaining attempt for each pending review (including a
        # newly admitted repair critic). Completed/retried reviews have
        # already spent the global budget and cannot be ignored here.
        remaining = min(int(run["attempt_budget"]) - reserve - work_used,
                        int(run["attempt_budget"]) - used - pending_reviews)
        return max(0, remaining), reserve

    @staticmethod
    def _dependency_map(conn: sqlite3.Connection, run_id: str) -> dict[str, sqlite3.Row]:
        rows = conn.execute("SELECT * FROM jobs WHERE run_id = ?", (run_id,)).fetchall()
        return {str(row["job_id"]): row for row in rows}

    def _recompute_blocks(self, conn: sqlite3.Connection, run_id: str) -> None:
        jobs = self._dependency_map(conn, run_id)
        for job in jobs.values():
            if job["state"] != "pending":
                continue
            dependencies = self._decode_list(job["dependencies_json"], "dependencies")
            failed = [dep for dep in dependencies if jobs.get(dep) is not None and jobs[dep]["state"] in ("failed", "blocked")]
            if failed:
                reason = "failed dependency: " + ",".join(sorted(failed))
                conn.execute(
                    "UPDATE jobs SET state = 'blocked', reason = ? WHERE run_id = ? AND job_id = ? AND state = 'pending'",
                    (reason, run_id, job["job_id"]),
                )

    @staticmethod
    def _dependencies_ready(
        job: sqlite3.Row,
        jobs: dict[str, sqlite3.Row],
    ) -> bool:
        dependencies = SwarmState._decode_list(job["dependencies_json"], "dependencies")
        if job["kind"] == "work":
            return all(jobs[dep]["state"] == "accepted" for dep in dependencies)
        return all(jobs[dep]["state"] in ("reported", "accepted") for dep in dependencies)

    @staticmethod
    def _reviewer_is_independent(
        conn: sqlite3.Connection,
        run_id: str,
        job: sqlite3.Row,
        worker_ref: str,
    ) -> bool:
        if job["kind"] != "review":
            return True
        dependencies = SwarmState._decode_list(job["dependencies_json"], "dependencies")
        if not dependencies:
            return True
        marks = ",".join("?" for _ in dependencies)
        row = conn.execute(
            f"SELECT 1 FROM attempts WHERE run_id = ? AND worker_ref = ? AND job_id IN ({marks}) LIMIT 1",
            (run_id, worker_ref, *dependencies),
        ).fetchone()
        return row is None

    @staticmethod
    def _leased_exclusive_keys(conn: sqlite3.Connection) -> set[str]:
        # Keys name owner-resolved resources (a worktree, a file), so a lease in
        # any run of this state store conflicts, not only one in the same run.
        leases = conn.execute(
            "SELECT exclusive_keys_json FROM jobs WHERE state = 'leased'"
        )
        keys: set[str] = set()
        for other in leases:
            keys.update(SwarmState._decode_list(other["exclusive_keys_json"], "exclusive keys"))
        return keys

    def claim(
        self,
        run_id: str,
        worker_ref: str,
        lease_seconds: float = 300,
    ) -> dict[str, Any] | None:
        run_id = protocol.ref(run_id, "run id")
        worker_ref = self._validate_worker(worker_ref)
        lease_seconds = self._validate_lease(lease_seconds)
        # Owner binding validation is performed before entering the write
        # transaction so an unavailable or slow owner can neither consume an
        # attempt nor hold the lock. Time is read again once the lock is held.
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn = self._transaction()
        ok = False
        try:
            now = self._now()
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            self._run_owner(run, now, prefetched)
            deadline, attempt_budget, concurrency = self._run_values(run)
            if now >= deadline:
                ok = True
                return None
            self._recompute_blocks(conn, run_id)
            attempts_used = int(
                conn.execute("SELECT COUNT(*) AS n FROM attempts WHERE run_id = ?", (run_id,)).fetchone()["n"]
            )
            if attempts_used >= attempt_budget:
                ok = True
                return None
            running = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE run_id = ? AND state = 'leased'", (run_id,)
                ).fetchone()["n"]
            )
            if running >= concurrency:
                ok = True
                return None

            jobs = self._dependency_map(conn, run_id)
            work_remaining, _ = self._work_remaining(conn, run)
            selected: sqlite3.Row | None = None
            leased_keys: set[str] | None = None
            for job in sorted(jobs.values(), key=lambda item: str(item["job_id"])):
                if job["state"] != "pending":
                    continue
                if job["kind"] == "work" and work_remaining == 0:
                    continue
                from .dependency_state import claim_allowed
                if not claim_allowed(self, conn, run, job, worker_ref):
                    continue
                if not self._dependencies_ready(job, jobs):
                    continue
                if not self._reviewer_is_independent(conn, run_id, job, worker_ref):
                    continue
                keys = self._decode_list(job["exclusive_keys_json"], "exclusive keys")
                if keys:
                    # One consistent set for this claim transaction, shared
                    # by every candidate rather than re-reading every lease.
                    if leased_keys is None:
                        leased_keys = self._leased_exclusive_keys(conn)
                    if leased_keys.intersection(keys):
                        continue
                selected = job
                break
            if selected is None:
                ok = True
                return None

            previous = conn.execute(
                "SELECT MAX(attempt) AS attempt, MAX(epoch) AS epoch FROM attempts WHERE run_id = ? AND job_id = ?",
                (run_id, selected["job_id"]),
            ).fetchone()
            attempt = int(previous["attempt"] or 0) + 1
            epoch = int(previous["epoch"] or 0) + 1
            token = secrets.token_urlsafe(32)
            lease_until = min(now + lease_seconds, deadline)
            conn.execute(
                """INSERT INTO attempts
                   (token, run_id, job_id, attempt, epoch, worker_ref, state,
                    lease_until, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'leased', ?, ?, ?)""",
                (token, run_id, selected["job_id"], attempt, epoch, worker_ref, lease_until, now, now),
            )
            conn.execute(
                "UPDATE jobs SET state = 'leased', reason = NULL WHERE run_id = ? AND job_id = ?",
                (run_id, selected["job_id"]),
            )
            result = {
                "run_id": run_id,
                "task_id": run["task_id"],
                "job_id": selected["job_id"],
                "token": token,
                "epoch": epoch,
                "attempt": attempt,
                "worker_ref": worker_ref,
                "kind": selected["kind"],
                "dependencies": self._decode_list(selected["dependencies_json"], "dependencies"),
                "exclusive_keys": self._decode_list(selected["exclusive_keys_json"], "exclusive keys"),
                "payload_ref": selected["payload_ref"],
                "payload_digest": selected["payload_digest"],
                "lease_until": lease_until,
                "deadline": deadline,
            }
            if json.loads(run["plan_json"]).get("execution_contract_version") == 3:
                from .dependency_state import stage_row
                stage = stage_row(self, conn, run)
                if stage and selected["job_id"] in {stage["certificate"]["b_job_id"], "r1-repair-" + stage["certificate"]["b_job_id"][3:]}:
                    result["delivered_input_digest"] = stage["actual_input_digest"] if selected["job_id"] == stage["certificate"]["b_job_id"] else selected["payload_digest"]
            ok = True
            return result
        except sqlite3.IntegrityError as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to persist claim") from exc
        except sqlite3.Error as exc:
            raise protocol.SwarmError("STATE_WRITE_FAILED", "unable to persist claim") from exc
        finally:
            self._finish(conn, ok)

    def _attempt_for_token(self, conn: sqlite3.Connection, token: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM attempts WHERE token = ?", (token,)).fetchone()
        if row is None:
            raise protocol.SwarmError("UNKNOWN_TOKEN", "attempt token does not exist")
        return row

    def _current_attempt(self, conn: sqlite3.Connection, token: str, now: float, prefetched: tuple[str, dict[str, Any]] | None = None, *, allow_expired: bool = False) -> tuple[sqlite3.Row, sqlite3.Row]:
        attempt = self._attempt_for_token(conn, token)
        if attempt["state"] != "leased":
            raise protocol.SwarmError("STALE_ATTEMPT", "attempt token is no longer current")
        run = self._get_run(conn, str(attempt["run_id"]))
        # Even expired-token cleanup must not release an unconfirmed worker's
        # permit after cancellation. fail() shares this transaction boundary.
        self._require_not_cancelled(conn, run)
        expired = now >= float(run["deadline"]) or now >= float(attempt["lease_until"])
        # Giving up an expired lease only downgrades state, so the current
        # token holder may still do it; everything else needs a live lease.
        if not (allow_expired and expired):
            self._run_owner(run, now, prefetched)
            if now >= float(run["deadline"]):
                raise protocol.SwarmError("DEADLINE_EXPIRED", "run deadline has elapsed")
            if now >= float(attempt["lease_until"]):
                raise protocol.SwarmError("LEASE_EXPIRED", "attempt lease has elapsed")
        job = conn.execute(
            "SELECT * FROM jobs WHERE run_id = ? AND job_id = ?",
            (attempt["run_id"], attempt["job_id"]),
        ).fetchone()
        if job is None or job["state"] != "leased":
            raise protocol.SwarmError("STALE_ATTEMPT", "attempt is not the current job lease")
        return attempt, run

    @staticmethod
    def _attempt_receipt(attempt: sqlite3.Row, state: str | None = None) -> dict[str, Any]:
        receipt = SwarmState._attempt_public(attempt)
        if state is not None:
            receipt["state"] = state
        return receipt

    def attach_identity(self, token: str, identity: Mapping[str, Any]) -> dict[str, Any]:
        token = self._validate_token(token)
        normalized = self._validate_identity(identity)
        prefetched = self._prefetch_owner(self._now(), token=token)
        conn = self._transaction()
        ok = False
        try:
            now = self._now()
            attempt = self._attempt_for_token(conn, token)
            run = self._get_run(conn, str(attempt["run_id"]))
            self._require_not_cancelled(conn, run)
            if attempt["state"] != "leased":
                if attempt["identity_json"] is not None:
                    try:
                        existing = json.loads(attempt["identity_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise protocol.SwarmError("CORRUPT_STATE", "stored attempt identity is not JSON") from exc
                    if existing == normalized:
                        ok = True
                        return copy.deepcopy(normalized)
                raise protocol.SwarmError("STALE_ATTEMPT", "attempt token is no longer current")
            self._run_owner(run, now, prefetched)
            if now >= float(run["deadline"]):
                raise protocol.SwarmError("DEADLINE_EXPIRED", "run deadline has elapsed")
            if now >= float(attempt["lease_until"]):
                raise protocol.SwarmError("LEASE_EXPIRED", "attempt lease has elapsed")
            if attempt["identity_json"] is not None:
                try:
                    existing = json.loads(attempt["identity_json"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise protocol.SwarmError("CORRUPT_STATE", "stored attempt identity is not JSON") from exc
                if existing != normalized:
                    raise protocol.SwarmError("IDENTITY_CONFLICT", "attempt already has another identity")
                ok = True
                return copy.deepcopy(normalized)
            conn.execute(
                "UPDATE attempts SET identity_json = ?, updated_at = ? WHERE token = ? AND state = 'leased'",
                (protocol.canonical(normalized), now, token),
            )
            ok = True
            return copy.deepcopy(normalized)
        finally:
            self._finish(conn, ok)

    def report(
        self,
        token: str,
        result_ref: str,
        result_digest: str,
        outcome: str,
        runtime_receipt_ref: str,
    ) -> dict[str, Any]:
        token = self._validate_token(token)
        result_ref = protocol.ref(result_ref, "result reference")
        result_digest = protocol.digest_ref(result_digest, "result digest")
        if outcome not in _OUTCOMES:
            raise protocol.SwarmError("INVALID_OUTCOME", "unknown worker outcome")
        runtime_receipt_ref = protocol.ref(runtime_receipt_ref, "runtime receipt reference")
        prefetched = self._prefetch_owner(self._now(), token=token)
        conn = self._transaction()
        ok = False
        try:
            now = self._now()
            attempt, run = self._current_attempt(conn, token, now, prefetched)
            conn.execute(
                """UPDATE attempts SET state = 'reported', result_ref = ?, result_digest = ?,
                   outcome = ?, runtime_receipt_ref = ?, updated_at = ?
                   WHERE token = ? AND state = 'leased'""",
                (result_ref, result_digest, outcome, runtime_receipt_ref, now, token),
            )
            conn.execute(
                "UPDATE jobs SET state = 'reported', reason = NULL WHERE run_id = ? AND job_id = ? AND state = 'leased'",
                (attempt["run_id"], attempt["job_id"]),
            )
            stored = conn.execute("SELECT * FROM attempts WHERE token = ?", (token,)).fetchone()
            ok = True
            return self._attempt_receipt(stored, "reported")
        finally:
            self._finish(conn, ok)

    def accept(
        self,
        run_id: str,
        job_id: str,
        result_digest: str,
        verification_ref: str,
        owner_ref: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if cancel_event is not None and not isinstance(cancel_event, threading.Event):
            raise protocol.SwarmError("RUN_CANCELLATION_INVALID", "cancel_event must be an Event")

        def eligible(run):
            if cancel_event is not None and cancel_event.is_set():
                raise protocol.SwarmError("RUN_CANCELLED", "run was cancelled")
            if self._now() >= float(run["deadline"]):
                raise protocol.SwarmError("DEADLINE_EXPIRED", "run deadline has elapsed")

        run_id = protocol.ref(run_id, "run id")
        job_id = protocol.ref(job_id, "job id")
        result_digest = protocol.digest_ref(result_digest, "result digest")
        verification_ref = protocol.ref(verification_ref, "verification reference")
        owner_ref = protocol.ref(owner_ref, "owner reference")
        prefetched = self._prefetch_owner(self._now(), run_id=run_id)
        conn = self._transaction()
        ok = False
        try:
            now = self._now()
            run = self._get_run(conn, run_id)
            self._require_not_cancelled(conn, run)
            eligible(run)
            owner = self._run_owner(run, now, prefetched)
            if owner_ref != owner["owner_ref"]:
                raise protocol.SwarmError("WRONG_OWNER", "acceptance caller is not the current owner")
            finalization = self._checked_finalization(conn, run_id)
            if finalization is not None:
                checkpoint = json.loads(finalization["checkpoint_json"])
                if now >= float(run["deadline"]):
                    raise protocol.SwarmError("DEADLINE_EXPIRED", "incomplete run has expired")
                if (checkpoint["accepts"].get(job_id) != result_digest
                        or checkpoint["verification_ref"] != verification_ref
                        or checkpoint["owner_ref"] != owner_ref):
                    raise protocol.SwarmError("FINALIZATION_CONFLICT", "acceptance is outside the terminal proof")
            job = conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? AND job_id = ?", (run_id, job_id)
            ).fetchone()
            if job is None:
                raise protocol.SwarmError("UNKNOWN_JOB", "job does not exist")
            if job["state"] == "accepted":
                # Replays must not grandfather an invalid pre-fix acceptance.
                accepted = conn.execute(
                    """SELECT * FROM attempts WHERE run_id = ? AND job_id = ?
                       AND state = 'accepted' AND result_digest = ?
                       ORDER BY attempt DESC LIMIT 1""",
                    (run_id, job_id, result_digest),
                ).fetchone()
                if accepted is None or accepted["outcome"] != "candidate":
                    raise protocol.SwarmError("NON_CANDIDATE_RESULT", "accepted evidence is not a candidate")
                if accepted["worker_ref"] == owner_ref:
                    raise protocol.SwarmError("IDENTITY_CONFLICT", "worker cannot accept its own report")
                if job["accepted_digest"] != result_digest or job["verification_ref"] != verification_ref:
                    raise protocol.SwarmError("RESULT_MISMATCH", "job is already accepted with another result")
                eligible(run)
                ok = True
                return {
                    "run_id": run_id,
                    "job_id": job_id,
                    "state": "accepted",
                    "result_digest": result_digest,
                    "verification_ref": verification_ref,
                    "owner_ref": owner_ref,
                }
            if job["state"] != "reported":
                raise protocol.SwarmError("RESULT_UNAVAILABLE", "job has no reported candidate")
            candidate = conn.execute(
                """SELECT * FROM attempts WHERE run_id = ? AND job_id = ?
                   AND state = 'reported' AND result_digest = ?
                   ORDER BY attempt DESC LIMIT 1""",
                (run_id, job_id, result_digest),
            ).fetchone()
            if candidate is None:
                raise protocol.SwarmError("RESULT_MISMATCH", "reported candidate digest does not match")
            if candidate["outcome"] != "candidate":
                raise protocol.SwarmError("NON_CANDIDATE_RESULT", "only candidate reports may be accepted")
            if candidate["worker_ref"] == owner_ref:
                raise protocol.SwarmError("IDENTITY_CONFLICT", "worker cannot accept its own report")
            conn.execute(
                "UPDATE attempts SET state = 'accepted', updated_at = ? WHERE token = ? AND state = 'reported'",
                (now, candidate["token"]),
            )
            conn.execute(
                """UPDATE jobs SET state = 'accepted', reason = NULL, accepted_digest = ?,
                   verification_ref = ?, accepted_owner_ref = ?, accepted_at = ?
                   WHERE run_id = ? AND job_id = ? AND state = 'reported'""",
                (result_digest, verification_ref, owner_ref, now, run_id, job_id),
            )
            if finalization is not None:
                conn.execute("UPDATE run_finalizations SET progress_json=? WHERE run_id=?",
                             (protocol.canonical(self._finalization_evidence(conn, run_id)), run_id))
            # The final eligibility observation is inside BEGIN IMMEDIATE;
            # rejection rolls back both writes. A later external Event change
            # cannot be atomic with SQLite and does not undo this acceptance.
            eligible(run)
            ok = True
            return {
                "run_id": run_id,
                "job_id": job_id,
                "state": "accepted",
                "result_digest": result_digest,
                "verification_ref": verification_ref,
                "owner_ref": owner_ref,
            }
        finally:
            self._finish(conn, ok)

    def fail(
        self,
        token: str,
        reason: str,
        retryable: bool = True,
        per_job_limit: int = 2,
    ) -> dict[str, Any]:
        token = self._validate_token(token)
        reason = protocol.ref(reason, "failure reason")
        if not isinstance(retryable, bool):
            raise protocol.SwarmError("INVALID_FAILURE", "retryable must be boolean")
        per_job_limit = protocol.integer(per_job_limit, "per-job limit", maximum=_PER_JOB_LIMIT_MAX)
        try:
            prefetched = self._prefetch_owner(self._now(), token=token)
        except protocol.SwarmError:
            prefetched = None  # an expired owner must not keep an expired lease alive
        conn = self._transaction()
        ok = False
        try:
            now = self._now()
            attempt, run = self._current_attempt(conn, token, now, prefetched, allow_expired=True)
            conn.execute(
                """UPDATE attempts SET state = 'failed', reason = ?, retryable = ?,
                   per_job_limit = ?, updated_at = ? WHERE token = ? AND state = 'leased'""",
                (reason, int(retryable), per_job_limit, now, token),
            )
            failures = int(
                conn.execute(
                    """SELECT COUNT(*) AS n FROM attempts
                       WHERE run_id = ? AND job_id = ? AND state IN ('failed', 'revoked')""",
                    (attempt["run_id"], attempt["job_id"]),
                ).fetchone()["n"]
            )
            attempts_used = int(
                conn.execute("SELECT COUNT(*) AS n FROM attempts WHERE run_id = ?", (attempt["run_id"],)).fetchone()["n"]
            )
            can_retry = retryable and failures < per_job_limit and attempts_used < int(run["attempt_budget"])
            state = "pending" if can_retry else "failed"
            terminal_reason = None if can_retry else reason
            conn.execute(
                "UPDATE jobs SET state = ?, reason = ? WHERE run_id = ? AND job_id = ? AND state = 'leased'",
                (state, terminal_reason, attempt["run_id"], attempt["job_id"]),
            )
            if state == "failed":
                self._recompute_blocks(conn, str(attempt["run_id"]))
            stored = conn.execute("SELECT * FROM attempts WHERE token = ?", (token,)).fetchone()
            ok = True
            receipt = self._attempt_receipt(stored, "failed")
            receipt.update({"job_state": state, "retryable": retryable, "failures": failures})
            return receipt
        finally:
            self._finish(conn, ok)

    # ------------------------------------------------------------------
    # Crash/dead-peer recovery
    # ------------------------------------------------------------------
    def recover(
        self,
        run_id: str,
        is_alive: Callable[[Mapping[str, Any]], Any],
    ) -> dict[str, Any]:
        run_id = protocol.ref(run_id, "run id")
        if not callable(is_alive):
            raise protocol.SwarmError("INVALID_LIVENESS_CHECK", "is_alive must be callable")
        now = self._now()
        # Read first and call the liveness adapter outside the write lock.  A
        # missing/unknown identity is deliberately never treated as dead.
        conn = self._connect()
        try:
            self._require_not_cancelled(conn, self._get_run(conn, run_id))
            rows = conn.execute(
                "SELECT * FROM attempts WHERE run_id = ? AND state = 'leased' AND lease_until <= ?",
                (run_id, now),
            ).fetchall()
            run_deadline = float(self._get_run(conn, run_id)["deadline"])
        finally:
            conn.close()
        decisions: list[tuple[str, str]] = []
        for row in rows:
            if row["identity_json"] is None:
                decisions.append((str(row["token"]), "unknown"))
                continue
            try:
                identity = json.loads(row["identity_json"])
            except (TypeError, json.JSONDecodeError):
                decisions.append((str(row["token"]), "unknown"))
                continue
            try:
                alive = is_alive(identity)
            except Exception:
                alive = None
            if alive is False:
                decisions.append((str(row["token"]), "dead"))
            elif alive is True:
                decisions.append((str(row["token"]), "alive"))
            else:
                decisions.append((str(row["token"]), "unknown"))

        revoked: list[str] = []
        alive_tokens: list[str] = []
        unknown_tokens: list[str] = []
        conn = self._transaction()
        ok = False
        try:
            self._require_not_cancelled(conn, self._get_run(conn, run_id))
            for token, decision in decisions:
                if decision == "dead":
                    changed = conn.execute(
                        """UPDATE attempts SET state = 'revoked', reason = 'dead worker',
                           retryable = 1, updated_at = ? WHERE token = ? AND state = 'leased'""",
                        (now, token),
                    ).rowcount
                    if changed:
                        row = conn.execute("SELECT run_id, job_id FROM attempts WHERE token = ?", (token,)).fetchone()
                        if row is not None:
                            conn.execute(
                                "UPDATE jobs SET state = 'pending', reason = 'dead worker lease revoked' WHERE run_id = ? AND job_id = ? AND state = 'leased'",
                                (row["run_id"], row["job_id"]),
                            )
                        revoked.append(token)
                elif decision == "alive" and now >= run_deadline:
                    # A live worker past the run deadline can never report; free
                    # its slot instead of leaving the run active forever.
                    changed = conn.execute(
                        """UPDATE attempts SET state = 'revoked', reason = 'run deadline elapsed',
                           retryable = 0, updated_at = ? WHERE token = ? AND state = 'leased'""",
                        (now, token),
                    ).rowcount
                    if changed:
                        row = conn.execute("SELECT run_id, job_id FROM attempts WHERE token = ?", (token,)).fetchone()
                        if row is not None:
                            conn.execute(
                                "UPDATE jobs SET state = 'failed', reason = 'run deadline elapsed' WHERE run_id = ? AND job_id = ? AND state = 'leased'",
                                (row["run_id"], row["job_id"]),
                            )
                        revoked.append(token)
                elif decision == "alive":
                    alive_tokens.append(token)
                else:
                    unknown_tokens.append(token)
            self._recompute_blocks(conn, run_id)
            ok = True
            return {
                "run_id": run_id,
                "revoked": revoked,
                "alive": alive_tokens,
                "unknown": unknown_tokens,
                "revoked_count": len(revoked),
            }
        finally:
            self._finish(conn, ok)

    # ------------------------------------------------------------------
    # Readback
    # ------------------------------------------------------------------
    @staticmethod
    def _attempts_by_job(conn: sqlite3.Connection, run_id: str) -> dict[str, list[dict[str, Any]]]:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY job_id, attempt ASC",
            (run_id,),
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["job_id"]), []).append(SwarmState._attempt_public(row))
        return grouped

    def _claimable_for_snapshot(
        self,
        conn: sqlite3.Connection,
        jobs: dict[str, sqlite3.Row],
        run_id: str,
        attempt_budget: int,
        concurrency: int,
        attempts_used: int,
        work_remaining: int,
    ) -> bool:
        if attempts_used >= attempt_budget:
            return False
        running = sum(1 for row in jobs.values() if row["state"] == "leased")
        if running >= concurrency:
            return False
        for job in jobs.values():
            if job["kind"] == "work" and work_remaining == 0:
                continue
            if job["state"] == "pending" and SwarmState._dependencies_ready(job, jobs):
                from .dependency_state import claim_allowed
                if not claim_allowed(self, conn, self._get_run(conn, run_id), job, None):
                    continue
                return True
        return False

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run_id = protocol.ref(run_id, "run id")
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            run = self._get_run(conn, run_id)
            cancellation = self._cancellation_record(conn, run)
            if cancellation is None:
                self._recompute_blocks(conn, run_id)
                run = self._get_run(conn, run_id)
            plan = self._plan_from_run(run)
            work_remaining, reserve = self._work_remaining(conn, run)
            jobs = self._dependency_map(conn, run_id)
            attempts_used = int(
                conn.execute("SELECT COUNT(*) AS n FROM attempts WHERE run_id = ?", (run_id,)).fetchone()["n"]
            )
            states: dict[str, dict[str, Any]] = {}
            reasons: list[str] = []
            attempts_by_job = self._attempts_by_job(conn, run_id)
            for job_id, row in sorted(jobs.items()):
                public = self._job_public(row)
                attempts = attempts_by_job.get(job_id, [])
                public["attempts"] = attempts
                public["attempt_count"] = len(attempts)
                public["current_attempt"] = attempts[-1] if attempts else None
                public["reported"] = (
                    attempts[-1]
                    if row["state"] in ("reported", "accepted") and attempts
                    else None
                )
                public["accepted"] = (
                    {
                        "result_digest": row["accepted_digest"],
                        "verification_ref": row["verification_ref"],
                        "owner_ref": row["accepted_owner_ref"],
                        "accepted_at": row["accepted_at"],
                    }
                    if row["state"] == "accepted"
                    else None
                )
                if row["reason"]:
                    reasons.append(f"{job_id}: {row['reason']}")
                elif row["state"] == "pending":
                    deps = self._decode_list(row["dependencies_json"], "dependencies")
                    waiting = [dep for dep in deps if jobs[dep]["state"] not in ("accepted", "reported")]
                    if waiting:
                        reason = "waiting for dependencies: " + ",".join(waiting)
                        public["reason"] = reason
                        reasons.append(f"{job_id}: {reason}")
                    elif now >= float(run["deadline"]):
                        reason = "run deadline elapsed"
                        public["reason"] = reason
                        reasons.append(f"{job_id}: {reason}")
                    elif attempts_used >= int(run["attempt_budget"]):
                        reason = "global attempt budget exhausted"
                        public["reason"] = reason
                        reasons.append(f"{job_id}: {reason}")
                    elif row["kind"] == "work" and work_remaining == 0:
                        reason = "work attempt budget exhausted; verifier reserve retained"
                        public["reason"] = reason
                        reasons.append(f"{job_id}: {reason}")
                states[job_id] = public

            counts = {
                "running": sum(1 for row in jobs.values() if row["state"] == "leased"),
                "reported": sum(1 for row in jobs.values() if row["state"] == "reported"),
                "accepted": sum(1 for row in jobs.values() if row["state"] == "accepted"),
                "failed": sum(1 for row in jobs.values() if row["state"] == "failed"),
                "blocked": sum(1 for row in jobs.values() if row["state"] == "blocked"),
                "pending": sum(1 for row in jobs.values() if row["state"] == "pending"),
            }
            claimable = self._claimable_for_snapshot(
                conn,
                jobs,
                run_id,
                int(run["attempt_budget"]),
                int(run["concurrency"]),
                attempts_used,
                work_remaining,
            )
            if cancellation is not None:
                run_state = "cancelled"
                reasons.append("run durably cancelled; outstanding leases are not confirmed stopped")
            elif counts["reported"] and not claimable and counts["running"] == 0:
                run_state = "waiting_owner"
            elif counts["pending"] and (
                attempts_used >= int(run["attempt_budget"]) or now >= float(run["deadline"])
                or (work_remaining == 0 and not claimable and counts["running"] == 0)
            ):
                run_state = "budget_exhausted"
            elif counts["pending"] or counts["running"]:
                run_state = "active"
            else:
                run_state = "quiescent"
            remaining = max(0, int(run["attempt_budget"]) - attempts_used)
            budget = {
                "attempt_budget": int(run["attempt_budget"]),
                "concurrency": int(run["concurrency"]),
                "deadline": float(run["deadline"]),
                "attempts_used": attempts_used,
                "remaining_attempts": remaining,
                "remaining_work_attempts": work_remaining,
                "verifier_reserve": reserve,
            }
            result = {
                "run_id": run_id,
                "task_id": run["task_id"],
                "binding_digest": run["binding_digest"],
                "plan": copy.deepcopy(plan),
                "budget": budget,
                "remaining_budget": remaining,
                "jobs": states,
                "job_states": copy.deepcopy(states),
                "jobs_list": list(copy.deepcopy(states).values()),
                "counts": counts,
                "running": counts["running"],
                "reported": counts["reported"],
                "accepted": counts["accepted"],
                "failed": counts["failed"],
                "blocked": counts["blocked"],
                "run_state": run_state,
                "reasons": reasons,
            }
            extension = conn.execute("SELECT extension_json FROM run_extensions WHERE run_id = ?", (run_id,)).fetchone()
            if extension is not None:
                result["extension"] = json.loads(extension[0])
            if plan.get("execution_contract_version") == 3:
                from .dependency_state import stage_row
                result["dependency_stage"] = stage_row(self, conn, run)
            if cancellation is not None:
                result["cancellation"] = cancellation
            ok = True
            return result
        finally:
            self._finish(conn, ok)


__all__ = ["SwarmState"]
