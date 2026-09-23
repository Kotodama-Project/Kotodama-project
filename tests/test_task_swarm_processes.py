"""Actual process concurrency, separate from thread and mocked-backend tests."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from task_swarm.protocol import digest, validate_binding
from task_swarm.state import SwarmState

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def children(program, args):
    environment = {**os.environ, "PYTHONPATH": str(RUNTIME), "PYTHONUTF8": "1"}
    processes = [subprocess.Popen([sys.executable, "-c", program, *arguments], env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for arguments in args]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, stderr.decode("utf-8", errors="replace")
            results.append(json.loads(stdout.decode("utf-8")))
        return results
    finally:
        for process in processes:
            if process.poll() is None:
                # Popen retains the exact owned OS process handle.
                process.kill()
                process.communicate(timeout=5)


def test_eight_process_claims_respect_global_concurrency(tmp_path):
    binding = dict(task_id="task", revision=1, context_digest="a"*64, owner_ref="owner", active_home="home",
                   authority_ref="order", capability_ref="cap", expires_at=200, status="active")
    path = tmp_path / "state.sqlite"
    state = SwarmState(path, lambda task:binding, clock=lambda:100)
    jobs = [dict(job_id=f"job-{i}", kind="work", dependencies=[], exclusive_keys=[], payload_ref=f"ref/job/{i}", payload_digest="b"*64) for i in range(8)]
    state.create_run(dict(run_id="run", task_id="task", binding_digest=digest(validate_binding(binding, now=100)),
        budget=dict(attempt_budget=8, concurrency=3, deadline=190), jobs=jobs))
    program = """
import json,sys
from task_swarm.state import SwarmState
b=json.loads(sys.argv[2])
s=SwarmState(sys.argv[1],lambda task:b,clock=lambda:100)
lease=s.claim('run',sys.argv[3],lease_seconds=30)
print(json.dumps({'claimed':lease is not None}))
"""
    results = children(program, [[str(path), json.dumps(binding), f"worker-{i}"] for i in range(8)])
    assert sum(r["claimed"] for r in results) == 3
    assert state.snapshot("run")["counts"]["running"] == 3


def test_eight_process_bootstrap_and_pending_quota_are_atomic(tmp_path):
    path = tmp_path / "transport.sqlite"
    program = """
import json,sys
from task_swarm.transport import PeerTransport
from task_swarm.protocol import SwarmError
actor=sys.argv[2]
def binding(task,who):
 return dict(task_id='task',revision=1,context_digest='a'*64,owner_ref='owner',active_home='home',authority_ref='order',capability_ref='cap-'+who,expires_at=200,status='active',actor_ref=who,epoch=1,invocation_ref='inv-'+who,actor_status='active')
t=PeerTransport(sys.argv[1],binding,lambda *args:True,clock=lambda:100,max_messages=20,max_pending=3)
r=dict(message_id='m-'+actor,idempotency_key='k-'+actor,task_id='task',revision=1,context_digest='a'*64,owner_ref='owner',active_home='home',authority_ref='order',capability_ref='cap-'+actor,sender_ref=actor,recipient_ref='receiver',sender_epoch=1,invocation_ref='inv-'+actor,parent_message_id=None,payload_ref='ref/payload',payload_digest='b'*64,expires_at=180)
try:
 t.send(r); outcome='stored'
except SwarmError as error:
 outcome=error.code
print(json.dumps({'outcome':outcome}))
"""
    results = children(program, [[str(path), f"sender-{i}"] for i in range(8)])
    assert sum(r["outcome"] == "stored" for r in results) == 3
    assert all(r["outcome"] in ("stored", "BACKPRESSURE") for r in results)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 3
