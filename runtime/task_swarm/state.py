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

    def _run_owner(self, run: sqlite3.Row, now: float) -> dict[str, Any]:
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
        self._closed(plan, _PLAN_KEYS, "plan")
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
        review_count = sum(job["kind"] == "review" for job in jobs)
        reserve = protocol.integer(budget.get("verifier_reserve", min(attempt_budget, review_count)),
                                   "verifier reserve", minimum=0, maximum=1_000)
        if reserve > attempt_budget or (review_count and attempt_budget and reserve < 1):
            raise protocol.SwarmError("INVALID_PLAN", "review attempts require a reserve within the total budget")
        return {
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
        used = conn.execute("""SELECT COUNT(*) FROM attempts a JOIN jobs j
            ON a.run_id=j.run_id AND a.job_id=j.job_id WHERE a.run_id=? AND j.kind='work'""",
            (run["run_id"],)).fetchone()[0]
        return max(0, int(run["attempt_budget"]) - reserve - used), reserve

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
    def _exclusive_conflict(
        conn: sqlite3.Connection,
        run_id: str,
        keys: list[str],
    ) -> bool:
        if not keys:
            return False
        leases = conn.execute(
            "SELECT job_id FROM jobs WHERE run_id = ? AND state = 'leased'", (run_id,)
        ).fetchall()
        for lease in leases:
            other = conn.execute(
                "SELECT exclusive_keys_json FROM jobs WHERE run_id = ? AND job_id = ?",
                (run_id, lease["job_id"]),
            ).fetchone()
            if other is None:
                continue
            other_keys = set(SwarmState._decode_list(other["exclusive_keys_json"], "exclusive keys"))
            if other_keys.intersection(keys):
                return True
        return False

    def claim(
        self,
        run_id: str,
        worker_ref: str,
        lease_seconds: float = 300,
    ) -> dict[str, Any] | None:
        run_id = protocol.ref(run_id, "run id")
        worker_ref = self._validate_worker(worker_ref)
        lease_seconds = self._validate_lease(lease_seconds)
        now = self._now()

        # Owner binding validation is performed before entering the write
        # transaction so an unavailable owner cannot consume an attempt.
        conn = self._transaction()
        ok = False
        try:
            run = self._get_run(conn, run_id)
            self._run_owner(run, now)
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
            for job in sorted(jobs.values(), key=lambda item: str(item["job_id"])):
                if job["state"] != "pending":
                    continue
                if job["kind"] == "work" and work_remaining == 0:
                    continue
                if not self._dependencies_ready(job, jobs):
                    continue
                if not self._reviewer_is_independent(conn, run_id, job, worker_ref):
                    continue
                keys = self._decode_list(job["exclusive_keys_json"], "exclusive keys")
                if self._exclusive_conflict(conn, run_id, keys):
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

    def _current_attempt(self, conn: sqlite3.Connection, token: str, now: float) -> tuple[sqlite3.Row, sqlite3.Row]:
        attempt = self._attempt_for_token(conn, token)
        if attempt["state"] != "leased":
            raise protocol.SwarmError("STALE_ATTEMPT", "attempt token is no longer current")
        run = self._get_run(conn, str(attempt["run_id"]))
        self._run_owner(run, now)
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
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            attempt = self._attempt_for_token(conn, token)
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
            run = self._get_run(conn, str(attempt["run_id"]))
            self._run_owner(run, now)
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
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            attempt, run = self._current_attempt(conn, token, now)
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
    ) -> dict[str, Any]:
        run_id = protocol.ref(run_id, "run id")
        job_id = protocol.ref(job_id, "job id")
        result_digest = protocol.digest_ref(result_digest, "result digest")
        verification_ref = protocol.ref(verification_ref, "verification reference")
        owner_ref = protocol.ref(owner_ref, "owner reference")
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            run = self._get_run(conn, run_id)
            owner = self._run_owner(run, now)
            if owner_ref != owner["owner_ref"]:
                raise protocol.SwarmError("WRONG_OWNER", "acceptance caller is not the current owner")
            job = conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? AND job_id = ?", (run_id, job_id)
            ).fetchone()
            if job is None:
                raise protocol.SwarmError("UNKNOWN_JOB", "job does not exist")
            if job["state"] == "accepted":
                if job["accepted_digest"] != result_digest or job["verification_ref"] != verification_ref:
                    raise protocol.SwarmError("RESULT_MISMATCH", "job is already accepted with another result")
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
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            attempt, run = self._current_attempt(conn, token, now)
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
            rows = conn.execute(
                "SELECT * FROM attempts WHERE run_id = ? AND state = 'leased' AND lease_until <= ?",
                (run_id, now),
            ).fetchall()
            self._get_run(conn, run_id)
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
    def _attempts_for_job(conn: sqlite3.Connection, run_id: str, job_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? AND job_id = ? ORDER BY attempt ASC",
            (run_id, job_id),
        ).fetchall()
        return [SwarmState._attempt_public(row) for row in rows]

    @staticmethod
    def _claimable_for_snapshot(
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
                return True
        return False

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run_id = protocol.ref(run_id, "run id")
        now = self._now()
        conn = self._transaction()
        ok = False
        try:
            run = self._get_run(conn, run_id)
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
            for job_id, row in sorted(jobs.items()):
                public = self._job_public(row)
                attempts = self._attempts_for_job(conn, run_id, job_id)
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
            if counts["reported"] and not claimable and counts["running"] == 0:
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
            ok = True
            return result
        finally:
            self._finish(conn, ok)


__all__ = ["SwarmState"]
