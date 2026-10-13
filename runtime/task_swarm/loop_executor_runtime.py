"""Current-owner and saved-process checks shared by every local loop reader.

The initial critic template binds this mode to the existing execution database.
These helpers neither dispatch children nor create authority or another ledger.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import threading

from .loop_executor import (check_current_executor_policy, derive_executor_policy,
                            executor_version, loop_schema, verify_loop_response, MAX_PROOF_BYTES)
from .owner_file import _current_read
from .protocol import SwarmError, canonical, digest, digest_ref, ref
from .task_contract import require, shape
from .task_runner import read_bytes, read_json, safe_directory


def _saved(path):
    from .closed_loop_recovery import read_artifact
    return read_artifact(path)


def select_executor_policy(payload, specification, owner_path):
    """Select the single explicit declaration in current constraint Sources."""
    from .loop_executor import _json
    from .owner_file import OwnerFile
    from .task_planning import _Sources
    sources, selected = _Sources(payload), []
    for span in payload["objective"]["constraints"]:
        text = sources.span(span)
        if not text.lstrip().startswith("{"):
            continue
        declaration = _json(text)
        if isinstance(declaration, dict) and declaration.get("kind") == "task_loop_executor":
            selected.append(span)
    require(len(selected) == 1, "LOOP_EXECUTOR_POLICY_SOURCE")
    return derive_executor_policy(payload, specification, selected[0], owner_base=str(OwnerFile(owner_path).path.parent))


def owner_binding(owner_sha, actors, critic_actor, actor_bindings):
    return {"owner_input_sha256": owner_sha, "worker_actors": list(actors), "critic_actor": critic_actor,
            "actor_binding_digests": {key: digest(value) for key, value in actor_bindings.items()}}


def validate_owner_binding(value):
    shape(value, {"owner_input_sha256", "worker_actors", "critic_actor", "actor_binding_digests"},
          "LOOP_EXECUTOR_OWNER_BINDING")
    digest_ref(value["owner_input_sha256"])
    actors = value["worker_actors"]
    require(isinstance(actors, list) and 1 <= len(actors) <= 3, "LOOP_EXECUTOR_OWNER_BINDING")
    for actor in [*actors, value["critic_actor"]]:
        ref(actor)
    require(len(set([*actors, value["critic_actor"]])) == len(actors) + 1,
            "LOOP_EXECUTOR_OWNER_BINDING")
    digests = value["actor_binding_digests"]
    require(isinstance(digests, dict) and set(digests) == {*actors, value["critic_actor"]},
            "LOOP_EXECUTOR_OWNER_BINDING")
    for sha in digests.values():
        digest_ref(sha)
    return value


class ExecutorEvidence:
    """Bounded immutable hashes from successful writers or verified readers."""
    def __init__(self, directory, maximum_jobs=8):
        require(type(maximum_jobs) is int and 1 <= maximum_jobs <= 8, "LOOP_EXECUTOR_PROOF_LIMIT")
        self.directory, self.maximum_jobs = Path(directory), maximum_jobs
        self.document_pins, self.proof_pins, self.receipt_pins, self.lock = {}, {}, {}, threading.Lock()

    def _add(self, target, pins, code):
        with self.lock:
            require(all(path not in target or target[path] == sha for path, sha in pins.items()), code)
            target.update(pins)

    def pin_artifacts(self, artifacts):
        require(isinstance(artifacts, dict) and len(artifacts) <= 32, "FINALIZATION_ARTIFACT_INVALID")
        pins = {}
        for name, sha in artifacts.items():
            require(isinstance(name, str) and Path(name).name == name and name.endswith(".json"),
                    "FINALIZATION_ARTIFACT_INVALID")
            digest_ref(sha)
            pins[self.directory/name] = sha
        self._add(self.document_pins, pins, "RUN_ARTIFACT_CHANGED")

    def pin_receipt(self, name, sha):
        require(name in {"receipt.json", ".receipt-pending.json"}, "FINALIZATION_ARTIFACT_INVALID")
        digest_ref(sha)
        self._add(self.receipt_pins, {self.directory/name: sha}, "RUN_ARTIFACT_CHANGED")

    def pin_runtime(self, runtime):
        """Call only after verify_loop_response accepted this exact packet."""
        pins = {Path(runtime["paths"][name]): sha for name, sha in runtime["receipt"]["artifact_digests"].items()}
        pins[Path(runtime["paths"]["receipt"])] = runtime["runtime_receipt_sha256"]
        pins[Path(runtime["receipt"]["runtime_receipt_path"])] = runtime["runtime_rollout_sha256"]
        self._add(self.proof_pins, pins, "RUN_RUNTIME_ARTIFACT_CHANGED")

    def check(self):
        # Digests originate in the DB-bound result/manifest and the completed
        # verifier, never in a fresh post-check snapshot. Re-read bytes only;
        # calling the semantic verifier here would recurse through current().
        with self.lock:
            documents, proofs, receipts = dict(self.document_pins), dict(self.proof_pins), dict(self.receipt_pins)
        require(len(documents) <= 32 and len(proofs) <= self.maximum_jobs*11 and len(receipts) <= 2,
                "LOOP_EXECUTOR_PROOF_LIMIT")
        for pins, limit, code in ((documents, 2*1024*1024, "RUN_ARTIFACT_CHANGED"),
                                  (receipts, 2*MAX_PROOF_BYTES, "RUN_ARTIFACT_CHANGED"),
                                  (proofs, self.maximum_jobs*MAX_PROOF_BYTES, "RUN_RUNTIME_ARTIFACT_CHANGED")):
            consumed = 0
            for path, sha in pins.items():
                try:
                    try:
                        raw = read_bytes(path, min(MAX_PROOF_BYTES, limit-consumed))
                    except FileNotFoundError:
                        # A monitor may span the finalizer's atomic rename.
                        # Only the identical pinned receipt is accepted there.
                        if path not in receipts or path.name != ".receipt-pending.json":
                            raise
                        raw = read_bytes(self.directory/"receipt.json", min(MAX_PROOF_BYTES, limit-consumed))
                except OSError as error:
                    raise SwarmError(code, "saved execution evidence is unavailable") from error
                consumed += len(raw)
                require(consumed <= limit and hashlib.sha256(raw).hexdigest() == sha, code)


class SavedExecutor:
    def __init__(self, directory, payload, plan, state, metadata=None, *, current_guard=None):
        from .owner_file import OwnerFile
        self.directory, self.payload, self.plan, self.state = Path(directory), payload, plan, state
        require(current_guard is None or callable(current_guard), "LOOP_EXECUTOR_CURRENT_GUARD")
        self.current_guard = current_guard
        self.snapshot = state.snapshot(plan["run_id"])
        require(len(self.snapshot["jobs"]) <= 8, "LOOP_EXECUTOR_PROOF_LIMIT")
        self.evidence = ExecutorEvidence(directory)
        require(canonical(self.snapshot["plan"]) == canonical(plan), "LOOP_EXECUTOR_PLAN_CHANGED")
        require(self.document("plan.json") == plan and self.document("input.json") == payload, "RUN_REPLAY_CONFLICT")
        self.template = self.document("r0-critic-template.json")
        require(executor_version(plan, self.template) == 1, "LOOP_EXECUTOR_VERSION")
        self.binding = validate_owner_binding(self.template.get("executor_owner_binding"))
        if metadata is not None:
            require(all(metadata.get(key) == value for key, value in self.binding.items()),
                    "LOOP_EXECUTOR_OWNER_BINDING")
            if "artifact_sha256" in metadata:
                self.pin_artifacts(metadata["artifact_sha256"])
        self.owner = getattr(state.binding_reader, "__self__", None)
        require(isinstance(self.owner, OwnerFile), "LOOP_EXECUTOR_OWNER_REQUIRED")
        self.policy = self.document("executor-policy.json")
        require(digest(self.policy) == self.template["executor_policy_sha256"], "LOOP_EXECUTOR_POLICY_CHANGED")
        self.specification = self.document("specification.json")
        self.expected_actors = {}
        for index in range(2):
            work = sorted(job for job, row in self.snapshot["jobs"].items()
                          if job.startswith(f"r{index}-") and row["kind"] == "work")
            require(len(work) <= len(self.binding["worker_actors"]), "LOOP_EXECUTOR_OWNER_BINDING")
            self.expected_actors.update(zip(work, self.binding["worker_actors"]))
        self.expected_actors.update((job, self.binding["critic_actor"])
            for job, row in self.snapshot["jobs"].items() if row["kind"] == "review")
        finalization = state.finalization(plan["run_id"])
        if finalization is not None and finalization["receipt"] is not None and (self.directory/"receipt.json").exists():
            raw = (canonical(finalization["receipt"])+"\n").encode("utf-8")
            self.pin_artifacts(finalization["receipt"]["artifact_sha256"])
            self.evidence.pin_receipt("receipt.json", hashlib.sha256(raw).hexdigest())
        self.current()

    def document(self, name, expected=None):
        from .closed_loop_recovery import read_artifact
        value, sha = read_artifact(self.directory/name, with_digest=True)
        canonical_sha = hashlib.sha256((canonical(value)+"\n").encode("utf-8")).hexdigest()
        require(sha == (expected or canonical_sha), "RUN_ARTIFACT_CHANGED")
        self.evidence.pin_artifacts({name: sha})
        return value

    def pin_artifacts(self, artifacts):
        self.evidence.pin_artifacts(artifacts)

    def current(self, *, after_policy=None):
        """Fence callbacks and policy I/O before the final raw owner read.

        In particular, an actor changed by the last policy check must not be
        accepted using a snapshot captured before that check. No callback or
        source read runs after the final owner digest comparison.
        """
        document = read_json(self.owner.path, 1024 * 1024)
        check_current_executor_policy(self.policy, self.payload, self.specification,
                                      owner_path=self.owner.path, owner_document=document)
        if self.current_guard is not None:
            # A read-only DB copy supplies its live cancellation/cut recheck
            # here, before the final proof and authority fences.
            self.current_guard()
        if after_policy is not None:
            # Invocation-local checks; never replace a shared callback while
            # worker and cancellation monitor readers run concurrently.
            after_policy()
        require(self.state.cancellation(self.plan["run_id"]) is None, "RUN_CANCELLED")
        root = self.owner.storage()["root"]
        require(safe_directory(self.directory).parent == root, "RUN_STORAGE_CHANGED")
        self.evidence.check()
        current_owner = _current_read(self.owner)
        task = current_owner.read_task(self.payload["task_id"])
        require(digest(task) == self.plan["binding_digest"], "STALE_BINDING")
        for actor, expected in self.binding["actor_binding_digests"].items():
            current = current_owner.read_binding(self.payload["task_id"], actor)
            require(current["actor_status"] == "active" and digest(current) == expected, "STALE_ACTOR")
        require(read_json(self.owner.path, 1024 * 1024, with_digest=True)[1]
                == self.binding["owner_input_sha256"], "OWNER_INPUT_CHANGED")

    def verify(self, job, delivered, response):
        row = self.snapshot["jobs"][job]
        attempt = row["current_attempt"]
        require(row["attempt_count"] == 1 and attempt is not None
                and attempt["worker_ref"] == self.expected_actors[job], "LOOP_EXECUTOR_DISPATCH")
        dispatch = {"run_id": self.plan["run_id"], "job_id": job, "actor_ref": attempt["worker_ref"],
                    "attempt": attempt["attempt"], "epoch": attempt["epoch"]}
        require(self.document(job+"-input.json") == delivered
                and self.document(job+"-result.json", attempt["result_digest"]) == response,
                "RUN_ARTIFACT_CHANGED")
        verify_loop_response(response, policy=self.policy, delivered=delivered,
            dispatch_identity=dispatch, expected_attempt=attempt, expected_schema=loop_schema(delivered),
            current_guard=self.current, attempt_directory=self.directory/(job+"-attempt"))
        self.evidence.pin_runtime(response["receipt"]["runtime"])
        self.current()


def saved_executor(directory, payload, plan, state, metadata=None, *, current_guard=None):
    template = _saved(Path(directory)/"r0-critic-template.json")
    if executor_version(plan, template) is None:
        return None
    return SavedExecutor(directory, payload, plan, state, metadata, current_guard=current_guard)
