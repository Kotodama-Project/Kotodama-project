"""Synthetic, content-free metric snapshots; no human acceptance is fabricated."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import intent_metric as metric
from intent_outcome_computation import digest,MetricRefused


def case(suffix='a'):
    ref=lambda kind:f'ref/{kind}/synthetic-{suffix}'
    request=hashlib.sha256(('synthetic-request-'+suffix).encode()).hexdigest()
    source_hash=hashlib.sha256(('synthetic-source-'+suffix).encode()).hexdigest()
    outcome_hash=hashlib.sha256(('synthetic-outcome-'+suffix).encode()).hexdigest()
    owner='ref/actor/synthetic-owner';revision=ref('intent-revision')
    return {'case_ref':ref('case'),'history_ref':ref('history'),'owner_ref':owner,'goal_ref':'OUT-INTENT',
        'intent_ref':ref('intent'),'intent_revision_ref':revision,'request_sha256':request,'due_at':'2026-09-15T00:00:00Z','admitted':True,'admitted_at':'2026-09-02T00:00:00Z','state':'completed',
        'source':{'ref':ref('source'),'revision_ref':ref('source-revision'),'sha256':source_hash},
        'intent_review':{'receipt_ref':ref('intent-review'),'reviewer_ref':owner,'intent_ref':ref('intent'),'intent_revision_ref':revision,'source_ref':ref('source'),'source_revision_ref':ref('source-revision'),'source_sha256':source_hash,'request_sha256':request,'reviewed_at':'2026-09-03T00:00:00Z'},
        'work':{'receipt_ref':ref('execution'),'work_order_ref':ref('order'),'grant_ref':ref('grant'),'executor_ref':'ref/actor/synthetic-executor','intent_revision_ref':revision,'request_sha256':request,'started_at':'2026-09-04T00:00:00Z','grant_issued_at':'2026-09-03T00:00:00Z','grant_expires_at':'2026-09-05T00:00:00Z','scope_matched':True},
        'outcome':{'ref':ref('outcome'),'sha256':outcome_hash,'request_sha256':request},
        'verification':{'receipt_ref':ref('verification'),'reviewer_ref':'ref/actor/synthetic-independent','outcome_sha256':outcome_hash,'intent_revision_ref':revision,'verdict':'pass','verified_at':'2026-09-05T00:00:00Z'},
        'acceptance':{'receipt_ref':ref('acceptance'),'owner_ref':owner,'outcome_sha256':outcome_hash,'request_sha256':request,'verdict':'accepted','requested_outcome_met':True,'accepted_at':'2026-09-06T00:00:00Z','mode':'owner','policy_ref':None,'policy_revision_ref':None,'policy_adoption_receipt_ref':None},
        'learning':{'receipt_ref':ref('learning'),'intent_revision_ref':revision,'disposition':'retained','recorded_at':'2026-09-07T00:00:00Z'},
        'exclusion':None,'violations':[],'kpi_change':'unknown','outcome_change':'unknown'}


def snapshot(*cases):
    return {'kind':'kotodama.intent-outcome-snapshot','schema_revision':'v1','snapshot_ref':'ref/snapshot/synthetic','snapshot_revision_ref':'ref/snapshot-revision/synthetic',
        'parameters':{'metric_id':'KGI-INTENT','window_start':'2026-09-01T00:00:00Z','window_end':'2026-10-01T00:00:00Z','exclusion_mode':'receipted_withdrawal_or_cancel'},
        'coverage':{'status':'synthetic_full','owner_ref':'ref/actor/synthetic-owner','receipt_ref':'ref/coverage/synthetic'},'cases':list(cases),'contains_content':False}


class IntentMetricTests(unittest.TestCase):
    def result(self,*cases):return metric.compute(snapshot(*cases))['result']

    def test_complete_case_is_deterministic_without_adoption_or_authenticated_evidence(self):
        value=snapshot(case());first=metric.compute(value);second=metric.compute(copy.deepcopy(value))
        self.assertEqual(first,second);self.assertEqual({'numerator':1,'denominator':1},first['result']['ratio'])
        self.assertFalse(any(first['claims'].values()));self.assertEqual('UNVERIFIED',first['result']['evidence_authenticity'])
        self.assertEqual('PASS',metric.attest(value,first)['status']);self.assertNotIn('ref/case/synthetic-a',json.dumps(first))

    def test_missing_proof_or_artifact_alone_never_substitutes_for_the_requested_outcome(self):
        for key in ('source','intent_review','work','outcome','verification','acceptance','learning'):
            row=case();row[key]=None;result=self.result(row)
            self.assertEqual(0,result['counts']['numerator'],key);self.assertEqual(1,result['counts']['denominator'])
        for state in ('active','failed','rejected','inconclusive'):
            row=case();row['state']=state;self.assertEqual(0,self.result(row)['counts']['numerator'])

    def test_source_intent_scope_actor_outcome_time_and_learning_bindings_are_required(self):
        changes=[('intent_review','source_ref','ref/source/other'),('intent_review','source_revision_ref','ref/source-revision/other'),('intent_review','intent_ref','ref/intent/other'),
            ('intent_review','intent_revision_ref','ref/intent-revision/other'),('intent_review','source_sha256','f'*64),('work','scope_matched',False),('work','request_sha256','f'*64),
            ('verification','reviewer_ref','ref/actor/synthetic-executor'),('verification','outcome_sha256','f'*64),('verification','verdict','inconclusive'),
            ('acceptance','owner_ref','ref/actor/other'),('acceptance','requested_outcome_met',False),('acceptance','outcome_sha256','f'*64),
            ('work','grant_expires_at','2026-09-04T00:00:00Z'),('acceptance','accepted_at','2026-09-04T00:00:00Z'),('learning','recorded_at','2026-10-02T00:00:00Z'),('learning','intent_revision_ref','ref/intent-revision/other')]
        for section,key,value in changes:
            with self.subTest(section=section,key=key):
                row=case();row[section][key]=value;self.assertEqual(0,self.result(row)['counts']['numerator'])

    def test_only_matching_receipted_exclusion_can_remove_a_cancelled_case(self):
        row=case();row['state']='cancelled';result=self.result(row)
        self.assertEqual(1,result['counts']['denominator']);self.assertEqual('REVIEW_REQUIRED',result['disposition'])
        row['exclusion']={'receipt_ref':'ref/exclusion/synthetic-a','owner_ref':row['owner_ref'],'intent_revision_ref':row['intent_revision_ref'],'reason_ref':'ref/reason/synthetic-a','action':'cancelled','recorded_at':'2026-09-08T00:00:00Z'}
        result=self.result(row);self.assertEqual(1,result['counts']['excluded']);self.assertIsNone(result['ratio']);self.assertEqual('NOT_MEASURED',result['disposition'])
        for key,value in [('owner_ref','ref/actor/other'),('intent_revision_ref','ref/intent-revision/other'),('recorded_at','2026-08-01T00:00:00Z')]:
            bad=copy.deepcopy(row);bad['exclusion'][key]=value;self.assertEqual(1,self.result(bad)['counts']['denominator'])
        value=snapshot(row);value['parameters']['exclusion_mode']='none';self.assertEqual(1,metric.compute(value)['result']['counts']['denominator'])

    def test_adopted_acceptance_policy_requires_all_explicit_references(self):
        row=case();row['acceptance']['mode']='adopted_policy';self.assertEqual(0,self.result(row)['counts']['numerator'])
        row['acceptance'].update(policy_ref='ref/policy/synthetic',policy_revision_ref='ref/policy-revision/synthetic',policy_adoption_receipt_ref='ref/policy-adoption/synthetic')
        self.assertEqual(1,self.result(row)['counts']['numerator']);self.assertFalse(self.result(row)['measurement_policy_adopted'])

    def test_duplicates_and_conflicting_receipts_are_refused_instead_of_inflating_counts(self):
        for key in ('case_ref','intent_ref','intent_revision_ref'):
            a,b=case('a'),case('b');b[key]=a[key]
            with self.assertRaisesRegex(MetricRefused,'DUPLICATE'):metric.compute(snapshot(a,b))
        a,b=case('a'),case('b');b['outcome']['ref']=a['outcome']['ref']
        with self.assertRaisesRegex(MetricRefused,'OUTCOME_REUSED'):metric.compute(snapshot(a,b))
        b=case('b');b['acceptance']['receipt_ref']=a['acceptance']['receipt_ref']
        with self.assertRaisesRegex(MetricRefused,'RECEIPT_BINDING_CONFLICT'):metric.compute(snapshot(a,b))

    def test_hard_guardrails_and_proxy_only_improvements_cannot_be_averaged_away(self):
        good,bad=case('good'),case('bad');bad['violations']=['authority'];result=self.result(good,bad)
        self.assertEqual('HARD_GUARDRAIL_FAILURE',result['disposition']);self.assertEqual(1,result['counts']['numerator']);self.assertEqual(2,result['counts']['denominator'])
        bad=case('proxy');bad.update(kpi_change='improved',outcome_change='unchanged');self.assertEqual('REVIEW_REQUIRED',self.result(good,bad)['disposition'])
        bad['due_at']='2026-11-01T00:00:00Z';bad['violations']=['unsafe_rollback'];self.assertEqual('FAIL',self.result(good,bad)['guardrail'])

    def test_window_boundaries_and_zero_denominator_are_explicit(self):
        self.assertIsNone(self.result()['ratio']);self.assertEqual('NOT_MEASURED',self.result()['disposition'])
        a,b=case('start'),case('end');a['due_at']='2026-09-01T00:00:00Z';b['due_at']='2026-10-01T00:00:00Z'
        result=self.result(a,b);self.assertEqual(1,result['counts']['denominator']);self.assertEqual(1,result['counts']['outside_window_or_unadmitted'])

    def test_unknown_parameters_private_fields_and_wrong_goal_ids_are_refused(self):
        for change in (lambda v:v['parameters'].update(other=True),lambda v:v.update(private_text='SYNTHETIC_PRIVATE'),lambda v:v['cases'][0].update(goal_ref='OUT-UNKNOWN'),lambda v:v.update(contains_content=0)):
            value=snapshot(case());change(value)
            with self.assertRaises(MetricRefused):metric.compute(value)

    def test_receipt_input_code_binding_exclusion_and_result_mutations_fail_attestation(self):
        value=snapshot(case());receipt=metric.compute(value)
        changes=[lambda r:r.update(computation_revision='f'*64),lambda r:r['artifact_sha256'].update({'tools/intent_outcome_computation.py':'f'*64}),
            lambda r:r.update(parameter_binding_sha256='f'*64),lambda r:r['result']['counts'].update(numerator=2),lambda r:r['result']['id_set_sha256'].update(excluded='f'*64),lambda r:r['claims'].update(authority_granted=0)]
        for change in changes:
            altered=copy.deepcopy(receipt);change(altered)
            with self.assertRaisesRegex(MetricRefused,'RECEIPT_MISMATCH'):metric.attest(value,altered)
        altered=copy.deepcopy(value);altered['cases'][0]['state']='failed'
        with self.assertRaisesRegex(MetricRefused,'RECEIPT_MISMATCH'):metric.attest(altered,receipt)

    def test_computation_and_definition_byte_mutations_fail_current_attestation(self):
        value=snapshot(case());receipt=metric.compute(value);bundle=metric.load_bundle(ROOT)
        for relative in ('tools/intent_outcome_computation.py','knowledge/computations/intent-outcome.md','schemas/intent-outcome-snapshot.schema.json'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for name,_ in bundle.input_bindings:
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
                self.assertEqual('PASS',metric.attest(value,receipt,root=root)['status'])
                target=root/relative;target.write_bytes(target.read_bytes()+b'\n ')
                with self.assertRaises((MetricRefused,metric.KnowledgeBaseError)):
                    metric.attest(value,receipt,root=root)

    def test_mutating_the_callers_object_cannot_relabel_the_evaluated_snapshot(self):
        value=snapshot(case());before=copy.deepcopy(value);original=metric.evaluate
        def alter_caller(admitted):
            value['cases'][0]['state']='failed'
            return original(admitted)
        with mock.patch.object(metric,'evaluate',alter_caller):receipt=metric.compute(value)
        self.assertEqual(digest(before),receipt['input_snapshot_sha256']);self.assertEqual(1,receipt['result']['counts']['numerator'])
        self.assertEqual('PASS',metric.attest(before,receipt)['status'])

    def test_real_cli_is_read_only_and_does_not_echo_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'snapshot.json';receipt=root/'receipt.json';source.write_text(json.dumps(snapshot(case())),encoding='utf-8');before=source.read_bytes()
            result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/intent_metric.py'),'compute',str(source)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(0,result.returncode,result.stderr+result.stdout);receipt.write_text(result.stdout,encoding='utf-8')
            checked=subprocess.run([sys.executable,'-B',str(ROOT/'tools/intent_metric.py'),'attest',str(source),'--receipt',str(receipt)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(0,checked.returncode,checked.stderr+checked.stdout);self.assertEqual(before,source.read_bytes())
            source.write_text('{"private":"SYNTHETIC_PRIVATE","private":1}',encoding='utf-8')
            result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/intent_metric.py'),'compute',str(source)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(1,result.returncode);self.assertNotIn('SYNTHETIC_PRIVATE',result.stdout+result.stderr);self.assertNotIn('Traceback',result.stderr)
