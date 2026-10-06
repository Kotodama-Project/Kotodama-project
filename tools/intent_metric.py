"""Compute or independently recompute a content-free candidate KGI receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from integration_contract_inputs import load_contract, local_schema_references_only, QuietParser
from kotodama_kb.foundation import KnowledgeBaseError, _require_valid_bundle, _assert_current, _read_bytes
from kotodama_kb.load import load_bundle
from kotodama_kb.strategy import strategy_model, strategy_reference_issues
from intent_outcome_computation import evaluate, digest, MetricRefused

ROOT=Path(__file__).resolve().parents[1]
CONCEPT='computations/intent-outcome'
ARTIFACTS=('tools/intent_outcome_computation.py','tools/intent_metric.py','schemas/intent-outcome-snapshot.schema.json')
PARAMETERS=[{'name':'snapshot','type':'object','required':True}]
RECEIPT_FIELDS=['computation_revision','artifact_sha256','input_snapshot_sha256','parameter_binding_sha256','result','result_sha256']
CLAIMS={'measurement_adopted':False,'source_evidence_authenticated':False,'coverage_authenticated':False,
        'execution_authenticated':False,'authority_granted':False,'current_truth_changed':False,
        'public_beta_go':False,'final_human_go':False}


def prepare(snapshot,*,root=ROOT):
    """Read a current pinned definition; never import code from a supplied root."""
    bundle=load_bundle(root);_require_valid_bundle(bundle)
    concept=bundle.by_id.get(CONCEPT)
    if concept is None:
        raise MetricRefused('METRIC_DEFINITION_MISSING')
    metadata=concept.metadata
    expected={'runtime':'python','parameters':PARAMETERS,'computation':'../../tools/intent_outcome_computation.py',
        'executor':{'resource':'../../tools/intent_metric.py','receipt':RECEIPT_FIELDS},
        'attester':{'resource':'../../tools/intent_metric.py'}}
    if any(digest(metadata.get(key))!=digest(value) for key,value in expected.items()):
        raise MetricRefused('METRIC_DEFINITION_CONTRACT_CHANGED')
    if concept.is_stale or concept.metadata.get('status')=='deprecated' or concept.extension.get('knowledge_state') not in {'candidate','confirmed'}:
        raise MetricRefused('METRIC_DEFINITION_NOT_CURRENT')
    sources={source['resource']:source.get('sha256') for source in metadata['sources']}
    bindings=dict(bundle.input_bindings);artifacts={}
    for relative in ARTIFACTS:
        pinned=sources.get('../../'+relative)
        if not pinned or bindings.get(relative)!=pinned:
            raise MetricRefused('METRIC_ARTIFACT_NOT_PINNED')
        # A test/inspection root may supply evidence; execution always stays in
        # this installed tool. Different code cannot be selected as a parameter.
        if hashlib.sha256(_read_bytes(ROOT/relative)).hexdigest()!=pinned:
            raise MetricRefused('METRIC_INSTALLED_ARTIFACT_MISMATCH')
        artifacts[relative]=pinned
    schema=load_contract(root,ARTIFACTS[2])
    if not local_schema_references_only(schema):
        raise MetricRefused('METRIC_SCHEMA_REFERENCE_REFUSED')
    Draft202012Validator.check_schema(schema)
    if next(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(snapshot),None) is not None:
        raise MetricRefused('METRIC_SNAPSHOT_INVALID')
    strategy,issues=strategy_model(bundle.concepts)
    if issues:
        raise MetricRefused('METRIC_STRATEGY_INVALID')
    for case in snapshot['cases']:
        if strategy_reference_issues({'goal_refs':[case['goal_ref']],'kgi_refs':['KGI-INTENT']},strategy['definitions'],path='metric-case'):
            raise MetricRefused('METRIC_GOAL_REFERENCE_INVALID')
    _assert_current(bundle)
    return bundle,concept.content_sha256,artifacts


def compute(snapshot,*,root=ROOT):
    # Keep one private JSON value for schema checks, arithmetic and receipt
    # digests even if an API caller later changes its mutable input object.
    snapshot=json.loads(json.dumps(snapshot,ensure_ascii=False,allow_nan=False))
    bundle,revision,artifacts=prepare(snapshot,root=root)
    result=evaluate(snapshot)
    _assert_current(bundle)
    # Detect installed artifact changes after validation as well as definition
    # changes. This is artifact consistency, not OS/runtime authentication.
    for relative,expected in artifacts.items():
        if hashlib.sha256(_read_bytes(ROOT/relative)).hexdigest()!=expected:
            raise MetricRefused('METRIC_INSTALLED_ARTIFACT_CHANGED')
    return {'kind':'kotodama.intent-outcome-receipt','schema_revision':'v1',
        'computation_ref':CONCEPT,'computation_revision':revision,'artifact_sha256':artifacts,
        'input_snapshot_sha256':digest(snapshot),'parameter_binding_sha256':digest({'snapshot':snapshot}),
        'result':result,'result_sha256':digest(result),'claims':dict(CLAIMS)}


def attest(snapshot,receipt,*,root=ROOT):
    # Recompute from supplied immutable evidence and the current pinned
    # definition, not from result fields or an LLM's explanation in the receipt.
    expected=compute(snapshot,root=root)
    if digest(receipt)!=digest(expected):
        raise MetricRefused('METRIC_RECEIPT_MISMATCH')
    return {'status':'PASS','scope':'PINNED_ARTIFACT_AND_ARITHMETIC_ONLY',
        'receipt_sha256':digest(expected),'result_sha256':expected['result_sha256'],
        'disposition':expected['result']['disposition'],'claims':dict(CLAIMS)}


def main():
    parser=QuietParser(description=__doc__)
    parser.add_argument('operation',choices=('compute','attest'))
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--receipt',type=Path)
    args=parser.parse_args()
    try:
        if (args.operation=='attest')!=(args.receipt is not None):
            raise MetricRefused('METRIC_RECEIPT_ARGUMENT')
        snapshot=load_contract(args.snapshot.parent,args.snapshot.name)
        result=compute(snapshot) if args.operation=='compute' else attest(snapshot,load_contract(args.receipt.parent,args.receipt.name))
        print(json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError,SchemaError,KnowledgeBaseError):
        print(json.dumps({'status':'REFUSED','scope':'PINNED_ARTIFACT_AND_ARITHMETIC_ONLY','reason_codes':['METRIC_INPUT_OR_BINDING_REFUSED'],'claims':dict(CLAIMS)},sort_keys=True));return 1


if __name__=='__main__':
    raise SystemExit(main())
