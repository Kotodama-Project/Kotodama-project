"""Synthetic strategy definitions never adopt Company goals or measurements."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from kotodama_kb.strategy import KINDS, strategy_template, strategy_model, strategy_reference_issues
from kotodama_kb.load import load_bundle
from kotodama_kb.project import _graph
from kotodama_kb.retrieve import select_context
import tempfile
import shutil


def concept(kind,identifier,relationships=(),**refs):
    strategy=strategy_template(kind,identifier)
    strategy['relationships']=[{'type':verb,'target':target} for verb,target in relationships]
    if kind=='Initiative':
        strategy['hypothesis']={'intervention':'Add source-bound context','expected_effect':'Fewer missing mandatory constraints','falsifier':'The frozen suite retains the same missing constraints'}
    return SimpleNamespace(metadata={'type':kind},extension={'strategy':strategy,**refs},
        concept_id='synthetic/'+identifier.lower(),document=SimpleNamespace(relative_path='synthetic/'+identifier.lower()+'.md'),
        resolved_concept_links=tuple('synthetic/'+target.lower() for _,target in relationships))


def fixture():
    result=[concept('Goal','OUT-INTENT',[('measured_by','KGI-INTENT')]),
        concept('Metric','KGI-INTENT',[('computed_by','COMP-INTENT'),('enabled_by','KF-CONTEXT')]),
        concept('Attested Computation','COMP-INTENT'),
        concept('Key Factor','KF-CONTEXT',[('observed_by','KPI-CONTEXT'),('advanced_by','INIT-CONTEXT')]),
        concept('KPI','KPI-CONTEXT',[('computed_by','COMP-CONTEXT')]),
        concept('Attested Computation','COMP-CONTEXT'),
        concept('Initiative','INIT-CONTEXT',[('tested_by','EXP-CONTEXT'),('produces','RESULT-CONTEXT')],goal_refs=['OUT-INTENT'],kgi_refs=['KGI-INTENT'],factor_refs=['KF-CONTEXT']),
        concept('Experiment','EXP-CONTEXT'),concept('Outcome','RESULT-CONTEXT')]
    result[1].extension['strategy']['measurement_role']='product_outcome'
    return result


class KnowledgeStrategyTests(unittest.TestCase):
    def test_public_bundle_resolves_existing_ids_and_projects_typed_goal_kgi_edge(self):
        bundle=load_bundle(ROOT);projection,issues=strategy_model(bundle.concepts)
        self.assertEqual([],issues);self.assertEqual(11,len(projection['definitions']))
        self.assertEqual('project/success-model',projection['definitions']['KGI-INTENT']['concept_id'])
        graph=_graph(bundle)
        self.assertIn({'from':'OUT-INTENT','from_kind':'goal','relation':'measured_by','to':'KGI-INTENT','to_kind':'kgi'},graph['edges'])
        self.assertEqual('project/success-model',next(n['definition_concept'] for n in graph['nodes'] if n['kind']=='kgi' and n['id']=='KGI-INTENT'))

    def test_default_profile_gate_refuses_a_goal_reference_with_no_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            baseline=load_bundle(ROOT)
            for relative,_ in baseline.input_bindings:
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
            self.assertFalse([i for i in load_bundle(root).issues if i.level=='error'])
            p=root/'knowledge/project/goal.md';text=p.read_text(encoding='utf-8');old='goal_refs: [OUT-INTENT, OUT-LOCAL]';self.assertIn(old,text)
            p.write_text(text.replace(old,'goal_refs: [OUT-MISSING]',1),encoding='utf-8')
            bundle=load_bundle(root)
            self.assertIn('STRATEGY_REF_UNRESOLVED',{i.code for i in bundle.issues})

    def test_linked_critical_definition_is_not_displaced_by_optional_context(self):
        from datetime import datetime,timezone
        bundle=load_bundle(ROOT,as_of=datetime(2026,10,4,14,tzinfo=timezone.utc))
        args=dict(goals=['OUT-INTENT'],kgis=[],initiatives=['INIT-KNOWLEDGE-REFRESH'],tags=[])
        critical={'project/goal','project/success-model','project/local-outcome','project/current-state',
                  'governance/authority-boundaries','governance/agent-responsibilities','governance/knowledge-lifecycle'}
        short=select_context(bundle,**args,max_concepts=6)
        self.assertTrue(short.unresolved_ids)
        complete=select_context(bundle,**args,max_concepts=7)
        self.assertEqual((),complete.unresolved_ids)
        self.assertEqual(critical,{c.concept_id for c in complete.selected})

    def test_every_template_is_closed_and_metric_adoption_remains_unknown(self):
        schema=json.loads((ROOT/'schemas/kotodama-okf-concept.schema.json').read_text(encoding='utf-8'))
        validator=Draft202012Validator({'$ref':'#/$defs/strategy','$defs':schema['$defs']})
        for kind in KINDS:
            value=strategy_template(kind,'SYNTHETIC-ID');self.assertEqual([],list(validator.iter_errors(value)))
            self.assertEqual('candidate',value['adoption_status'])
            for bad in ({**value,'runtime_authority':True},{**value,'target':1},{**value,'adoption_status':'adopted'}):
                self.assertTrue(list(validator.iter_errors(bad)))

    def test_typed_model_is_deterministic_and_keeps_portable_concept_links(self):
        items=fixture();a,issues=strategy_model(items);b,other=strategy_model(reversed(items))
        self.assertEqual([],issues);self.assertEqual([],other);self.assertEqual(a,b)
        self.assertEqual('synthetic/kgi-intent',a['definitions']['KGI-INTENT']['concept_id'])
        self.assertEqual('projection_only',a['authority']);self.assertEqual(8,len(a['relationships']))

    def test_task_reference_projection_rejects_missing_or_wrong_goal_metric_factor_initiative(self):
        projection,_=strategy_model(fixture());index=projection['definitions']
        valid={'goal_refs':['OUT-INTENT'],'kgi_refs':['KGI-INTENT'],'factor_refs':['KF-CONTEXT'],'initiative_refs':['INIT-CONTEXT']}
        self.assertEqual([],strategy_reference_issues(valid,index,path='synthetic-task'))
        for key in valid:
            for wrong in ('MISSING-ID','EXP-CONTEXT'):
                self.assertTrue(strategy_reference_issues({**valid,key:[wrong]},index,path='synthetic-task'))
        index['SLO-CONTEXT']={'kind':'metric','concept_id':'synthetic/slo-context','measurement_role':'control_slo'}
        self.assertTrue(strategy_reference_issues({'kgi_refs':['SLO-CONTEXT']},index,path='synthetic-task'))

    def test_unknown_refs_duplicate_definitions_missing_links_and_wrong_edge_types_refuse_projection(self):
        mutations=[lambda x:x[0].extension.update(goal_refs=['MISSING-ID']),lambda x:x.append(copy.deepcopy(x[0])),
            lambda x:setattr(x[0],'resolved_concept_links',()),lambda x:x[0].extension['strategy']['relationships'][0].update(target='KF-CONTEXT'),
            lambda x:x[0].extension['strategy']['relationships'][0].update(target='MISSING-ID')]
        for mutate in mutations:
            items=fixture();mutate(items);projection,issues=strategy_model(items)
            self.assertTrue(issues);self.assertFalse(projection['valid']);self.assertEqual({},projection['definitions']);self.assertEqual([],projection['relationships'])

    def test_circular_dependencies_and_placeholder_initiatives_are_reported(self):
        items=[concept('Decision','DECISION-A',[('revises','DECISION-B')]),concept('Decision','DECISION-B',[('revises','DECISION-A')])]
        self.assertIn('STRATEGY_DEPENDENCY_CYCLE',{i.code for i in strategy_model(items)[1]})
        initiative=concept('Initiative','INIT-CONTEXT');initiative.extension['strategy']['hypothesis']['falsifier']='TODO'
        self.assertIn('STRATEGY_HYPOTHESIS_REQUIRED',{i.code for i in strategy_model([initiative])[1]})

    def test_candidate_metadata_cannot_adopt_window_target_baseline_or_confuse_kpi_and_kgi(self):
        for field in ('baseline','target','deadline','measurement_window','exclusion_policy'):
            items=fixture();items[1].extension['strategy'][field]=42
            self.assertIn('STRATEGY_MEASUREMENT_NOT_ADOPTED',{i.code for i in strategy_model(items)[1]})
        items=fixture();items[4].extension['strategy']['measurement_role']='product_outcome'
        self.assertIn('STRATEGY_MEASUREMENT_ROLE',{i.code for i in strategy_model(items)[1]})

    def test_empty_definitions_do_not_make_unresolved_legacy_references_valid(self):
        old=SimpleNamespace(extension={'goal_refs':['OUT-INTENT']},document=SimpleNamespace(relative_path='legacy.md'))
        self.assertIn('STRATEGY_REF_UNRESOLVED',{i.code for i in strategy_model([old])[1]})
