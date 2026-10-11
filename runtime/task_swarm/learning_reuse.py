"""One reviewed learning reused by one next Task under its existing owner.

This adds purpose-bound local reuse evidence to the originating execution DB.
It never promotes Company truth or modifies Task records, grants, or KB state.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time

from .closed_loop import execute_closed_loop
from .closed_loop_context import validate_report_in_view
from .closed_loop_contract import integration_candidate, learning_candidate, validate_critic
from .owner_file import OwnerFile
from .protocol import SwarmError, canonical, digest, digest_ref, integer, ref
from .task_contract import require, shape, validate_input
from .task_planning import _Sources
from .task_runner import read_bytes, read_json, safe_directory
from .state import SwarmState


class _NoDispatch:
    synthetic = True

    def produce(self, *args, **kwargs):
        raise AssertionError("historical readback must not dispatch")

    review = produce


def purpose_digest(payload):
    """Bind semantic scope including exact original/corrected intent and limits."""
    sources = _Sources(payload)
    objective = payload["objective"]
    fields = {name: [{**span, "text": sources.span(span, current=name != "intent")}
                     for span in objective[name]]
              for name in ("constraints", "unknowns", "acceptance")}
    fields["intent"] = [{**span, "text": sources.span(span, current=False)}
                        for span in [objective["intent"]["original"], *objective["intent"]["replacements"]]]
    fields["references"] = [{**item, "text": sources.span(item["source"], current=True)}
                            for item in objective["references"]]
    return digest({"request": payload["request"], "acceptance": payload["acceptance"],
                   "stop_conditions": objective["stop_conditions"], "rollback": objective["rollback"], **fields})


def _origin(owner_path, payload_path, anchor, *, clock):
    digest_ref(anchor, "origin receipt anchor")
    owner = OwnerFile(owner_path, clock=clock)
    payload = read_json(Path(payload_path), 256 * 1024)
    binding = owner.read_task(payload.get("task_id"))
    payload = validate_input(payload, binding, now=clock(), allow_expired_objective=True)
    require(payload["version"] == 2, "REUSE_OBJECTIVE_REQUIRED")
    run_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    directory = safe_directory(owner.storage()["root"] / run_id)
    receipt, actual = read_json(directory / "receipt.json", with_digest=True)
    require(actual == anchor, "REUSE_ORIGIN_ANCHOR_MISMATCH")
    require("context-binding.json" not in receipt["artifact_sha256"], "REUSE_NESTED_ORIGIN_UNSUPPORTED")
    specification = read_json(directory / "specification.json")
    replay = execute_closed_loop(owner_path, payload_path, specification, _NoDispatch(),
        worker_actors=receipt["worker_actors"], critic_actor=receipt["critic_actor"],
        expected_receipt_sha256=anchor, clock=clock)
    require(replay["receipt"]["review_passed"] is True and replay["learning_candidate"] is not None,
            "REUSE_ORIGIN_NOT_REVIEWED")
    # Hash readback alone is insufficient: revalidate actual report evidence and
    # every independent critic against the exact saved delivered views.
    runtime_plan = read_json(directory / "plan.json")
    admission = read_json(directory / "extension.json") if "extension.json" in receipt["artifact_sha256"] else None
    scheduled = {job["job_id"]: job for job in [*runtime_plan["jobs"],
                 *(admission["jobs"] if admission else [])]}
    require(type(receipt["rounds"]) is int and receipt["rounds"] in (1, 2)
            and (receipt["rounds"] == 2) == (admission is not None)
            and set(receipt["dispatches"]) == set(scheduled), "REUSE_ORIGIN_PLAN_MISMATCH")
    reports, invocations, prior_review = {}, set(), None
    for round_index in range(receipt["rounds"]):
        work = sorted(job for job, spec in scheduled.items()
                      if job.startswith(f"r{round_index}-") and spec["kind"] == "work")
        for index, job in enumerate(work):
            delivered = read_json(directory / (job + "-input.json"))
            response = read_json(directory / (job + "-result.json"))
            proof = response["receipt"]
            require(proof["actor_ref"] == receipt["worker_actors"][index]
                    and proof["input_digest"] == digest(delivered) and proof["synthetic"] is True,
                    "REUSE_ORIGIN_IDENTITY_MISMATCH")
            require(receipt["dispatches"][job] == {
                "declared_input_ref": scheduled[job]["payload_ref"],
                "declared_input_digest": scheduled[job]["payload_digest"],
                "delivered_input_digest": digest(delivered)}
                and scheduled[job]["payload_digest"] == digest(delivered), "REUSE_ORIGIN_INPUT_MISMATCH")
            require(proof["invocation_ref"] not in invocations, "REUSE_ORIGIN_IDENTITY_MISMATCH")
            invocations.add(proof["invocation_ref"])
            reports[job] = validate_report_in_view(response["result"], delivered["view"], payload, allowed_jobs=work)
        job = f"r{round_index}-critic"
        delivered = read_json(directory / (job + "-input.json"))
        response, critic_sha = read_json(directory / (job + "-result.json"), with_digest=True)
        proof = response["receipt"]
        require(proof["actor_ref"] == receipt["critic_actor"]
                and proof["actor_ref"] not in receipt["worker_actors"]
                and proof["invocation_ref"] not in invocations
                and proof["input_digest"] == digest(delivered) and proof["synthetic"] is True,
                "REUSE_ORIGIN_IDENTITY_MISMATCH")
        invocations.add(proof["invocation_ref"])
        require(canonical(delivered["reports"]) == canonical(reports), "REUSE_ORIGIN_REPORT_MISMATCH")
        critic = validate_critic(response["result"], payload, reports, view=delivered["view"],
            plan_digest=receipt["initial_plan_digest"], round_index=round_index,
            initial_execution_plan_digest=digest(runtime_plan),
            expected_jobs=tuple(job for job, spec in scheduled.items()
                if spec["kind"] == "work" and (round_index or job.startswith("r0-"))),
            dispatched_input=delivered,
            dispatched_input_digest=receipt["dispatches"][job]["delivered_input_digest"],
            prior_review=prior_review, repair_admission=admission if round_index else None)
        prior_review = {"response": response, "dispatched_input": delivered,
                        "dispatched_input_digest": receipt["dispatches"][job]["delivered_input_digest"]}
    expected = integration_candidate(payload, reports, critic, critic_sha,
                                    stop_reason=replay["candidate"]["stop_reason"])
    require(canonical(expected) == canonical(replay["candidate"])
            and canonical(learning_candidate(expected)) == canonical(replay["learning_candidate"]),
            "REUSE_ORIGIN_CANDIDATE_MISMATCH")
    return owner, payload, receipt, expected, directory


def propose_learning(owner_path, payload_path, anchor, claim_index, *, clock=time.time):
    """Read one externally anchored result. This operation makes no decision."""
    owner, payload, receipt, candidate, directory = _origin(owner_path, payload_path, anchor, clock=clock)
    integer(claim_index, "claim index", minimum=0, maximum=len(candidate["claims"]) - 1)
    selected = candidate["claims"][claim_index]
    require(selected["claim"]["status"] == "supported", "REUSE_SUPPORTED_CLAIM_REQUIRED")
    producer = read_json(directory / (selected["job_id"] + "-result.json"))["receipt"]["actor_ref"]
    result = {"version": 1, "kind": "task_learning_reuse_proposal",
        "origin_receipt_sha256": anchor, "origin_task_id": payload["task_id"], "origin_revision": payload["revision"],
        "origin_input_digest": digest(payload), "claim_index": claim_index, "selected": selected,
        "purpose_digest": purpose_digest(payload), "owner_ref": owner.read_task()["owner_ref"],
        "producer_ref": producer, "producer_refs": receipt["worker_actors"],
        "origin_critic_ref": receipt["critic_actor"],
        "origin_critic_digest": candidate["final_critic_digest"],
        "authority": "projection_only", "model_runtime_verified": False}
    require(len(canonical(result).encode("utf-8")) <= 11000, "REUSE_PROPOSAL_LIMIT")
    return result


def learning_source(proposal):
    """A bounded projection used as an ordinary owner-admitted Task source."""
    text = canonical(proposal)
    require(len(text) <= 12000, "REUSE_PROPOSAL_LIMIT")
    return {"key": digest(["task_learning_reuse", proposal["origin_receipt_sha256"],
                           proposal["claim_index"]]), "revision": 1, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def with_learning_source(payload, proposal):
    result = copy.deepcopy(payload)
    require(result["version"] == 2 and purpose_digest(result) == proposal["purpose_digest"],
            "REUSE_PURPOSE_MISMATCH")
    require(result["task_id"] != proposal["origin_task_id"], "REUSE_NEW_TASK_REQUIRED")
    source = learning_source(proposal)
    old = [s for s in result["sources"] if s["key"] == source["key"]]
    require(not old or canonical(old) == canonical([source]), "REUSE_SOURCE_CONFLICT")
    if not old:
        require(len(result["sources"]) < 10, "REUSE_SOURCE_LIMIT")
        result["sources"].append(source)
    return result


class ReuseOwner:
    """A local extension of the same Task/Work owner's execution evidence.

    The operator explicitly supplies a target-owner learning_reuse grant. All
    writes are separately invoked review/decision operations. The evidence
    resides in A's existing execution.sqlite, never in another Task database.
    """

    def __init__(self, origin_owner, origin_input, anchor, target_owner, target_input,
                 proposal, *, clock=time.time, allow_expired_objective=False):
        self.origin_owner, self.origin_input = Path(origin_owner), Path(origin_input)
        self.anchor, self.target_owner, self.target_input = anchor, Path(target_owner), Path(target_input)
        self.proposal, self.clock = copy.deepcopy(proposal), clock
        require(type(allow_expired_objective) is bool, "REUSE_READBACK_INVALID")
        self._allow_expired_objective = allow_expired_objective
        _, _, self.receipt, _, self.directory = _origin(origin_owner, origin_input, anchor, clock=clock)
        self.state = SwarmState(self.directory / "execution.sqlite",
                                OwnerFile(origin_owner, clock=clock).read_task, clock=clock)
        self._scope()
        with self.state._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS learning_reuse_reviews (
                  review_ref TEXT PRIMARY KEY, command_digest TEXT NOT NULL,
                  document_json TEXT NOT NULL, document_digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_reuse_decisions (
                  generation INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                  command_digest TEXT NOT NULL, document_json TEXT NOT NULL, document_digest TEXT NOT NULL);
            """)

    def _scope(self, *, allow_expired_objective=None):
        expected = propose_learning(self.origin_owner, self.origin_input, self.anchor,
                                    self.proposal["claim_index"], clock=self.clock)
        require(canonical(expected) == canonical(self.proposal), "REUSE_PROPOSAL_CHANGED")
        owner = OwnerFile(self.target_owner, clock=self.clock)
        payload = read_json(self.target_input, 256 * 1024)
        binding = owner.read_task(payload.get("task_id"))
        payload = validate_input(payload, binding, now=self.clock(),
            allow_expired_objective=self._allow_expired_objective if allow_expired_objective is None
            else allow_expired_objective)
        require(binding["owner_ref"] == self.proposal["owner_ref"], "REUSE_OWNER_MISMATCH")
        require(canonical(with_learning_source(payload, self.proposal)) == canonical(payload),
                "REUSE_SOURCE_MISSING")
        doc = read_json(self.target_owner, 1024 * 1024)
        grant = doc.get("learning_reuse")
        shape(grant, {"version", "grant_ref", "policy_revision_ref", "proposal_digest",
              "origin_receipt_sha256", "target_context_digest", "purpose_digest", "reviewer_ref", "expires_at"},
              "REUSE_GRANT_REQUIRED")
        require(type(grant["version"]) is int and grant["version"] == 1, "REUSE_GRANT_REQUIRED")
        for key in ("grant_ref", "policy_revision_ref", "reviewer_ref"):
            ref(grant[key], key)
        require(grant["proposal_digest"] == digest(self.proposal)
                and grant["origin_receipt_sha256"] == self.anchor
                and grant["target_context_digest"] == digest(payload)
                and grant["purpose_digest"] == purpose_digest(payload), "REUSE_GRANT_MISMATCH")
        require(type(grant["expires_at"]) in (int, float) and self.clock() < grant["expires_at"]
                <= binding["expires_at"]
                and payload["objective"]["budget"]["deadline"] <= grant["expires_at"], "REUSE_GRANT_EXPIRED")
        reviewer = owner.read_binding(binding["task_id"], grant["reviewer_ref"])
        require(reviewer["actor_status"] == "active"
                and reviewer["actor_ref"] not in {*self.proposal["producer_refs"], binding["owner_ref"]},
                "REUSE_REVIEWER_NOT_INDEPENDENT")
        return owner, payload, binding, grant, reviewer

    @staticmethod
    def _row(row):
        require(row is not None, "REUSE_EVIDENCE_MISSING")
        value = json.loads(row["document_json"])
        require(digest(value) == row["document_digest"], "REUSE_EVIDENCE_CHANGED")
        return value

    def _authority_fingerprint(self):
        # No database operation here: usable while the evidence CAS is locked.
        OwnerFile(self.origin_owner, clock=self.clock).read_task()
        OwnerFile(self.target_owner, clock=self.clock).read_task()
        require(read_json(self.directory / "receipt.json", with_digest=True)[1] == self.anchor,
                "REUSE_ORIGIN_ANCHOR_MISMATCH")
        require(read_json(self.origin_owner, with_digest=True)[1] == self.receipt["owner_input_sha256"],
                "REUSE_ORIGIN_OWNER_CHANGED")
        for name, expected in self.receipt["artifact_sha256"].items():
            require(hashlib.sha256(read_bytes(self.directory / name)).hexdigest() == expected,
                    "REUSE_ORIGIN_ARTIFACT_CHANGED")
        return digest([read_json(path, with_digest=True)[1]
                       for path in (self.origin_owner, self.origin_input, self.target_owner, self.target_input)])

    def _head(self, db):
        return db.execute("SELECT * FROM learning_reuse_decisions ORDER BY generation DESC LIMIT 1").fetchone()

    def review(self, review_ref, reviewer_ref, outcome, reason):
        """Record a distinct actor's explicit review, not a compiler PASS."""
        ref(review_ref, "review ref")
        require(outcome in {"allow", "reject"} and isinstance(reason, str) and 0 < len(reason) <= 1000,
                "REUSE_REVIEW_INVALID")
        fingerprint = self._authority_fingerprint()
        _, payload, binding, grant, reviewer = self._scope(allow_expired_objective=False)
        require(reviewer_ref == grant["reviewer_ref"], "REUSE_REVIEWER_NOT_AUTHORIZED")
        command = {"review_ref": review_ref, "proposal_digest": digest(self.proposal),
            "target_task_id": payload["task_id"], "target_revision": payload["revision"],
            "target_binding_digest": digest(binding), "grant_digest": digest(grant),
            "reviewer_binding_digest": digest(reviewer), "reviewer_ref": reviewer_ref,
            "outcome": outcome, "reason": reason}
        with self.state._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            require(self._authority_fingerprint() == fingerprint, "REUSE_AUTHORITY_CHANGED")
            old = db.execute("SELECT * FROM learning_reuse_reviews WHERE review_ref=?", (review_ref,)).fetchone()
            if old:
                require(old["command_digest"] == digest(command), "REUSE_REVIEW_CONFLICT")
                return self._row(old)
            require(db.execute("SELECT count(*) FROM learning_reuse_reviews").fetchone()[0] < 8,
                    "REUSE_EVIDENCE_LIMIT")
            document = {**command, "kind": "task_learning_reuse_review", "recorded_at": self.clock(),
                        "model_runtime_verified": False}
            db.execute("INSERT INTO learning_reuse_reviews VALUES(?,?,?,?)",
                       (review_ref, digest(command), canonical(document), digest(document)))
            db.commit()
            return document

    def decide(self, decision_actor, review_ref, outcome, idempotency_key, *, expected_generation):
        """Explicit owner decision under an existing, currently scoped grant."""
        require(outcome in {"allow", "reject", "revoke", "supersede"}, "REUSE_DECISION_INVALID")
        integer(expected_generation, "expected generation", minimum=0, maximum=8)
        ref(idempotency_key, "idempotency key")
        fingerprint = self._authority_fingerprint()
        _, payload, binding, grant, reviewer = self._scope(allow_expired_objective=False)
        require(decision_actor == binding["owner_ref"] and decision_actor != self.proposal["producer_ref"],
                "REUSE_DECISION_NOT_OWNER")
        with self.state._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            require(self._authority_fingerprint() == fingerprint, "REUSE_AUTHORITY_CHANGED")
            review = self._row(db.execute("SELECT * FROM learning_reuse_reviews WHERE review_ref=?", (review_ref,)).fetchone())
            require(review["proposal_digest"] == digest(self.proposal)
                    and review["target_binding_digest"] == digest(binding)
                    and review["grant_digest"] == digest(grant)
                    and review["reviewer_binding_digest"] == digest(reviewer), "REUSE_REVIEW_STALE")
            require(outcome != "allow" or review["outcome"] == "allow", "REUSE_REVIEW_REJECTED")
            command = {"decision_actor": decision_actor, "review_digest": digest(review), "outcome": outcome,
                "proposal_digest": digest(self.proposal), "target_task_id": payload["task_id"],
                "target_revision": payload["revision"], "target_binding_digest": digest(binding),
                "grant_digest": digest(grant), "idempotency_key": idempotency_key}
            old = db.execute("SELECT * FROM learning_reuse_decisions WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            head = self._head(db)
            if old:
                require(old["command_digest"] == digest(command), "REUSE_DECISION_CONFLICT")
                require(old["generation"] == head["generation"], "REUSE_DECISION_STALE")
                return self._row(old)
            generation = head["generation"] if head else 0
            require(generation == expected_generation, "REUSE_GENERATION_CONFLICT")
            require(generation < 8, "REUSE_EVIDENCE_LIMIT")
            require(head is None or self._row(head)["target_task_id"] == payload["task_id"]
                    and self._row(head)["target_revision"] == payload["revision"]
                    and self._row(head)["proposal_digest"] == digest(self.proposal), "REUSE_ONE_TARGET_ONLY")
            document = {**command, "kind": "task_learning_reuse_decision", "generation": generation + 1,
                        "recorded_at": self.clock(), "expires_at": grant["expires_at"],
                        "authority": "one_target_task_only", "company_truth_changed": False}
            db.execute("INSERT INTO learning_reuse_decisions VALUES(?,?,?,?,?)",
                       (generation + 1, idempotency_key, digest(command), canonical(document), digest(document)))
            db.commit()
            return document

    def current(self, expected_decision_digest):
        digest_ref(expected_decision_digest, "decision digest")
        fingerprint = self._authority_fingerprint()
        _, payload, binding, grant, reviewer = self._scope()
        with self.state._connect() as db:
            decision = self._row(self._head(db))
            require(digest(decision) == expected_decision_digest, "REUSE_DECISION_STALE")
            require(decision["outcome"] == "allow", "REUSE_NOT_ALLOWED")
            require(decision["target_task_id"] == payload["task_id"]
                    and decision["target_revision"] == payload["revision"]
                    and decision["target_binding_digest"] == digest(binding)
                    and decision["proposal_digest"] == digest(self.proposal)
                    and decision["grant_digest"] == digest(grant)
                    and self.clock() < decision["expires_at"], "REUSE_DECISION_STALE")
            rows = db.execute("SELECT * FROM learning_reuse_reviews WHERE document_digest=?",
                              (decision["review_digest"],)).fetchall()
            require(len(rows) == 1, "REUSE_EVIDENCE_MISSING")
            review = self._row(rows[0])
            require(review["outcome"] == "allow"
                    and review["reviewer_binding_digest"] == digest(reviewer), "REUSE_REVIEW_STALE")
            require(self._authority_fingerprint() == fingerprint, "REUSE_AUTHORITY_CHANGED")
        return decision

    def execute(self, expected_decision_digest, plan, backend, *, worker_actors,
                critic_actor="verifier", repair_planner=None, expected_receipt_sha256=None):
        """Use the real coordinator, rechecking the current evidence at every guard."""
        result = execute_closed_loop(self.target_owner, self.target_input, plan, backend,
            worker_actors=worker_actors, critic_actor=critic_actor, repair_planner=repair_planner,
            clock=self.clock, expected_receipt_sha256=expected_receipt_sha256,
            reuse_context={"origin_owner": str(self.origin_owner), "origin_input": str(self.origin_input),
                "anchor": self.anchor, "proposal": self.proposal, "decision_digest": expected_decision_digest})
        return {**result, "reuse_decision_digest": expected_decision_digest,
                "reuse_proposal_digest": digest(self.proposal)}

    def context_binding(self, expected_decision_digest):
        decision = self.current(expected_decision_digest)
        return {"kind": "task_learning_reuse", "decision_digest": expected_decision_digest,
            "proposal_digest": digest(self.proposal), "origin_receipt_sha256": self.anchor,
            "source_key": learning_source(self.proposal)["key"],
            "target_task_id": decision["target_task_id"], "target_revision": decision["target_revision"]}

    def validate_delivery(self, delivered):
        source = learning_source(self.proposal)
        require(any(s["source_key"] == source["key"] and s["source_revision"] == source["revision"]
                    and s["start"] == 0 and s["end"] == len(source["text"]) and s["text"] == source["text"]
                    for s in delivered["view"]["spans"]), "REUSE_CLAIM_NOT_DELIVERED")

    def validate_review(self, critic, reports):
        if all(item["status"] == "passed" for item in critic["validations"]):
            source = learning_source(self.proposal)
            require(any(any(e["source_key"] == source["key"]
                            for e in reports[r["job_id"]]["claims"][r["claim_index"]]["evidence"])
                        for item in critic["validations"] for r in item["evidence"]), "REUSE_CLAIM_NOT_CITED")

    def validate_candidate(self, candidate):
        if candidate["status"] == "needs_owner_review":
            source = learning_source(self.proposal)
            require(any(any(e["source_key"] == source["key"] for e in c["claim"]["evidence"])
                        for c in candidate["claims"]), "REUSE_CLAIM_NOT_CITED")


def main(argv=None):
    """Explicit proposal, review, owner decision and local simulation commands."""
    import argparse
    import sys
    from .closed_loop import ScriptedSimulation
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    proposal = commands.add_parser("propose", help="Read one externally anchored supported claim")
    proposal.add_argument("--owner", required=True, type=Path)
    proposal.add_argument("--input", required=True, type=Path)
    proposal.add_argument("--anchor", required=True)
    proposal.add_argument("--claim-index", required=True, type=int)
    prepare = commands.add_parser("prepare", help="Project a proposal into an unadmitted Task input")
    prepare.add_argument("--input", required=True, type=Path)
    prepare.add_argument("--proposal", required=True, type=Path)
    actions = {name: commands.add_parser(name) for name in ("review", "decide", "current", "run")}
    for action in actions.values():
        action.add_argument("--context", required=True, type=Path,
                            help="Private JSON origin/target paths, external anchor and exact proposal")
    actions["review"].add_argument("--review-ref", required=True)
    actions["review"].add_argument("--reviewer", required=True)
    actions["review"].add_argument("--outcome", choices=("allow", "reject"), required=True)
    actions["review"].add_argument("--reason", required=True)
    actions["decide"].add_argument("--actor", required=True)
    actions["decide"].add_argument("--review-ref", required=True)
    actions["decide"].add_argument("--outcome", choices=("allow", "reject", "revoke", "supersede"), required=True)
    actions["decide"].add_argument("--key", required=True)
    actions["decide"].add_argument("--expected-generation", type=int, required=True)
    for action in (actions["current"], actions["run"]):
        action.add_argument("--decision-digest", required=True)
    actions["run"].add_argument("--plan", type=Path, required=True)
    actions["run"].add_argument("--simulation", type=Path, required=True)
    actions["run"].add_argument("--worker", action="append", required=True)
    actions["run"].add_argument("--critic", default="verifier")
    actions["run"].add_argument("--receipt-sha256")
    args = parser.parse_args(argv)
    try:
        if args.command == "propose":
            result = propose_learning(args.owner, args.input, args.anchor, args.claim_index)
        elif args.command == "prepare":
            result = with_learning_source(read_json(args.input, 256 * 1024), read_json(args.proposal, 32768))
        else:
            context = read_json(args.context, 65536)
            shape(context, {"origin_owner", "origin_input", "anchor", "target_owner", "target_input", "proposal"},
                  "REUSE_CONTEXT_INVALID")
            owner = ReuseOwner(**context, allow_expired_objective=(
                args.command == "run" and args.receipt_sha256 is not None))
            if args.command == "review":
                result = owner.review(args.review_ref, args.reviewer, args.outcome, args.reason)
            elif args.command == "decide":
                result = owner.decide(args.actor, args.review_ref, args.outcome, args.key,
                                      expected_generation=args.expected_generation)
            elif args.command == "current":
                result = owner.current(args.decision_digest)
            else:
                scenario = read_json(args.simulation, 1024 * 1024)
                backend = ScriptedSimulation(scenario)
                repair = scenario["repair_plan"]
                result = owner.execute(args.decision_digest, read_json(args.plan, 256 * 1024),
                    backend, worker_actors=args.worker, critic_actor=args.critic,
                    repair_planner=(lambda _gap: copy.deepcopy(repair)) if repair is not None else None,
                    expected_receipt_sha256=args.receipt_sha256)
        print(canonical(result))
        return 0
    except SwarmError as exc:
        print(canonical({"error": exc.code, "message": exc.detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
