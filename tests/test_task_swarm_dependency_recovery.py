"""Real child exit at release/lease/terminal boundaries, with no implicit retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_dependency_loop import setup_dependency, Calculation
from task_swarm.closed_loop import execute_closed_loop, cancel_closed_loop
from task_swarm.owner_file import OwnerFile
from task_swarm.state import SwarmState
from task_swarm.task_runner import read_json
from task_swarm.protocol import SwarmError, digest


def prepare(root):
    setup=setup_dependency(root)
    config={"owner":str(setup[0]),"input":str(setup[1]),"plan":setup[4],"actors":setup[5],"measure":setup[6]}
    (root/"control.json").write_text(json.dumps(config))
    return config


def child(root, mode):
    return subprocess.run([sys.executable,str(Path(__file__).resolve()),str(root),mode],
                          capture_output=True,text=True,timeout=20)


def snapshot(config):
    owner=OwnerFile(config["owner"],clock=lambda:1000)
    payload=read_json(Path(config["input"]))
    run="task-run-"+digest([payload["task_id"],payload["revision"]])[:32]
    return SwarmState(owner.storage()["root"]/run/"execution.sqlite",owner.read_task,clock=lambda:1000).snapshot(run)


def test_release_resume_preserves_a_and_never_repeats_first_two_calls(tmp_path):
    config=prepare(tmp_path)
    assert child(tmp_path,"release").returncode==73
    before=snapshot(config)
    assert before["jobs"]["r0-uncertainty"]["attempt_count"]==0
    result=child(tmp_path,"resume")
    assert result.returncode==0,result.stderr
    after=snapshot(config)
    assert before["jobs"]["r0-speed"]["accepted"]==after["jobs"]["r0-speed"]["accepted"]
    assert after["budget"]["attempts_used"]==4
    assert json.loads((tmp_path/"result.json").read_text())["calls"]==["r0-uncertainty","r0-critic"]
    assert child(tmp_path,"resume").returncode==2


def test_leased_b_is_unknown_and_never_redispatched(tmp_path):
    config=prepare(tmp_path)
    assert child(tmp_path,"leased").returncode==74
    before=snapshot(config)
    assert child(tmp_path,"resume").returncode==2
    assert snapshot(config)==before


def test_terminal_resume_preserves_scoped_acceptance(tmp_path):
    config=prepare(tmp_path)
    assert child(tmp_path,"terminal").returncode==75
    before=snapshot(config)
    result=child(tmp_path,"resume")
    assert result.returncode==0,result.stderr
    after=snapshot(config)
    assert after["jobs"]["r0-speed"]["accepted"]==before["jobs"]["r0-speed"]["accepted"]
    assert json.loads((tmp_path/"result.json").read_text())["calls"]==[]


@pytest.mark.parametrize("change",["cancel","source","proof"])
def test_release_resume_rechecks_current_authority(tmp_path,change):
    config=prepare(tmp_path)
    assert child(tmp_path,"release").returncode==73
    before=snapshot(config)
    if change=="cancel": cancel_closed_loop(config["owner"],config["input"],clock=lambda:1000)
    elif change=="source":
        file=Path(config["input"]);file.write_bytes(file.read_bytes().replace(b"speed=42",b"speed=43"))
    else:
        run=before["run_id"]
        file=Path(config["owner"]).parent/"operations"/run/"release-progress.json"
        file.write_bytes(file.read_bytes()+b" ")
    assert child(tmp_path,"resume").returncode==2
    assert not (tmp_path/"result.json").exists()


def test_two_fresh_resumers_create_only_one_b_attempt(tmp_path):
    config=prepare(tmp_path)
    assert child(tmp_path,"release").returncode==73
    command=[sys.executable,str(Path(__file__).resolve()),str(tmp_path),"resume"]
    first=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    second=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    first.communicate(timeout=20);second.communicate(timeout=20)
    assert sorted([first.returncode,second.returncode])==[0,2]
    saved=snapshot(config)
    assert saved["jobs"]["r0-uncertainty"]["attempt_count"]==1
    assert saved["budget"]["attempts_used"]==4


@pytest.mark.parametrize("kind",["stage","a_acceptance"])
def test_terminal_raw_proof_edit_cannot_resume(tmp_path,kind):
    config=prepare(tmp_path)
    assert child(tmp_path,"terminal").returncode==75
    saved=snapshot(config)
    path=Path(config["owner"]).parent/"operations"/saved["run_id"]/"execution.sqlite"
    with sqlite3.connect(path) as conn:
        if kind=="stage":
            raw=conn.execute("SELECT stage_json FROM run_dependency_stages").fetchone()[0]
            stage=json.loads(raw);stage["actual_input_digest"]="0"*64
            conn.execute("UPDATE run_dependency_stages SET stage_json=?",(json.dumps(stage),))
        else:conn.execute("UPDATE jobs SET accepted_at=1001 WHERE job_id='r0-speed'")
    assert child(tmp_path,"resume").returncode==2


def test_damaged_stage_does_not_disable_owner_cancellation(tmp_path):
    config=prepare(tmp_path)
    assert child(tmp_path,"release").returncode==73
    saved=snapshot(config)
    path=Path(config["owner"]).parent/"operations"/saved["run_id"]/"execution.sqlite"
    with sqlite3.connect(path) as conn:conn.execute("UPDATE run_dependency_stages SET stage_json='broken'")
    cancellation=cancel_closed_loop(config["owner"],config["input"],clock=lambda:1000)
    assert cancellation["run_id"]==saved["run_id"]
    assert child(tmp_path,"resume").returncode==2



def test_durable_cancel_can_acquire_lock_while_b_backend_runs(tmp_path):
    config=prepare(tmp_path)
    result=child(tmp_path,"cancel_b")
    assert result.returncode==2 and "RUN_CANCELLED" in result.stderr
    saved=snapshot(config)
    assert saved["jobs"]["r0-speed"]["state"]=="accepted"
    assert saved["jobs"]["r0-uncertainty"]["attempt_count"]==1
    assert saved["jobs"]["r0-critic"]["attempt_count"]==0
    assert saved["cancellation"] is not None

def _child(root,mode):
    config=read_json(root/"control.json")
    payload=read_json(Path(config["input"]))
    backend=Calculation(payload,config["measure"])
    if mode=="release":
        old=SwarmState.commit_dependency_stage
        def commit(*a,**kw): old(*a,**kw);os._exit(73)
        SwarmState.commit_dependency_stage=commit
    elif mode=="leased":
        old=backend.produce
        def produce(value,*a,**kw):
            if "prerequisite" in value: os._exit(74)
            return old(value,*a,**kw)
        backend.produce=produce
    elif mode=="cancel_b":
        old=backend.produce
        def produce(value,*a,**kw):
            if "prerequisite" in value:
                cancel_closed_loop(config["owner"],config["input"],clock=lambda:1000)
            return old(value,*a,**kw)
        backend.produce=produce
    elif mode=="terminal":
        old=SwarmState.prepare_finalization
        def terminal(*a,**kw):old(*a,**kw);os._exit(75)
        SwarmState.prepare_finalization=terminal
    try:
        result=execute_closed_loop(config["owner"],config["input"],config["plan"],backend,
            worker_actors=config["actors"],clock=lambda:1000,resume_finalization=mode=="resume")
        (root/"result.json").write_text(json.dumps({"result":result,"calls":[
            item.get("job_id",item.get("core",{}).get("job_id")) for item in backend.inputs]}))
        return 0
    except SwarmError as exc:
        print(exc.code,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(_child(Path(sys.argv[1]),sys.argv[2]))
