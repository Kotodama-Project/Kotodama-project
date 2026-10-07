"""Forged local records exercise rejection; these fixtures never call a model."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone
try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in required Task swarm pytest job")
from test_task_swarm_task_runner import setup
from task_swarm.protocol import SwarmError
from task_swarm.task_backend import SyntheticTaskBackend
from task_swarm.task_runner import execute_task
from task_swarm.codex import _paths, MODEL, EFFORT, SANDBOX


def runtime_fixture(value, directory):
    attempt = directory/("attempt-"+uuid.uuid4().hex)
    attempt.mkdir(parents=True)
    paths = _paths(attempt)
    thread, turn = str(uuid.uuid4()), str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).isoformat()
    output = json.dumps(value["result"])
    rollout = attempt/("rollout-"+thread+".jsonl")
    records = [{"type":"session_meta","payload":{"id":thread,"cwd":str(attempt),"timestamp":stamp}},
               {"type":"turn_context","payload":{"turn_id":turn,"model":MODEL,"effort":EFFORT,
                   "sandbox_policy":{"type":SANDBOX},"approval_policy":"never","cwd":str(attempt)}},
               {"type":"event_msg","payload":{"type":"task_complete","turn_id":turn,"last_agent_message":output}}]
    rollout.write_text("\n".join(json.dumps(item) for item in records),encoding="utf-8")
    data = {"schema":{}, "command":{}, "process":{"pid":4242,"created_at":123.4},
            "result":value["result"], "last_message":value["result"]}
    for name, item in data.items():
        paths[name].write_text(json.dumps(item),encoding="utf-8")
    paths["events"].write_text(json.dumps({"type":"thread.started","thread_id":thread})+"\n"+
                               json.dumps({"type":"turn.completed","turn_id":turn})+"\n",encoding="utf-8")
    paths["stderr"].write_text("",encoding="utf-8")
    receipt = {"thread_id":thread,"turn_id":turn,"pid":4242,"created_at":123.4,
               "started_at":stamp,"runtime_receipt_path":str(rollout),
               "artifact_digests":{key:hashlib.sha256(paths[key].read_bytes()).hexdigest()
                                   for key in (*data,"events","stderr")}}
    paths["receipt"].write_text(json.dumps(receipt),encoding="utf-8")
    return {"result":value["result"],"receipt":receipt,"paths":{key:str(path) for key,path in paths.items()}}


class RecordedFixture(SyntheticTaskBackend):
    # False only to exercise the runtime-verification branch with local records.
    synthetic = False
    def produce(self, job, payload, directory, **kwargs):
        return runtime_fixture(super().produce(job,payload,directory,**kwargs),directory)
    def review(self, payload, reports, directory, **kwargs):
        return runtime_fixture(super().review(payload,reports,directory,**kwargs),directory)


@pytest.mark.parametrize("artifact", ["events", "process", "receipt", "result", "rollout"])
def test_nested_runtime_mutation_cannot_reach_owner_acceptance(tmp_path, artifact):
    owner, source, _, root = setup(tmp_path)
    class Backend(RecordedFixture):
        def review(self,payload,reports,directory,**kwargs):
            value = super().review(payload,reports,directory,**kwargs)
            worker = next((directory.parent/"facts").glob("attempt-*"))
            target = next(worker.glob("rollout-*")) if artifact == "rollout" else _paths(worker)[artifact]
            target.write_bytes(target.read_bytes()+b" ")
            return value
    with pytest.raises(SwarmError) as raised:
        execute_task(owner,source,Backend())
    assert raised.value.code in {"RUN_RUNTIME_ARTIFACT_CHANGED","RUN_RUNTIME_RECEIPT_CHANGED","RUN_RUNTIME_ROLLOUT_CHANGED"}
    assert not list(root.glob("*/receipt.json"))
    import sqlite3
    with sqlite3.connect(next(root.glob("*/execution.sqlite"))) as db:
        assert db.execute("select count(*) from jobs where state='accepted'").fetchone()[0] == 0


def test_replay_reopens_completed_runtime_output_under_external_receipt_anchor(tmp_path):
    owner, source, _, root = setup(tmp_path)
    result = execute_task(owner,source,RecordedFixture())
    target = next(root.glob("*/attempts/facts/attempt-*/rollout-*"))
    target.write_bytes(target.read_bytes()+b" ")
    with pytest.raises(SwarmError) as raised:
        execute_task(owner,source,RecordedFixture(),expected_receipt_sha256=result["receipt_sha256"])
    assert raised.value.code == "RUN_RUNTIME_ROLLOUT_CHANGED"
