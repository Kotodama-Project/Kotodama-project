"""Synthetic structural receipt checks; no real deletion or private artifacts."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import validate_retention_deletion_receipt as checker

NOW=datetime(2026,10,7,tzinfo=timezone.utc)


class RetentionDeletionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((ROOT/'examples/retention-deletion/synthetic-receipt.json').read_text(encoding='utf-8'))

    def validate(self): return checker.validate(self.value,as_of=NOW)

    def test_schema_and_reference_vocabulary_match_the_existing_ledger(self):
        schema=json.loads((ROOT/'schemas/retention-deletion-receipt.schema.json').read_text(encoding='utf-8'))
        ledger=json.loads((ROOT/'schemas/session-conversation-event-ledger.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        for name in ('ref','session_ref','public_ref_safety','timestamp','sha256'):
            self.assertEqual(schema['$defs'][name],ledger['$defs'][name])
        reference={**ledger['$defs']['retention']['properties']['deletion_receipt_ref'],'$defs':ledger['$defs']}
        Draft202012Validator(reference).validate(self.value['receipt_ref'])
        expected={'RAW_AUDIO_PCM','RAW_AUDIO_ENCODED','RAW_AUDIO_SEGMENT'}|set(ledger['$defs']['content']['properties']['artifact_stage']['enum'])-{'RAW_AUDIO'}
        self.assertEqual(set(schema['$defs']['artifact_kind']['enum']),expected)

    def test_equal_content_is_valid_for_distinct_manifest_entries_without_deletion_claims(self):
        report=self.validate()
        self.assertEqual(report['status'],'PASS');self.assertEqual(report['artifact_count'],2)
        self.assertEqual(report['scope'],'STRUCTURAL_ONLY');self.assertFalse(any(report['claims'].values()))
        self.assertEqual(len(report['receipt_sha256']),64)
        self.assertEqual(report['as_of'],'2026-10-07T00:00:00Z')

    def test_missing_readback_residue_unknown_fields_and_authority_claims_are_refused(self):
        original=copy.deepcopy(self.value)
        changes=[lambda d:d.pop('readback'),lambda d:d['readback'].update(residual_count=1),
                 lambda d:d['readback'].update(status='PENDING'),lambda d:d.update(body='SYNTHETIC_DO_NOT_REFLECT'),
                 lambda d:d.update(authority_granted=True),lambda d:d.update(gate_closed=True),
                 lambda d:d.update(public_beta_go=True),lambda d:d.update(contains_content=True),
                 lambda d:d.update(receipt_authenticity='VERIFIED'),lambda d:d.update(artifacts=[])]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.value=copy.deepcopy(original);change(self.value);report=self.validate()
                self.assertEqual(report['status'],'REFUSED');self.assertIsNone(report['receipt_ref'])
                self.assertIsNone(report['receipt_sha256']);self.assertFalse(any(report['claims'].values()))
                self.assertNotIn('SYNTHETIC_DO_NOT_REFLECT',json.dumps(report))

    def test_count_mismatch_and_same_target_twice_are_refused(self):
        self.value['artifacts'][0]['count']=1
        self.assertIn('COUNT_DIGEST_MISMATCH',self.validate()['reason_codes'])
        self.value['artifacts'][0]['count']=2
        second=copy.deepcopy(self.value['artifacts'][0]);second['kind']='RAW_AUDIO_ENCODED';self.value['artifacts'].append(second)
        self.assertIn('DUPLICATE_MANIFEST_ENTRY',self.validate()['reason_codes'])

    def test_one_kind_cannot_be_split_or_both_retained_and_deleted(self):
        duplicate=copy.deepcopy(self.value['artifacts'][0]);duplicate['manifest_entry_sha256']=['e'*64,'f'*64]
        self.value['artifacts'].append(duplicate)
        self.assertIn('DUPLICATE_ARTIFACT_KIND',self.validate()['reason_codes'])
        self.value['retained_by_policy'].append('RAW_AUDIO_PCM')
        self.assertIn('RETAINED_AND_DELETED',self.validate()['reason_codes'])

    def test_total_artifact_budget_applies_across_kinds(self):
        self.value['artifacts']=[{'kind':kind,'count':513,'pre_delete_sha256':['b'*64]*513,
            'manifest_entry_sha256':[f'{offset+i:064x}' for i in range(513)]}
            for kind,offset in [('RAW_AUDIO_PCM',0),('RAW_AUDIO_ENCODED',513)]]
        self.assertIn('ARTIFACT_LIMIT',self.validate()['reason_codes'])

    def test_expiry_and_readback_chronology_are_enforced(self):
        original=copy.deepcopy(self.value)
        cases=[('EARLY_EXPIRY_DELETION',lambda d:d.update(deleted_at='2026-08-31T23:59:59Z')),
               ('LATE_DELETION',lambda d:d.update(deleted_at='2026-09-03T00:00:00Z')),
               ('READBACK_BEFORE_DELETION',lambda d:d['readback'].update(checked_at='2026-09-01T00:59:59Z')),
               ('LATE_READBACK',lambda d:d['readback'].update(checked_at='2026-09-03T00:00:00Z')),
               ('DEADLINE_ORDER',lambda d:d['deadline'].update(delete_by='2026-08-31T00:00:00Z')),
               ('FUTURE_RECEIPT',lambda d:d['readback'].update(checked_at='2026-10-08T00:00:00Z'))]
        for code,change in cases:
            with self.subTest(code=code):
                self.value=copy.deepcopy(original);change(self.value);self.assertIn(code,self.validate()['reason_codes'])

    def test_withdrawal_can_precede_the_original_retention_date(self):
        self.value['trigger']='withdrawal';self.value['deadline']['retain_until']='2026-10-01T00:00:00Z'
        self.assertEqual(self.validate()['status'],'PASS')

    def test_private_locators_and_identifiers_do_not_become_opaque_refs(self):
        original=self.value['session_ref']
        for bad in ('ref/session/100000000000000001','ref/session/host.invalid','ref/session/C:/private','ref/session/private user','ref/session/ghp_secret'):
            with self.subTest(ref=bad):
                self.value['session_ref']=bad;self.assertEqual(self.validate()['status'],'REFUSED')
        self.value['session_ref']=original
        self.value['artifacts'][0]['path']='SYNTHETIC_PRIVATE_PATH'
        self.assertNotIn('SYNTHETIC_PRIVATE_PATH',json.dumps(self.validate()))

    def test_invalid_as_of_does_not_silently_fall_back_to_now(self):
        for bad in (False,0,'',datetime(2026,10,7)):
            with self.subTest(as_of=bad):
                self.assertIn('CLOCK_INVALID',checker.validate(self.value,as_of=bad)['reason_codes'])

    def test_schema_cannot_fetch_external_references(self):
        with mock.patch.object(checker,'load_contract',return_value={'$ref':'https://example.invalid/private'}), mock.patch.object(checker,'Draft202012Validator',side_effect=AssertionError('must not follow schema')):
            self.assertEqual(self.validate()['reason_codes'],['SCHEMA_UNAVAILABLE'])

    def test_real_cli_is_read_only_and_rejects_malformed_large_and_deep_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory).resolve()/'receipt.json'
            valid=json.dumps(self.value).encode();file.write_bytes(valid)
            def run(): return subprocess.run([sys.executable,'-B',str(ROOT/'tools/validate_retention_deletion_receipt.py'),str(file),'--as-of','2026-10-07T00:00:00Z'],capture_output=True,timeout=20)
            result=run();self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(file.read_bytes(),valid)
            for payload in (b'{"private":"SYNTHETIC_PRIVATE","private":"duplicate"}',b' '*262145,b'['*1500+b'0'+b']'*1500,b'\xff'):
                with self.subTest(length=len(payload)):
                    file.write_bytes(payload);result=run()
                    self.assertEqual(result.returncode,1,result.stderr)
                    self.assertEqual(json.loads(result.stdout)['status'],'REFUSED')
                    self.assertNotIn(b'SYNTHETIC_PRIVATE',result.stdout+result.stderr)
                    self.assertNotIn(b'Traceback',result.stderr)
                    self.assertEqual(file.read_bytes(),payload)


if __name__=='__main__': unittest.main()
