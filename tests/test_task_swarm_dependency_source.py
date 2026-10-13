"""Source-derived edge and complete ancestor context; no caller-chosen subset."""
from pathlib import Path
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1]/"tools")]
from test_knowledge_task_frontier import fixture, graph
from test_knowledge_task_input import STAMP, admit
from kotodama_kb.task_input import compile_task_input, verify_task_input
from runtime.task_swarm.dependency_contract import descriptor
from runtime.task_swarm.protocol import SwarmError


def test_source_edge_compiles_rederives_and_preserves_root_assignment(tmp_path):
    spec=graph(two=True)
    spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    bundle, seed, owner, file, _=fixture(tmp_path,spec)
    candidate=compile_task_input(bundle,seed,owner,clock=lambda:STAMP)
    plan=candidate["supplied_plan"]
    assert plan["version"]==2
    desc,_=descriptor(candidate["payload"],plan)
    assert len(desc["gate"])==1
    criteria=candidate["diagnostics"]["frontier"]["criteria"]
    assert len(criteria[0]["leaf_requirement_ids"])==2
    assert criteria[1]["criterion_id"] in desc["gate"]
    admit(candidate,owner,file)
    assert verify_task_input(bundle,candidate,owner,clock=lambda:STAMP)==candidate["payload"]
    candidate["supplied_plan"]["jobs"].reverse()
    with pytest.raises(SwarmError):
        verify_task_input(bundle,candidate,owner,clock=lambda:STAMP)


@pytest.mark.parametrize("case",["cycle","self","outside","root_edge"])
def test_source_dependency_does_not_expand_bounded_frontier(tmp_path,case):
    spec=graph(two=True)
    spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    if case=="cycle":spec["REQ-LATENCY"]["requires"]=["REQ-RSS"]
    if case=="self":spec["REQ-RSS"]["requires"]=["REQ-RSS"]
    if case=="outside":spec["REQ-RSS"]["requires"]=["REQ-OUTSIDE"]
    if case=="root_edge":spec["REQ-ROOT"]["requires"]=["REQ-LATENCY"]
    bundle,seed,owner,_,_=fixture(tmp_path,spec)
    with pytest.raises(SwarmError):compile_task_input(bundle,seed,owner,clock=lambda:STAMP)


class SourceCalculation:
    """A quotes its Source; B computes f(A, B Source); critic recomputes independently."""
    synthetic=True

    def __init__(self):self.inputs=[]

    def response(self,delivered,result,actor):
        import copy
        from runtime.task_swarm.closed_loop import ScriptedSimulation
        self.inputs.append(copy.deepcopy(delivered))
        return ScriptedSimulation._response(delivered,result,actor)

    def produce(self,delivered,directory,*,actor_ref,**kwargs):
        import json
        from runtime.task_swarm.protocol import canonical
        record=next(row for row in delivered["view"]["spans"] if row["text"]==delivered["purpose"])
        evidence={key:record[key] for key in ("source_key","source_revision","start","end")}
        text,status=delivered["purpose"],"supported"
        if "prerequisite" in delivered:
            a=json.loads(delivered["prerequisite"]["report"]["claims"][0]["text"].split(" DATA=",1)[1])
            b=json.loads(delivered["purpose"].split(" DATA=",1)[1])
            text=canonical({"combined":sorted(a["values"])[18]+max(x for x in b["values"] if x is not None)})
            status="inference"
        return self.response(delivered,{"job_id":delivered["job_id"],"summary":text,"conflicts":[],
            "claims":[{"text":text,"status":status,"evidence":[{**evidence,"quote":record["text"]}]}]},actor_ref)

    def review(self,delivered,directory,*,actor_ref,**kwargs):
        import json
        from runtime.task_swarm.protocol import canonical,digest
        if "core" in delivered:
            result={"kind":"prerequisite_review","version":1,"descriptor_sha256":delivered["descriptor_sha256"],
                "report_sha256":delivered["report_sha256"],"validations":[{"criterion_id":key,"status":"passed",
                "evidence":[{"job_id":delivered["report"]["job_id"],"claim_index":0}]} for key in delivered["core"]["gate"]]}
        else:
            if "job_id" in delivered:
                actual={value["job_id"]:value for value in self.inputs if "prerequisite" in value}
                assert delivered["prerequisite_inputs"]=={name:{"delivered_input_digest":digest(value),
                    "prerequisite":value["prerequisite"]} for name,value in actual.items()}
            data=[json.loads(row["text"].split(" DATA=",1)[1]) for row in delivered["view"]["spans"] if row["text"].startswith("[REQ-") and " DATA=" in row["text"]]
            a=next(row for row in data if row["operation"]=="latency")
            b=next(row for row in data if row["operation"]=="rss")
            # Distinct calculation from B: discrete percentile plus descending peak.
            import math
            expected=canonical({"combined":sorted(a["values"])[math.ceil(.95*len(a["values"]))-1]+sorted(x for x in b["values"] if x is not None)[-1]})
            assert any(row["claims"][0]["text"]==expected for row in delivered["reports"].values())
            result={"parent_input_digest":delivered["view"]["parent_input_digest"],"plan_digest":delivered["view"]["plan_digest"],
                "round":0,"report_digests":delivered["report_digests"],"validations":[{"criterion_id":key,"status":"passed",
                    "evidence":[{"job_id":job,"claim_index":0} for job in assigned],"gap_reason":None,"source_spans":[]}
                    for key,assigned in delivered["required_evidence_jobs"].items()]}
        return self.response(delivered,result,actor_ref)


@pytest.mark.parametrize("corrected,expected",[(False,115),(True,147)])
def test_source_edge_reaches_real_b_with_changed_arithmetic(tmp_path,corrected,expected):
    from kotodama_kb.task_input import execute_task_input
    spec=graph(two=True,corrected=corrected);spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    bundle,seed,owner,file,_=fixture(tmp_path,spec,corrected=corrected)
    candidate=compile_task_input(bundle,seed,owner,clock=lambda:STAMP)
    admit(candidate,owner,file)
    before=owner.read_bytes()
    backend=SourceCalculation()
    result=execute_task_input(bundle,candidate,owner,file,backend,worker_actors=["worker-a","worker-b"],clock=lambda:STAMP)
    assert len(backend.inputs)==4 and result["receipt"]["version"]==3
    assert any(row["claim"]["text"]=='{"combined":'+str(expected)+'}' for row in result["candidate"]["claims"])
    assert owner.read_bytes()==before


@pytest.mark.parametrize("blocked",[False,True])
def test_source_cli_in_separate_process_preserves_owner_and_exit_contract(tmp_path,blocked):
    import hashlib
    import json
    import subprocess
    import time
    from test_knowledge_task_input import change_declaration,reseal_seed
    from runtime.task_swarm.closed_loop import ScriptedSimulation
    from runtime.task_swarm.closed_loop_contract import work_input,required_evidence_jobs
    from runtime.task_swarm.closed_loop_context import derive_child_view
    from runtime.task_swarm.dependency_contract import review_input
    from runtime.task_swarm.protocol import canonical,digest
    spec=graph(two=True);spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    _,seed,owner,file,_=fixture(tmp_path,spec)
    change_declaration(seed,tmp_path,lambda declaration:declaration["budget"].update(deadline=time.time()+600))
    reseal_seed(seed,owner,file)
    document=json.loads(owner.read_bytes());document["binding"]["expires_at"]=time.time()+900
    owner.write_bytes(json.dumps(document).encode())
    cwd=tmp_path/"outside";cwd.mkdir()
    entry=Path(__file__).resolve().parents[1]/"tools/knowledge_base.py"
    def command(operation,*args,code=0):
        process=subprocess.run([sys.executable,"-I","-B",str(entry),"task-input",operation,
            "--root",str(tmp_path),"--owner",str(owner),*map(str,args)],cwd=cwd,
            capture_output=True,text=True,encoding="utf-8",timeout=30)
        assert process.returncode==code,process.stderr
        assert not process.stderr
        return json.loads(process.stdout)
    candidate=command("compile","--input",file)
    path=tmp_path/"candidate.json";path.write_bytes((canonical(candidate)+"\n").encode())
    admit(candidate,owner,file)
    payload,plan=candidate["payload"],candidate["supplied_plan"]
    desc,envelope=descriptor(payload,plan)
    jobs={"r0-"+job["job_id"]:job for job in plan["jobs"]}
    a,b=desc["a_job_id"],desc["b_job_id"]
    delivered={key:work_input(payload,job,0,digest(plan),round_plan_digest=digest(plan)) for key,job in jobs.items()}
    actors={key:actor for key,actor in zip(sorted(jobs),["worker-a","worker-b"])}
    backend=SourceCalculation()
    response=backend.produce(delivered[a],cwd,actor_ref=actors[a])
    reports={a:response["result"]}
    sha=hashlib.sha256((canonical(response)+"\n").encode()).hexdigest()
    prerequisite=backend.review(review_input(envelope,reports[a],sha),cwd,actor_ref="verifier")["result"]
    if blocked:prerequisite["validations"][0]["status"]="unknown"
    reports[b]=backend.produce({**delivered[b],"prerequisite":{"report":reports[a]}},cwd,actor_ref=actors[b])["result"]
    view=derive_child_view(payload,"r0-critic",[span for job in jobs.values() for span in job["selected_spans"]],plan_digest=digest(plan))
    review=backend.review({"view":view,"reports":reports,"report_digests":{key:digest(value) for key,value in reports.items()},
        "required_evidence_jobs":required_evidence_jobs(payload,plan)},cwd,actor_ref="verifier")["result"]
    scenario={"work":reports,"critics":{"prerequisite":prerequisite,"0":review},"repair_plan":None}
    simulation=tmp_path/"simulation.json";simulation.write_bytes(canonical(scenario).encode())
    before=owner.read_bytes()
    args=("--candidate",path,"--input",file,"--simulation",simulation,"--worker","worker-a","--worker","worker-b")
    result=command("simulate",*args,code=3 if blocked else 0)
    assert owner.read_bytes()==before
    if blocked:
        assert result["error"]=="LOOP_PREREQUISITE_BLOCKED" and result["receipt"] is None
        assert command("simulate",*args,code=3)==result
    else:
        assert result["receipt"]["version"]==3
        assert command("simulate",*args,"--receipt-sha256",result["receipt_sha256"])["duplicate"]


@pytest.mark.parametrize("change",["hidden","missing","reversed"])
def test_source_entry_rederives_edges_before_any_backend_call(tmp_path,change):
    from copy import deepcopy
    from kotodama_kb.task_input import execute_task_input
    spec=graph(two=True);spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    bundle,seed,owner,file,_=fixture(tmp_path,spec)
    candidate=compile_task_input(bundle,seed,owner,clock=lambda:STAMP)
    admit(candidate,owner,file)
    altered=deepcopy(candidate)
    jobs=altered["supplied_plan"]["jobs"]
    a=next(job for job in jobs if not job["requires"])
    b=next(job for job in jobs if job["requires"])
    if change=="hidden":
        altered["supplied_plan"]["version"]=1
        for job in jobs:job.pop("requires")
    elif change=="missing":b["requires"]=[]
    else:a["requires"],b["requires"]=[b["job_id"]],[]
    backend=SourceCalculation()
    with pytest.raises(SwarmError):
        execute_task_input(bundle,altered,owner,file,backend,worker_actors=["worker-a","worker-b"],clock=lambda:STAMP)
    assert backend.inputs==[]


def test_source_compiler_refuses_impossible_dependency_budget(tmp_path):
    from test_knowledge_task_input import change_declaration,reseal_seed
    spec=graph(two=True);spec["REQ-RSS"]["requires"]=["REQ-LATENCY"]
    bundle,seed,owner,file,_=fixture(tmp_path,spec)
    change_declaration(seed,tmp_path,lambda declaration:declaration["budget"].update(attempt_budget=3))
    reseal_seed(seed,owner,file)
    before=owner.read_bytes(),file.read_bytes()
    with pytest.raises(SwarmError,match="INVALID_LIMIT"):
        compile_task_input(bundle,seed,owner,clock=lambda:STAMP)
    assert (owner.read_bytes(),file.read_bytes())==before
