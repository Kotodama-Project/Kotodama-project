"""Numeric synthetic regressions; no upstream installation or provider call."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

from tools.validate_cloudflare_quality import (BUDGET_PATH,ROOT,Refused,asset_summary,compare,parse,
                                              read_json,validate_budget,warning_summary)


class CloudflareQualityBudgetTests(unittest.TestCase):
    def setUp(self):
        self.budget=read_json(ROOT/BUDGET_PATH)
        self.lint={'diagnostics':[{'filename':'packages/typed-storage/src/index.ts','code':'eslint(no-shadow)',
                                  'severity':'warning','labels':[{'span':{'offset':20,'length':3}}]}]}
        self.budget['warning_limits']=[{'package':'packages/typed-storage','rule':'eslint(no-shadow)',
                                       'origin':'source','max':1,'owner':'cloudflare_upstream'}]
        self.budget['warning_ids']=warning_summary(self.lint)[2]
        self.assets=[{'name':'assets/main-AbCd1234.js','bytes':100,'gzip_bytes':60,'sha256':'0'*64}]

    def test_committed_budget_retains_the_original_graph_and_every_warning_exception(self):
        actual=read_json(ROOT/BUDGET_PATH)
        limits=validate_budget(actual,now=datetime(2026,10,8,tzinfo=timezone.utc))
        self.assertEqual(sum(limits.values()),64)
        self.assertEqual(len(actual['warning_ids']),64)
        self.assertEqual({key[2] for key in limits},{'source'})
        self.assertEqual(actual['source']['lock_line_endings'],'LF')
        self.assertEqual(actual['source']['dependency_graph'],'original_pinned_no_overlay')

    def test_smaller_synthetic_observation_does_not_claim_a_review_or_provider_pass(self):
        result=compare(self.budget,self.lint,self.assets)
        self.assertEqual(result['status'],'WITHIN_NUMERICAL_LIMITS')
        self.assertFalse(result['review_identity_verified'])
        self.assertFalse(result['provider_verified'])

    def test_warning_growth_and_new_warning_with_same_count_are_refused(self):
        for mode,reason in [('growth','WARNING_GROWTH'),('replacement','UNREVIEWED_WARNING')]:
            with self.subTest(mode=mode):
                lint=copy.deepcopy(self.lint)
                replacement=copy.deepcopy(lint['diagnostics'][0]);replacement['labels'][0]['span']['offset']=90
                if mode=='growth':lint['diagnostics'].append(replacement)
                else:lint['diagnostics']=[replacement]
                with self.assertRaisesRegex(Refused,reason):compare(self.budget,lint,self.assets)

    def test_generated_vendor_or_another_package_cannot_use_a_source_warning_waiver(self):
        for path in ('packages/typed-storage/src/generated/x.ts','packages/typed-storage/vendor/x.ts','packages/new-owner/src/x.ts'):
            with self.subTest(path=path):
                lint=copy.deepcopy(self.lint);lint['diagnostics'][0]['filename']=path
                with self.assertRaisesRegex(Refused,'WARNING_GROWTH'):compare(self.budget,lint,self.assets)

    def test_lint_errors_are_not_offset_by_fewer_warnings(self):
        self.lint['diagnostics'][0]['severity']='error'
        with self.assertRaisesRegex(Refused,'LINT_ERRORS'):compare(self.budget,self.lint,self.assets)

    def test_chunk_exception_is_bounded_by_bytes_gzip_size_name_and_count(self):
        limit=self.budget['frontend_limits']['large_js']['index']
        original={'name':'assets/index-AbCd1234.js','bytes':limit['bytes'],'gzip_bytes':limit['gzip_bytes'],'sha256':'0'*64}
        for mode in ('bytes','gzip_bytes','name','count'):
            with self.subTest(mode=mode):
                assets=[dict(original)]
                if mode in ('bytes','gzip_bytes'):assets[0][mode]+=1
                if mode=='name':assets[0]['name']='assets/unreviewed-AbCd1234.js'
                if mode=='count':assets.append({**original,'name':'assets/index-XyZa1234.js'})
                with self.assertRaises(Refused):compare(self.budget,self.lint,assets)

    def test_many_small_chunks_cannot_hide_total_or_count_growth(self):
        assets=[{**self.assets[0],'name':f'assets/part{i}-AbCd1234.js'} for i in range(27)]
        with self.assertRaisesRegex(Refused,'ASSET_TOTAL_GROWTH'):compare(self.budget,self.lint,assets)

    def test_a_budget_update_can_only_reduce_previously_existing_ceilings(self):
        synthetic_previous=copy.deepcopy(self.budget)
        synthetic_previous['warning_limits'][0]['max']=2
        synthetic_previous['warning_ids'].append('f'*64)
        validate_budget(self.budget,previous=synthetic_previous)
        previous=read_json(ROOT/BUDGET_PATH)
        for mode in ('warning','total','exception','identity'):
            with self.subTest(mode=mode):
                current=copy.deepcopy(previous)
                if mode=='warning':
                    # Keep global 64 and IDs consistent, but move a waiver to a
                    # previously absent package: per-owner growth still fails.
                    current['warning_limits'][0]['package']='packages/new-owner'
                elif mode=='total':current['frontend_limits']['js_bytes']+=1
                elif mode=='exception':current['frontend_limits']['large_js']['index']['bytes']+=1
                else:current['warning_ids'][0]='f'*64
                with self.assertRaises(Refused):validate_budget(current,previous=previous)

    def test_expired_exception_wrong_graph_or_claimed_acceptance_is_refused(self):
        for mode in ('expiry','graph','authority','boolean'):
            with self.subTest(mode=mode):
                value=copy.deepcopy(self.budget)
                if mode=='expiry':value['valid_until']=value['observed_at']
                if mode=='graph':value['source']['dependency_graph']='security_overlay'
                if mode=='authority':value['measurement']['provider_verified']=True
                if mode=='boolean':value['frontend_limits']['js_bytes']=True
                with self.assertRaises(Refused):validate_budget(value)

    def test_assets_are_measured_from_bytes_without_executing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir();file=root/'assets/main-AbCd1234.js'
            file.write_bytes(b'throw new Error("synthetic fixture must not execute");')
            before=file.read_bytes();rows=asset_summary(root)
            self.assertEqual(file.read_bytes(),before)
            self.assertEqual(rows[0]['bytes'],len(before));self.assertGreater(rows[0]['gzip_bytes'],0)

    def test_duplicate_nonfinite_and_private_lint_paths_are_refused(self):
        for data in (b'{"a":1,"a":2}',b'{"a":NaN}'):
            with self.assertRaises(Refused):parse(data)
        for path in ('/private/source.ts','C:/private/source.ts','packages/../private/source.ts'):
            self.lint['diagnostics'][0]['filename']=path
            with self.assertRaises(Refused):warning_summary(self.lint)


if __name__=='__main__':unittest.main()
