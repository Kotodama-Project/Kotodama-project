"""Read-only structure and chronology checks; does not perform or attest deletion."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from integration_contract_inputs import load_contract, QuietParser, local_schema_references_only

ROOT=Path(__file__).resolve().parents[1]
MAX_ARTIFACTS=1024
CLAIMS={"deletion_performed":False,"filesystem_readback_verified":False,"receipt_authenticity_verified":False,
        "authority_granted":False,"gate_closed":False,"public_beta_go":False}


def instant(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def report(errors,receipt=None,as_of=None):
    valid=not errors
    return {"status":"PASS" if valid else "REFUSED","scope":"STRUCTURAL_ONLY","reason_codes":sorted(set(errors)),
        "as_of":as_of.astimezone(timezone.utc).isoformat().replace('+00:00','Z') if as_of else None,
        "receipt_ref":receipt["receipt_ref"] if valid else None,
        "receipt_sha256":hashlib.sha256(json.dumps(receipt,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest() if valid else None,
        "artifact_count":sum(item['count'] for item in receipt['artifacts']) if valid else 0,"claims":dict(CLAIMS)}


def validate(receipt,*,as_of=None):
    schema=load_contract(ROOT,'schemas/retention-deletion-receipt.schema.json')
    if not local_schema_references_only(schema):
        return report(['SCHEMA_UNAVAILABLE'])
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return report(['SCHEMA_UNAVAILABLE'])
    if next(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(receipt),None) is not None:
        return report(['SCHEMA_INVALID'])
    errors=[];kinds=[];entries=[];count=0
    for artifact in receipt['artifacts']:
        kinds.append(artifact['kind']);count+=artifact['count'];entries+=artifact['manifest_entry_sha256']
        if artifact['count']!=len(artifact['pre_delete_sha256']) or artifact['count']!=len(artifact['manifest_entry_sha256']):
            errors.append('COUNT_DIGEST_MISMATCH')
    if len(set(kinds))!=len(kinds): errors.append('DUPLICATE_ARTIFACT_KIND')
    if len(set(entries))!=len(entries): errors.append('DUPLICATE_MANIFEST_ENTRY')
    if set(kinds)&set(receipt['retained_by_policy']): errors.append('RETAINED_AND_DELETED')
    if count>MAX_ARTIFACTS: errors.append('ARTIFACT_LIMIT')
    evaluated=None
    try:
        now=datetime.now(timezone.utc) if as_of is None else as_of
        if now.tzinfo is None: raise ValueError('timezone required')
        evaluated=now
        retain=instant(receipt['deadline']['retain_until']);deadline=instant(receipt['deadline']['delete_by'])
        deleted=instant(receipt['deleted_at']);checked=instant(receipt['readback']['checked_at'])
        if receipt['trigger']=='expiry':
            if deadline<retain: errors.append('DEADLINE_ORDER')
            if deleted<retain: errors.append('EARLY_EXPIRY_DELETION')
        if deleted>deadline: errors.append('LATE_DELETION')
        if checked<deleted: errors.append('READBACK_BEFORE_DELETION')
        if checked>deadline: errors.append('LATE_READBACK')
        if deleted>now or checked>now: errors.append('FUTURE_RECEIPT')
    except (ValueError,TypeError,AttributeError):
        errors.append('CLOCK_INVALID')
    return report(errors,receipt,evaluated)


def main():
    parser=QuietParser(description=__doc__)
    parser.add_argument('receipt',type=Path)
    parser.add_argument('--as-of',help='Historical structural evaluation only; not a live readback clock')
    args=parser.parse_args()
    try:
        value=load_contract(args.receipt.parent,args.receipt.name)
        result=validate(value,as_of=instant(args.as_of) if args.as_of is not None else None)
    except (OSError,ValueError,TypeError,RecursionError):
        result=report(['INPUT_REFUSED'])
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
