"""Actual four-call dependency execution with independently calculated results."""
import copy
import hashlib
import json
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

from test_task_swarm_dependency_contract import dependency_setup
from test_task_swarm_closed_loop import execute, MeasuredBackend
from task_swarm.closed_loop_contract import loop_criteria
from task_swarm.protocol import SwarmError, digest
from task_swarm.task_runner import read_json
from test_task_swarm_objectives import span


def setup_dependency(tmp_path, *, budget=6, number=42):
    setup = dependency_setup(tmp_path)
    owner, file, document, payload, spec, _, measure = setup
    measure["text"] = measure["text"].replace("speed=42", f"speed={number}")
    measure["sha256"] = hashlib.sha256(measure["text"].encode()).hexdigest()
    payload["acceptance"].append(f"speed={number}")
    payload["objective"]["acceptance"].append(span(measure, f"speed={number}"))
    payload["objective"]["budget"]["attempt_budget"] = budget
    spec["parent_input_digest"] = digest(payload)
    shared = [key for key in loop_criteria(payload) if not key.startswith("A")]
    spec["jobs"][0]["criterion_ids"] = [*shared, "A1"]
    spec["jobs"][1]["criterion_ids"] = [*shared, "A2"]
    file.write_bytes(json.dumps(payload, ensure_ascii=False).encode())
    document["binding"]["context_digest"] = digest(payload)
    document["source_checks"][0]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    owner.write_bytes(json.dumps(document).encode())
    return setup


class Calculation(MeasuredBackend):
    def __init__(self, *args, blocked=False, wrong=False, **kw):
        super().__init__(*args, **kw)
        self.blocked, self.wrong = blocked, wrong

    def produce(self, delivered, directory, *, actor_ref, **kw):
        if "prerequisite" not in delivered:
            return super().produce(delivered, directory, actor_ref=actor_ref, **kw)
        x = int(delivered["prerequisite"]["report"]["claims"][0]["text"].split("=")[1])
        answer = x + (2 if self.wrong and delivered["round"] == 0 else 1)
        record = next(item for item in delivered["view"]["spans"] if item["text"].startswith("speed="))
        evidence = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
        return self.envelope(delivered, {"job_id":delivered["job_id"], "summary":f"derived={answer}",
            "conflicts":[], "claims":[{"text":f"derived={answer}", "status":"inference",
                "evidence":[{**evidence, "quote":record["text"]}]}]}, actor_ref)

    def review(self, delivered, directory, *, actor_ref, **kw):
        if "core" in delivered:
            result={"kind":"prerequisite_review","version":1,"descriptor_sha256":delivered["descriptor_sha256"],
                "report_sha256":delivered["report_sha256"], "validations":[{"criterion_id":key,
                    "status":"unknown" if self.blocked else "passed",
                    "evidence":[{"job_id":delivered["report"]["job_id"],"claim_index":0}]}
                    for key in delivered["core"]["gate"]]}
            return self.pre_envelope(delivered,result,actor_ref)
        reports=delivered["reports"]
        actual={value["job_id"]:value for value in self.inputs if "prerequisite" in value}
        assert delivered["prerequisite_inputs"]=={name:{"delivered_input_digest":digest(value),
            "prerequisite":value["prerequisite"]} for name,value in actual.items()}
        a=next(value for value in reports.values() if value["claims"][0]["text"].startswith("speed="))
        x=int(a["claims"][0]["text"].split("=")[1])
        dependent=[value for name,value in sorted(reports.items()) if value["claims"][0]["text"].startswith("derived=")]
        valid=int(dependent[-1]["claims"][0]["text"].split("=")[1])==x+1
        gap=next(item for item in delivered["view"]["spans"] if item["text"].startswith("speed="))
        gap={key:gap[key] for key in ("source_key","source_revision","start","end")}
        validations=[]
        for key, assigned in delivered["required_evidence_jobs"].items():
            failed=key=="A2" and not valid
            validations.append({"criterion_id":key,"status":"failed" if failed else "passed",
                "evidence":[] if failed else [{"job_id":job,"claim_index":0} for job in assigned],
                "gap_reason":"independent arithmetic mismatch" if failed else None,
                "source_spans":[gap] if failed else []})
        return self.envelope(delivered,{"parent_input_digest":digest(self.payload),
            "plan_digest":delivered["view"]["plan_digest"], "round":delivered["round"],
            "report_digests":{key:digest(value) for key,value in reports.items()},"validations":validations},actor_ref)

    def pre_envelope(self, delivered, result, actor):
        self.inputs.append(copy.deepcopy(delivered))
        return {"result":result,"receipt":{"actor_ref":actor,"invocation_ref":"synthetic-prerequisite",
                "input_digest":digest(delivered),"synthetic":True}}


def test_four_call_derived_input_and_anchored_replay(tmp_path):
    setup=setup_dependency(tmp_path)
    backend=Calculation(setup[3],setup[6])
    result=execute(setup,backend)
    assert result["receipt"]["version"]==3 and result["receipt"]["review_passed"]
    assert len(backend.inputs)==4
    b=next(value for value in backend.inputs if "prerequisite" in value)
    assert b["prerequisite"]["report"]["claims"][0]["text"]=="speed=42"
    assert any(item["claim"]["text"]=="derived=43" for item in result["candidate"]["claims"])
    assert execute(setup,backend,expected_receipt_sha256=result["receipt_sha256"])["duplicate"]
    assert len(backend.inputs)==4


def test_blocked_retries_do_not_dispatch_or_create_receipt(tmp_path):
    setup=setup_dependency(tmp_path)
    backend=Calculation(setup[3],setup[6],blocked=True)
    first=execute(setup,backend)
    assert first["error"]=="LOOP_PREREQUISITE_BLOCKED" and first["receipt"] is None
    assert len(backend.inputs)==2
    assert execute(setup,backend)==first
    assert execute(setup,backend,resume_finalization=True)==first
    assert len(backend.inputs)==2


def test_b_local_repair_uses_same_a_and_six_calls(tmp_path):
    setup=setup_dependency(tmp_path)
    backend=Calculation(setup[3],setup[6],wrong=True)
    result=execute(setup,backend)
    assert result["receipt"]["review_passed"] and len(backend.inputs)==6
    assert result["receipt"]["budget"]["remaining_attempts"]==0


@pytest.mark.parametrize("number", [42, 73])
def test_input_value_changes_actual_delivery_and_independent_answer(tmp_path,number):
    setup=setup_dependency(tmp_path,number=number)
    # A's dependency identity remains authoritative when lexical input order changes.
    setup[4]["jobs"].reverse()
    backend=Calculation(setup[3],setup[6])
    result=execute(setup,backend)
    assert any(item["claim"]["text"]==f"derived={number+1}" for item in result["candidate"]["claims"])
    inputs=[item for item in backend.inputs if "prerequisite" in item]
    assert len(inputs)==1 and f"speed={number}" in json.dumps(inputs[0])


@pytest.mark.parametrize("budget", [4,5])
def test_b_gap_cannot_exceed_original_budget(tmp_path,budget):
    setup=setup_dependency(tmp_path,budget=budget)
    backend=Calculation(setup[3],setup[6],wrong=True)
    result=execute(setup,backend)
    assert len(backend.inputs)==4 and result["learning_candidate"] is None
    assert result["candidate"]["stop_reason"]=="attempt_budget_exhausted"


@pytest.mark.parametrize("mode",["inference","conflict","gate","a_gap"])
def test_prerequisite_and_shared_repair_boundaries(tmp_path,mode):
    setup=setup_dependency(tmp_path)
    class Backend(Calculation):
        def produce(self,delivered,*args,**kw):
            response=super().produce(delivered,*args,**kw)
            if "prerequisite" not in delivered:
                if mode=="inference":response["result"]["claims"][0]["status"]="inference"
                if mode=="conflict":response["result"]["conflicts"]=["unresolved measurement disagreement"]
            return response
        def review(self,delivered,*args,**kw):
            response=super().review(delivered,*args,**kw)
            if mode=="gate" and "core" in delivered:response["result"]["validations"]=[]
            if mode=="a_gap" and "core" not in delivered:
                item=next(v for v in response["result"]["validations"] if v["criterion_id"]=="A1")
                record=next(row for row in delivered["view"]["spans"] if row["text"].startswith("speed="))
                item.update(status="failed",evidence=[],gap_reason="A contradiction",
                    source_spans=[{key:record[key] for key in ("source_key","source_revision","start","end")}])
            return response
    backend=Backend(setup[3],setup[6])
    if mode=="gate":
        with pytest.raises(SwarmError,match="LOOP_PREREQUISITE_GATE"):execute(setup,backend)
        assert len(backend.inputs)==2
    else:
        result=execute(setup,backend)
        if mode=="a_gap":
            assert result["candidate"]["stop_reason"]=="dependency_repair_unsupported"
            assert result["learning_candidate"] is None and len(backend.inputs)==4
        else:
            assert result["status"]=="blocked" and len(backend.inputs)==2


def test_impossible_four_call_budget_refuses_before_reserving_run_directory(tmp_path):
    setup=setup_dependency(tmp_path,budget=3)
    backend=Calculation(setup[3],setup[6])
    with pytest.raises(SwarmError,match="INVALID_LIMIT"):
        execute(setup,backend)
    assert backend.inputs==[]
    assert list((setup[0].parent/"operations").iterdir())==[]


from test_task_swarm_learning_reuse import setup_reuse, ReadingBackend, allow, save
from task_swarm.learning_reuse import ReuseOwner
from task_swarm.repair_planning import inspect_repair


class LearningDependencyBackend(ReadingBackend):
    def review(self, delivered, directory, *, actor_ref, **kwargs):
        if 'core' in delivered:
            result = {'kind': 'prerequisite_review', 'version': 1,
                'descriptor_sha256': delivered['descriptor_sha256'], 'report_sha256': delivered['report_sha256'],
                'validations': [{'criterion_id': key, 'status': 'passed',
                    'evidence': [{'job_id': delivered['report']['job_id'], 'claim_index': 0}]}
                    for key in delivered['core']['gate']]}
            self.calls.append('prerequisite_review')
            return {'result': result, 'receipt': {'actor_ref': actor_ref, 'invocation_ref': 'reading-prerequisite',
                'input_digest': digest(delivered), 'synthetic': True}}
        response = super().review(delivered, directory, actor_ref=actor_ref, **kwargs)
        for item in response['result']['validations']:
            item['evidence'] = [{'job_id': name, 'claim_index': 0}
                                for name in delivered['required_evidence_jobs'][item['criterion_id']]]
        return response



@pytest.mark.parametrize("lane", ["revoked", "allowed", "missing", "changed"])
def test_precheckpoint_profile2_learning_has_db_bound_release_context(tmp_path, monkeypatch, lane):
    # Configure the synthetic original objective before its actual writer runs.
    # No existing receipt, goal, test assertion or owner decision is rewritten.
    import test_task_swarm_learning_reuse as reuse_fixture
    original_setup = reuse_fixture.setup_loop
    def extra_acceptance(*args, **kw):
        setup = original_setup(*args, **kw)
        current = next(s for s in setup[3]['sources'] if s['key'] == 'a' * 64 and s['revision'] == 2)
        setup[3]['acceptance'].append('未解決点を示す')
        setup[3]['objective']['acceptance'].append(span(current, '未解決点を示す'))
        setup[4]['jobs'][0]['criterion_ids'] = list(loop_criteria(setup[3]))
        return setup
    monkeypatch.setattr(reuse_fixture, 'setup_loop', extra_acceptance)
    _, arguments, plan, payload, document, _ = setup_reuse(tmp_path, observation=17)
    payload['objective']['budget']['attempt_budget'] = 6
    save(Path(arguments['target_input']), payload)
    document['binding']['context_digest'] = digest(payload)
    document['learning_reuse']['target_context_digest'] = digest(payload)
    document['source_checks'][0]['sha256'] = hashlib.sha256(Path(arguments['target_input']).read_bytes()).hexdigest()
    document['actors']['worker-b'] = {**document['actors']['worker-a'], 'invocation_ref': 'invocation-worker-b'}
    save(Path(arguments['target_owner']), document)
    reuse = ReuseOwner(**arguments, clock=lambda: 1000)
    decision = allow(reuse)
    a = {**copy.deepcopy(plan['jobs'][0]), 'requires': [],
         'criterion_ids': [key for key in loop_criteria(payload) if key != 'A2']}
    b = {**copy.deepcopy(a), 'job_id': 'consume-memory', 'requires': [a['job_id']],
         'criterion_ids': [key for key in loop_criteria(payload) if key != 'A1']}
    plan = {**plan, 'parent_input_digest': digest(payload), 'version': 2, 'jobs': [a, b]}
    class GapBackend(LearningDependencyBackend):
        def produce(self, delivered, directory, *, actor_ref, **kw):
            result = super().produce(delivered, directory, actor_ref=actor_ref, **kw)
            if 'prerequisite' in delivered:
                result['result']['summary'] = 'Use measured memory budget 0.'
                result['result']['claims'][0]['text'] = result['result']['summary']
            return result
        def review(self, delivered, directory, *, actor_ref, **kw):
            if 'core' in delivered:
                return super().review(delivered, directory, actor_ref=actor_ref, **kw)
            response = super().review(delivered, directory, actor_ref=actor_ref, **kw)
            _, _, record = self.observed(delivered)
            for item in response['result']['validations']:
                failed = item['criterion_id'] == 'A2'
                item.update(status='failed' if failed else 'passed',
                    evidence=[] if failed else [{'job_id': name, 'claim_index': 0}
                        for name in delivered['required_evidence_jobs'][item['criterion_id']]],
                    gap_reason='The dependent ignored the actually observed memory.' if failed else None,
                    source_spans=[{k:record[k] for k in ('source_key','source_revision','start','end')}] if failed else [])
            return response
    backend = GapBackend()
    interrupted = LookupError('owned stop after the real r0 report before a repair/checkpoint')
    def stop_before_repair(gap):
        assert gap['failed_criteria'] == ['A2']
        raise interrupted
    with pytest.raises(LookupError) as caught:
        reuse.execute(digest(decision), plan, backend, worker_actors=['worker-a', 'worker-b'], repair_planner=stop_before_repair)
    assert caught.value is interrupted and len(backend.calls) == 4
    run_id = 'task-run-' + digest([payload['task_id'], payload['revision']])[:32]
    directory = Path(arguments['target_owner']).parent / 'operations' / run_id
    from task_swarm.owner_file import OwnerFile
    from task_swarm.state import SwarmState
    from task_swarm.task_runner import read_json
    owner = OwnerFile(arguments['target_owner'], clock=lambda: 1000)
    state = SwarmState(directory/'execution.sqlite', owner.read_task, clock=lambda: 1000)
    assert state.finalization(run_id) is None
    progress, progress_sha = read_json(directory/'release-progress.json', with_digest=True)
    assert state.dependency_stage(run_id)['certificate']['progress_sha256'] == progress_sha
    assert progress['metadata']['reuse_context'] is not None
    assert 'context-binding.json' in progress['artifacts']
    if lane != 'allowed':
        reuse.decide('ref/owner/fixture', 'ref/review/one-learning', 'revoke',
            'ref/decision/revoke-precheckpoint', expected_generation=1)
        with pytest.raises(SwarmError, match='REUSE_DECISION_STALE'):
            reuse.current(digest(decision))
    del document['learning_reuse']
    save(Path(arguments['target_owner']), document)
    (directory/'context-binding.json').unlink()
    error = 'LOOP_REUSE_INSPECTION_UNSUPPORTED'
    if lane == 'missing':
        (directory/'release-progress.json').unlink()
    elif lane == 'changed':
        progress['metadata']['reuse_context'] = None
        progress['metadata']['context_binding_digest'] = digest(None)
        progress['artifacts'].pop('context-binding.json')
        (directory/'release-progress.json').write_bytes(json.dumps(progress).encode('utf-8'))
        error = 'LOOP_RELEASE_CHANGED'
    before = {p.name:p.read_bytes() for p in directory.iterdir() if p.is_file()}
    if lane == 'missing':
        with pytest.raises(FileNotFoundError):
            inspect_repair(arguments['target_owner'], arguments['target_input'], clock=lambda: 1000)
    else:
        with pytest.raises(SwarmError, match=error):
            inspect_repair(arguments['target_owner'], arguments['target_input'], clock=lambda: 1000)
    assert {p.name:p.read_bytes() for p in directory.iterdir() if p.is_file()} == before
    assert len(backend.calls) == 4


def test_precheckpoint_profile2_without_learning_remains_inspectable(tmp_path):
    setup = setup_dependency(tmp_path)
    backend = Calculation(setup[3], setup[6], wrong=True)
    stopped = LookupError("stop before repair with nonlearning released evidence")
    def stop_before_repair(gap):
        raise stopped
    with pytest.raises(LookupError) as caught:
        execute(setup, backend, repair_planner=stop_before_repair)
    assert caught.value is stopped and len(backend.inputs) == 4
    run_id = "task-run-" + digest([setup[3]["task_id"], setup[3]["revision"]])[:32]
    directory = setup[0].parent / "operations" / run_id
    before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    value = inspect_repair(setup[0], setup[1], clock=lambda: 1000)
    assert value["admitted"] is False and value["impact"]["version"] == 2
    assert {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()} == before
    assert len(backend.inputs) == 4
