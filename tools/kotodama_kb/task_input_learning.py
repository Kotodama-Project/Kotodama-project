"""One explicitly selected, owner-approved learning in a source-bound Task.

Compilation produces an unadmitted candidate. Verification first checks the
real final Task binding, then reproduces both the KB projection and the one
learning addition. The existing reuse owner remains the only decision reader.
"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from runtime.task_swarm.closed_loop import execute_closed_loop
from runtime.task_swarm.closed_loop_context import derive_child_view
from runtime.task_swarm.closed_loop_contract import validate_plan
from runtime.task_swarm.learning_reuse import (ReuseOwner, learning_source,
    propose_learning, with_learning_source)
from runtime.task_swarm.owner_file import OwnerFile
from runtime.task_swarm.protocol import digest, integer
from runtime.task_swarm.task_contract import require, shape, validate_input
from runtime.task_swarm.task_runner import read_json

from .task_input import _build, _copy, _SEED_KEYS, compile_task_input


_CANDIDATE_KEYS = {"payload", "supplied_plan", "seed_digest", "source_checks",
                   "context_projection", "diagnostics", "learning"}


def _learning(value):
    shape(value, {"version", "origin_owner", "origin_input", "anchor", "proposal"},
          "TASK_LEARNING_INVALID")
    require(type(value["version"]) is int and value["version"] == 1, "TASK_LEARNING_INVALID")
    for name in ("origin_owner", "origin_input"):
        path = value[name]
        require(isinstance(path, str) and 0 < len(path) <= 4096 and "\0" not in path
                and Path(path).is_absolute(), "TASK_LEARNING_PATH_INVALID")
    require(isinstance(value["proposal"], dict), "TASK_LEARNING_INVALID")
    integer(value["proposal"].get("claim_index"), "claim index", minimum=0, maximum=1000)
    require(all(isinstance(value["proposal"].get(key), str) for key in
                ("origin_receipt_sha256", "purpose_digest", "origin_task_id")),
            "TASK_LEARNING_INVALID")
    return value


def _compose(base, learning):
    source = learning_source(learning["proposal"])
    require(not any(row["key"] == source["key"] for row in base["payload"]["sources"]),
            "TASK_LEARNING_SOURCE_PRESENT")
    payload = with_learning_source(base["payload"], learning["proposal"])
    selected = {"source_key": source["key"], "source_revision": source["revision"],
                "start": 0, "end": len(source["text"])}
    plan = copy.deepcopy(base["supplied_plan"])
    plan["parent_input_digest"] = digest(payload)
    for job in plan["jobs"]:
        job["selected_spans"].append(copy.deepcopy(selected))
    plan = validate_plan(plan, payload)
    spans = {tuple(span[key] for key in ("source_key", "source_revision", "start", "end")): span
             for job in plan["jobs"] for span in job["selected_spans"]}
    require(len(spans) <= 32, "TASK_CONTEXT_LIMIT")
    derive_child_view(payload, "r0-critic", list(spans.values()), plan_digest=digest(plan))
    candidate = {**base, "payload": payload, "supplied_plan": plan, "learning": learning,
                 "diagnostics": {**base["diagnostics"], "learning": {
                     "status": "requires_current_owner_decision", "count": 1,
                     "base_payload_digest": digest(base["payload"]),
                     "base_plan_digest": digest(base["supplied_plan"]),
                     "proposal_digest": digest(learning["proposal"])}}}
    return _copy(candidate)


def compile_task_learning_input(bundle, seed_payload, owner_path, *, origin_owner,
                                origin_input, origin_anchor, claim_index, clock=time.time):
    """Compile one proposal without writing the owner, grant or reuse decision."""
    require(all(isinstance(path, (str, Path)) and 0 < len(str(path)) <= 4096
                and "\0" not in str(path) for path in (origin_owner, origin_input)),
            "TASK_LEARNING_PATH_INVALID")
    base = compile_task_input(bundle, seed_payload, owner_path, clock=clock)
    proposal = propose_learning(origin_owner, origin_input, origin_anchor, claim_index, clock=clock)
    binding = OwnerFile(owner_path, clock=clock).read_task()
    require(proposal["owner_ref"] == binding["owner_ref"], "REUSE_OWNER_MISMATCH")
    learning = {"version": 1, "origin_owner": str(Path(origin_owner).resolve()),
                "origin_input": str(Path(origin_input).resolve()),
                "anchor": origin_anchor, "proposal": proposal}
    candidate = _compose(base, _learning(learning))
    # Recheck the original admitted seed after the independent origin readback.
    require(compile_task_input(bundle, seed_payload, owner_path, clock=clock) == base,
            "TASK_CONTEXT_CANDIDATE_CHANGED")
    return candidate


def _verify_projection(bundle, candidate, owner_path, payload_path, *, clock, allow_expired):
    """Rebuild KB inputs only; the caller separately checks current reuse state."""
    candidate = _copy(candidate)
    shape(candidate, _CANDIDATE_KEYS, "TASK_LEARNING_CANDIDATE_INVALID")
    owner = OwnerFile(owner_path, clock=clock)
    binding = owner.read_task()
    payload = validate_input(candidate["payload"], binding, now=clock(),
                             allow_expired_objective=allow_expired)
    require(read_json(Path(payload_path)) == payload, "TASK_CONTEXT_INPUT_CHANGED")
    proposal = _learning(candidate["learning"])["proposal"]
    source = learning_source(proposal)
    matching = [row for row in payload["sources"] if row["key"] == source["key"]]
    require(matching == [source], "REUSE_SOURCE_MISSING")
    # Rebuild a projection, not a forged admission. Only the final payload above
    # is validated against the real owner; no substitute context_digest exists.
    seed = {key: payload[key] for key in _SEED_KEYS}
    seed["version"] = 1
    seed["sources"] = [row for row in payload["sources"] if row["key"] != source["key"]]
    base = _build(bundle, seed, binding, now=clock(), allow_expired=allow_expired)
    require(_compose(base, candidate["learning"]) == candidate, "TASK_CONTEXT_CANDIDATE_CHANGED")
    document = read_json(owner.path)
    declared = {str((owner.path.parent / item["path"]).resolve()): item["sha256"]
                for item in document["source_checks"]}
    require(all(declared.get(str(Path(item["path"]).resolve())) == item["sha256"]
                for item in candidate["source_checks"]), "TASK_CONTEXT_OWNER_CHECKS_REQUIRED")
    require(owner.read_task() == binding, "STALE_BINDING")
    # Keep the original producer's real-time Concept checks, including replay.
    from .task_input import _live_context
    _live_context(candidate["context_projection"], clock())
    return payload


def verify_task_learning_input(bundle, candidate, owner_path, payload_path, *,
                               decision_digest, clock=time.time, allow_expired=False):
    """Check final owner admission and the current existing reuse decision."""
    candidate = _copy(candidate)
    _verify_projection(bundle, candidate, owner_path, payload_path,
                       clock=clock, allow_expired=allow_expired)
    learning = _learning(candidate["learning"])
    reuse = ReuseOwner(learning["origin_owner"], learning["origin_input"],
        learning["anchor"], owner_path, payload_path, learning["proposal"], clock=clock,
        allow_expired_objective=allow_expired)
    reuse.current(decision_digest)
    payload = _verify_projection(bundle, candidate, owner_path, payload_path,
                                 clock=clock, allow_expired=allow_expired)
    # The second projection can take time. Re-read the real decision and origin
    # after it, rather than returning a cached authority result from above.
    reuse.current(decision_digest)
    from .task_input import _live_context
    _live_context(candidate["context_projection"], clock())
    return payload


def execute_task_learning_input(bundle, candidate, owner_path, payload_path, backend, *,
                                decision_digest, worker_actors, clock=time.time, **options):
    """Use the real coordinator with the existing, independently checked owner."""
    candidate = _copy(candidate)
    require("reuse_context" not in options, "TASK_LEARNING_CONTEXT_OVERRIDE")
    allow_expired = options.get("expected_receipt_sha256") is not None

    def guard():
        # The coordinator checks ReuseOwner.current immediately before and after
        # this backend wrapper, as well as at claim/report/finalization. Keep the
        # additional KB projection checks here; never replace the runtime's
        # current authority check with a saved result from our initial verify.
        _verify_projection(bundle, candidate, owner_path, payload_path,
                           clock=clock, allow_expired=allow_expired)

    verify_task_learning_input(bundle, candidate, owner_path, payload_path,
        decision_digest=decision_digest, clock=clock, allow_expired=allow_expired)

    from runtime.task_swarm.task_backend import checked_backend
    learning = candidate["learning"]
    context = {key: learning[key] for key in ("origin_owner", "origin_input", "anchor", "proposal")}
    result = execute_closed_loop(owner_path, payload_path, candidate["supplied_plan"], checked_backend(backend, guard),
        worker_actors=worker_actors, clock=clock,
        reuse_context={**context, "decision_digest": decision_digest}, **options)
    if result.get("duplicate"):
        # Anchored replay has no backend call and waives the old Task deadline.
        # It must still satisfy the current Concept expiry at the return edge.
        from .task_input import _live_context
        _live_context(candidate["context_projection"], clock())
    return result
