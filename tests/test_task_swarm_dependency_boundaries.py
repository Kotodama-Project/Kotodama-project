"""Authority cutoffs, immutable delivery and learning across the released lane."""
import copy
import json
from pathlib import Path
import sqlite3
import threading

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_dependency_loop import setup_dependency, Calculation
from test_task_swarm_closed_loop import execute
from task_swarm.closed_loop import execute_closed_loop
from task_swarm.dependency_contract import check_descriptor, descriptor
from task_swarm.learning_reuse import propose_learning
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_runner import read_json


@pytest.mark.parametrize("change", ["core", "envelope", "db_core"])
def test_recomputed_core_envelope_and_full_job_digest_are_required(tmp_path, change):
    setup=setup_dependency(tmp_path)
    result=execute(setup, Calculation(setup[3],setup[6]))
    directory=setup[0].parent/"operations"/result["receipt"]["run_id"]
    plan=read_json(directory/"plan.json")
    desc, envelope=descriptor(setup[3],setup[4])
    if change=="core":envelope["core"]["gate"]=[]
    elif change=="envelope":envelope["descriptor_sha256"]="0"*64
    else:
        next(job for job in plan["jobs"] if job["job_id"]=="r0-prerequisite")["payload_digest"]=envelope["core_digest"]
    with pytest.raises(SwarmError,match="LOOP_DEPENDENCY_POLICY"):
        check_descriptor(setup[3],setup[4],plan,desc,envelope)


@pytest.mark.parametrize("phase", ["prerequisite", "b"])
@pytest.mark.parametrize("change", ["deadline", "actor", "cancel"])
def test_current_authority_failure_preserves_only_prior_acceptance(tmp_path,phase,change):
    setup=setup_dependency(tmp_path)
    now=[1000]
    event=threading.Event()
    class Backend(Calculation):
        def mutate(self):
            if change=="deadline":now[0]=1101
            elif change=="actor":
                setup[2]["actors"]["verifier"]["epoch"]+=1
                setup[0].write_bytes(json.dumps(setup[2]).encode())
            else:event.set()
        def produce(self,delivered,*args,**kwargs):
            response=super().produce(delivered,*args,**kwargs)
            if phase=="b" and "prerequisite" in delivered:self.mutate()
            return response
        def review(self,delivered,*args,**kwargs):
            response=super().review(delivered,*args,**kwargs)
            if phase=="prerequisite" and "core" in delivered:self.mutate()
            return response
    backend=Backend(setup[3],setup[6])
    with pytest.raises(SwarmError):
        execute_closed_loop(setup[0],setup[1],setup[4],backend,worker_actors=setup[5],
                            clock=lambda:now[0],cancel_event=event)
    directory=next((setup[0].parent/"operations").glob("task-run-*"))
    assert not (directory/"receipt.json").exists()
    with sqlite3.connect(directory/"execution.sqlite") as connection:
        accepted=connection.execute("SELECT job_id FROM jobs WHERE state='accepted'").fetchall()
        assert accepted==([("r0-speed",)] if phase=="b" else [])
        assert connection.execute("SELECT count(*) FROM attempts").fetchone()[0]==(3 if phase=="b" else 2)


def test_learning_origin_revalidates_preaccepted_a_and_rejects_inference(tmp_path):
    setup=setup_dependency(tmp_path)
    result=execute(setup,Calculation(setup[3],setup[6]))
    claims=result["candidate"]["claims"]
    ai=next(i for i,row in enumerate(claims) if row["job_id"]=="r0-speed")
    bi=next(i for i,row in enumerate(claims) if row["job_id"]=="r0-uncertainty")
    proposal=propose_learning(setup[0],setup[1],result["receipt_sha256"],ai,clock=lambda:1000)
    assert proposal["selected"]["claim"]["text"]=="speed=42"
    with pytest.raises(SwarmError,match="REUSE_SUPPORTED_CLAIM_REQUIRED"):
        propose_learning(setup[0],setup[1],result["receipt_sha256"],bi,clock=lambda:1000)
    directory=setup[0].parent/"operations"/result["receipt"]["run_id"]
    with sqlite3.connect(directory/"execution.sqlite") as connection:
        connection.execute("UPDATE jobs SET accepted_at=1001 WHERE job_id='r0-speed'")
    with pytest.raises(SwarmError):
        propose_learning(setup[0],setup[1],result["receipt_sha256"],ai,clock=lambda:1000)


@pytest.mark.parametrize("change",["missing","digest","lane","extra"])
def test_self_hashed_critic_without_exact_actual_b_input_is_rejected(tmp_path,monkeypatch,change):
    from task_swarm import closed_loop
    original=closed_loop.validate_critic
    def altered(value,payload,reports,**kw):
        delivered=copy.deepcopy(kw["dispatched_input"])
        if change=="missing":delivered.pop("prerequisite_inputs")
        else:
            key=next(iter(delivered["prerequisite_inputs"]))
            if change=="digest":delivered["prerequisite_inputs"][key]["delivered_input_digest"]="0"*64
            elif change=="lane":delivered["prerequisite_inputs"][key]["prerequisite"]["report"]["summary"]="substituted"
            else:delivered["prerequisite_inputs"]["unexpected"]=delivered["prerequisite_inputs"][key]
        return original(value,payload,reports,**{**kw,"dispatched_input":delivered,"dispatched_input_digest":digest(delivered)})
    monkeypatch.setattr(closed_loop,"validate_critic",altered)
    setup=setup_dependency(tmp_path)
    with pytest.raises(SwarmError,match="LOOP_RELEASE_INVALID"):
        execute(setup,Calculation(setup[3],setup[6]))
