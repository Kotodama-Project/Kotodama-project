"""Real small subprocess suites for an opt-in runner, not performance evidence."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'tools/run_repository_tests.py'

TRACE = '''
import json, os, time
from pathlib import Path
def trace(event):
    with Path(os.environ['FIXTURE_TRACE']).open('a') as stream:
        stream.write(json.dumps({'event': event, 'pid': os.getpid(), 'time': time.monotonic()}) + '\\n')
'''


@unittest.skipUnless(sys.platform == 'linux', 'opt-in ownership/RSS runner currently requires Linux /proc')
class RepositoryTestRunnerTests(unittest.TestCase):
    def setUp(self):
        evidence_root = os.environ.get('KOTODAMA_REPOSITORY_RUNNER_TEST_ARTIFACTS')
        if evidence_root:
            Path(evidence_root).mkdir(parents=True, exist_ok=True)
            self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=evidence_root))
        else:
            self.temporary = tempfile.TemporaryDirectory()
            self.addCleanup(self.temporary.cleanup)
            self.root = Path(self.temporary.name)
        self.repo = self.root / 'source'; (self.repo / 'tests').mkdir(parents=True)
        self.trace = self.root / 'trace.jsonl'
        self.cwd = self.root / 'outside'; self.cwd.mkdir()
        self.env = {**os.environ, 'FIXTURE_TRACE': str(self.trace), 'PYTHONDONTWRITEBYTECODE': '1'}
        self.number = 0

    def make_source(self, modules):
        for name, content in modules.items():
            (self.repo / 'tests' / name).write_text(textwrap.dedent(content))
        for args in [('init', '--quiet'), ('config', 'user.email', 'fixture@users.noreply.github.com'),
                     ('config', 'user.name', 'Local fixture'), ('add', '.'), ('commit', '--quiet', '-m', 'fixture')]:
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)
        return subprocess.check_output(['git', '-C', str(self.repo), 'rev-parse', 'HEAD^{tree}']).decode().strip()

    def command(self, workers=1, timeout=15):
        self.number += 1
        out = self.root / ('result-' + str(self.number))
        args = [sys.executable, '-B', str(RUNNER), '--root', str(self.repo), '--output', str(out),
                '--workers', str(workers), '--timeout', str(timeout)]
        return args, out

    def run_suite(self, workers=1, timeout=15, exit_code=0):
        args, out = self.command(workers, timeout)
        result = subprocess.run(args, cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        summary = json.loads((out / 'summary.json').read_text())
        self.assertEqual(summary['exit_code'], exit_code)
        self.assertEqual(summary['qualification'], 'NOT_EVALUATED')
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.repo), 'status', '--porcelain']), b'')
        return summary, out

    def trace_events(self):
        return [json.loads(row) for row in self.trace.read_text().splitlines()]

    def comparable(self, summary):
        return [{k:v for k,v in row.items() if k != 'monotonic'} for row in summary['events']]

    def test_actual_two_workers_overlap_and_keep_private_temp_and_fixtures(self):
        modules = {}
        for name in ['a', 'b']:
            modules['test_' + name + '.py'] = TRACE + f'''
import unittest, tempfile
from pathlib import Path
def setUpModule(): trace('{name}.module.setup')
def tearDownModule(): trace('{name}.module.teardown')
class Work(unittest.TestCase):
    @classmethod
    def setUpClass(cls): trace('{name}.class.setup')
    @classmethod
    def tearDownClass(cls): trace('{name}.class.teardown')
    def test_work(self):
        ready=Path(os.environ['FIXTURE_TRACE']+'.{name}.ready'); ready.write_text('ready')
        other=Path(os.environ['FIXTURE_TRACE']+'.{'b' if name == 'a' else 'a'}.ready')
        until=time.monotonic()+5
        while not other.exists() and time.monotonic()<until: time.sleep(.01)
        self.assertTrue(other.exists())
        trace('{name}.start')
        time.sleep(.15)
        self.assertTrue(Path(tempfile.gettempdir()).name.startswith('tmp-'))
        self.assertNotEqual(Path.cwd(), Path(os.environ['FIXTURE_TRACE']).parent)
        trace('{name}.end')
'''
        self.make_source(modules)
        result, out = self.run_suite(workers=2)
        rows = self.trace_events()
        a = next(x for x in rows if x['event']=='a.start'); b = next(x for x in rows if x['event']=='b.start')
        ae = next(x for x in rows if x['event']=='a.end'); be = next(x for x in rows if x['event']=='b.end')
        self.assertNotEqual(a['pid'], b['pid'])
        self.assertLess(max(a['time'], b['time']), min(ae['time'], be['time']))
        self.assertEqual(len(rows), 12)
        self.assertEqual(result['started_occurrences'], 2)
        self.assertGreater(result['sampled_aggregate_peak_rss_bytes'], 0)
        self.assertEqual(len(list(out.glob('worker-*/raw.log'))), 2)
        self.assertIn('test_work', (out/'worker-0/raw.log').read_text())

    def test_duplicate_ids_and_a_b_a_setup_failure_reentry_match_sequential(self):
        a = TRACE + '''
import unittest
entered=0
def setUpModule():
    global entered
    entered+=1;trace('a.setup.'+str(entered))
    if entered==1: raise RuntimeError('first setup intentionally failed')
def tearDownModule(): trace('a.teardown')
class Again(unittest.TestCase):
    def test_same(self): self.assertEqual(entered,2);trace('a.case')
'''
        self.make_source({'test_a.py':a,'test_b.py':TRACE+'''\nimport unittest
class Between(unittest.TestCase):
    def test_between(self): trace('b.case')
''','test_z.py':'from test_a import Again\n'})
        serial, _ = self.run_suite(exit_code=1)
        parallel, out = self.run_suite(workers=2, exit_code=1)
        # Tracebacks differ only at the runner dispatch frame, while every raw
        # cause, occurrence and fixture outcome remains independently retained.
        projection = lambda s:[{k:v for k,v in row.items() if k not in ('monotonic','traceback')} for row in s['events']]
        self.assertEqual(projection(serial), projection(parallel))
        plan = json.loads((out/'plan.json').read_text())
        ids = [r for r in plan['discovery']['occurrences'] if r['id'].endswith('Again.test_same')]
        self.assertEqual([r['ordinal'] for r in ids], [1,2])
        self.assertEqual(sum(r['kind']=='blocked' for r in parallel['events']),1)
        self.assertEqual(sum(r['kind']=='start' and r['id'].endswith('Again.test_same') for r in parallel['events']),1)
        self.assertEqual(sum('a.setup.2'==r['event'] for r in self.trace_events()),2)
        self.assertTrue(any('first setup intentionally failed' in row.get('traceback','') for row in parallel['events']))

    def test_fail_error_skip_expected_unexpected_and_subtests_all_survive(self):
        self.make_source({'test_outcomes.py':'''\nimport unittest
class Outcomes(unittest.TestCase):
    def test_failure(self): self.fail('genuine assertion')
    def test_error(self): raise LookupError('genuine error')
    @unittest.skip('genuine skip')
    def test_skip(self): pass
    @unittest.expectedFailure
    def test_expected(self): self.fail('expected')
    @unittest.expectedFailure
    def test_unexpected(self): pass
    def test_subtests(self):
        for value in [1,2]:
            with self.subTest(case=value): self.assertEqual(value,1)
''','test_other.py':'import unittest\nclass Other(unittest.TestCase):\n def test_ok(self): pass\n'})
        serial, _ = self.run_suite(exit_code=1)
        parallel, out = self.run_suite(workers=2, exit_code=1)
        projected = lambda s:[{k:v for k,v in row.items() if k not in ('monotonic','traceback')} for row in s['events']]
        self.assertEqual(projected(serial), projected(parallel))
        kinds = [r['kind'] for r in parallel['events']]
        for kind in ['failure','error','skip','expected_failure','unexpected_success']:
            self.assertIn(kind,kinds)
        self.assertEqual(kinds.count('subtest'),2)
        self.assertEqual(parallel['started_occurrences'],7)
        logs=''.join(p.read_text() for p in out.glob('worker-*/raw.log'))
        self.assertIn('genuine assertion',logs);self.assertIn('genuine error',logs)
        self.assertIn('unexpected success',logs.lower())

    def test_real_discovery_import_failure_is_a_retained_error_case(self):
        self.make_source({'test_broken.py':'import does_not_exist_repository_fixture\n','test_ok.py':'import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): pass\n'})
        result,out=self.run_suite(workers=2,exit_code=1)
        self.assertEqual(result['started_occurrences'],2)
        self.assertIn('does_not_exist_repository_fixture',(out/'discovery.log').read_text())
        self.assertTrue(any(r['kind']=='error' and 'FailedTest' in r['id'] for r in result['events']))
        self.assertFalse(result['infrastructure_failures'])

    def test_class_fixture_failure_accounts_for_each_omitted_case(self):
        self.make_source({'test_setup.py':'''\nimport unittest
class Blocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls): raise RuntimeError('class setup failed')
    def test_a(self): self.fail('must never execute')
    def test_b(self): self.fail('must never execute')
class StillRuns(unittest.TestCase):
    def test_c(self): pass
'''})
        result,_=self.run_suite(exit_code=1)
        self.assertEqual(result['started_occurrences'],1)
        self.assertEqual(sum(r['kind']=='blocked' for r in result['events']),2)
        self.assertFalse(result['infrastructure_failures'])

    def test_crash_keeps_partial_raw_prefix_and_never_reports_success(self):
        self.make_source({'test_crash.py':'''\nimport os,unittest
class Crash(unittest.TestCase):
    def test_crash(self): os._exit(77)
'''})
        result,out=self.run_suite(exit_code=2)
        self.assertEqual(result['started_occurrences'],1)
        self.assertEqual(result['stopped_occurrences'],0)
        self.assertEqual(result['worker_returncodes'],[77])
        self.assertTrue((out/'worker-0/events.jsonl').read_bytes())
        self.assertFalse((out/'worker-0/result.json').exists())

    def long_source(self):
        return TRACE+'''
import signal,subprocess,sys,unittest
from pathlib import Path
class Long(unittest.TestCase):
    def test_long(self):
        child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'],start_new_session=True)
        Path(os.environ['FIXTURE_TRACE']+'.child').write_text(str(child.pid))
        trace('ready')
        while True: time.sleep(.02)
'''

    def test_timeout_reaps_detached_real_child_and_preserves_start(self):
        self.make_source({'test_long.py':self.long_source()})
        result,out=self.run_suite(timeout=1.5,exit_code=2)
        self.assertTrue(any(f['code']=='TIMEOUT' for f in result['infrastructure_failures']))
        self.assertEqual(result['started_occurrences'],1)
        pid=int(Path(str(self.trace)+'.child').read_text())
        self.assertFalse(Path('/proc/'+str(pid)).exists())
        self.assertTrue((out/'worker-0/raw.log').exists())

    def test_sigint_stops_all_owned_children_with_partial_evidence(self):
        self.make_source({'test_long.py':self.long_source()})
        args,out=self.command(timeout=15)
        proc=subprocess.Popen(args,cwd=self.cwd,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
        deadline=time.monotonic()+8
        while not Path(str(self.trace)+'.child').exists() and time.monotonic()<deadline:
            time.sleep(.02)
        self.assertTrue(Path(str(self.trace)+'.child').exists())
        proc.send_signal(signal.SIGINT)
        stdout,stderr=proc.communicate(timeout=8)
        self.assertEqual(proc.returncode,2,stdout+stderr)
        result=json.loads((out/'summary.json').read_text())
        self.assertTrue(any(f['code']=='CANCELLED' for f in result['infrastructure_failures']))
        self.assertEqual(result['started_occurrences'],1)
        pid=int(Path(str(self.trace)+'.child').read_text())
        self.assertFalse(Path('/proc/'+str(pid)).exists())

    def test_custom_load_tests_runs_sequential_but_parallel_is_explicitly_refused(self):
        self.make_source({'test_custom.py':'''\nimport unittest
class Custom(unittest.TestCase):
    def test_ok(self): pass
def load_tests(loader,tests,pattern): return tests
'''})
        self.run_suite()
        result,out=self.run_suite(workers=2,exit_code=2)
        self.assertTrue(any(f['code']=='PARALLEL_UNSUPPORTED' for f in result['infrastructure_failures']))
        self.assertEqual(result['started_occurrences'],0)
        self.assertFalse(list(out.glob('worker-*')))

    def test_custom_reordered_run_matches_actual_vanilla_with_duplicates_and_fixture_failure(self):
        for setup_fails in [False, True]:
            with self.subTest(case='setup_failed' if setup_fails else 'all_execute'):
                if self.repo.exists():
                    import shutil
                    shutil.rmtree(self.repo)
                    (self.repo/'tests').mkdir(parents=True)
                self.make_source({
                    'alpha.py':TRACE+"""
import unittest
def setUpModule(): trace('alpha.setup')
def tearDownModule(): trace('alpha.teardown')
class A(unittest.TestCase):
    @classmethod
    def setUpClass(cls): trace('A.setup')
    @classmethod
    def tearDownClass(cls): trace('A.teardown')
    def test_a(self): trace('A.test')
""",
                    'beta.py':TRACE+"""
import unittest
def setUpModule(): trace('beta.setup')
def tearDownModule(): trace('beta.teardown')
class B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        trace('B.setup')
        if SETUP_FAILS: raise LookupError('actual reordered class refusal')
    @classmethod
    def tearDownClass(cls): trace('B.teardown')
    def test_b(self): trace('B.test')
""".replace('SETUP_FAILS',repr(setup_fails)),
                    'test_reverse.py':"""
import unittest,alpha,beta
class Reversed(unittest.TestSuite):
    def run(self,result,debug=False):
        return unittest.TestSuite(list(self)[::-1]).run(result,debug)
def load_tests(loader,tests,pattern):
    return Reversed([alpha.A('test_a'),alpha.A('test_a'),beta.B('test_b')])
"""})
                if self.trace.exists():
                    (self.root/('prior-trace-'+str(setup_fails)+'.jsonl')).write_bytes(self.trace.read_bytes())
                    self.trace.unlink()
                vanilla=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],
                                       cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=15)
                self.assertEqual(vanilla.returncode,1 if setup_fails else 0,vanilla.stdout+vanilla.stderr)
                (self.root/('vanilla-'+str(setup_fails)+'.log')).write_text(vanilla.stdout+vanilla.stderr)
                actual_vanilla=[e['event'] for e in self.trace_events()]
                (self.root/('vanilla-'+str(setup_fails)+'.json')).write_text(json.dumps(actual_vanilla))
                self.trace.unlink()
                result,out=self.run_suite(exit_code=1 if setup_fails else 0)
                self.assertFalse(result['infrastructure_failures'])
                self.assertEqual([e['event'] for e in self.trace_events()],actual_vanilla)
                starts=[e for e in result['events'] if e['kind']=='start']
                self.assertEqual([e['id'] for e in starts],(['beta.B.test_b'] if not setup_fails else [])+['alpha.A.test_a']*2)
                self.assertEqual([e['ordinal'] for e in starts if e['id']=='alpha.A.test_a'],[1,2])
                self.assertEqual(sum(e['kind']=='blocked' for e in result['events']),1 if setup_fails else 0)
                parallel,_=self.run_suite(workers=2,exit_code=2)
                self.assertEqual(parallel['started_occurrences'],0)
                self.assertTrue(any(f['code']=='PARALLEL_UNSUPPORTED' for f in parallel['infrastructure_failures']))

    def test_custom_run_omission_without_setup_refusal_is_not_completion(self):
        self.make_source({'test_omit.py':"""
import unittest
class Real(unittest.TestCase):
    def test_a(self): pass
    def test_b(self): pass
class Missing(unittest.TestSuite):
    def run(self,result,debug=False):
        return unittest.TestSuite(list(self)[1:]).run(result,debug)
def load_tests(loader,tests,pattern): return Missing([Real('test_a'),Real('test_b')])
"""})
        result,_=self.run_suite(exit_code=2)
        self.assertEqual(result['started_occurrences'],1)
        self.assertTrue(any(f['code']=='WORKER_INCOMPLETE' for f in result['infrastructure_failures']))

    def test_custom_stale_or_ambiguous_setup_skip_cannot_cover_unstarted_case(self):
        for fault in ['healthy_reentry', 'ambiguous_single_entry']:
            with self.subTest(case=fault):
                if self.repo.exists():
                    import shutil
                    shutil.rmtree(self.repo)
                    (self.repo/'tests').mkdir(parents=True)
                if self.trace.exists():
                    (self.root/('prior-trace-'+fault+'.jsonl')).write_bytes(self.trace.read_bytes())
                    self.trace.unlink()
                self.make_source({
                    'alpha.py':TRACE+"""
import unittest
entries=0
def setUpModule():
    global entries
    entries+=1;trace('alpha.enter.'+str(entries))
    if entries==1: raise unittest.SkipTest('first entry is skipped')
class A(unittest.TestCase):
    def test_a(self): trace('alpha.a')
    def test_c(self): trace('alpha.c')
    def test_d(self): trace('alpha.d')
""",
                    'beta.py':TRACE+"""
import unittest
class B(unittest.TestCase):
    def test_b(self): trace('beta.b')
""",
                    'test_custom.py':"""
import unittest,alpha,beta
class Omitted(unittest.TestSuite):
    def run(self,result,debug=False):
        return unittest.TestSuite(list(self)[:LIMIT]).run(result,debug)
def load_tests(loader,tests,pattern):
    return Omitted(CASES)
""".replace('LIMIT','3' if fault=='healthy_reentry' else '1').replace('CASES',
                    "[alpha.A('test_a'),beta.B('test_b'),alpha.A('test_c'),alpha.A('test_d')]" if fault=='healthy_reentry' else "[alpha.A('test_a'),alpha.A('test_d')]"),
                })
                result,out=self.run_suite(exit_code=2)
                self.assertEqual(result['status'],'INCOMPLETE')
                self.assertTrue(any(f['code']=='WORKER_INCOMPLETE' for f in result['infrastructure_failures']))
                events=result['events']
                self.assertTrue(any(e['kind']=='skip' and e['id']=='setUpModule (alpha)' for e in events))
                self.assertFalse(any(e['kind']=='blocked' and e['planned_id']=='alpha.A.test_d' for e in events))
                self.assertFalse(any(e['kind']=='start' and e['id']=='alpha.A.test_d' for e in events))
                self.assertTrue((out/'worker-0/raw.log').exists())
                if fault=='healthy_reentry':
                    self.assertEqual(result['started_occurrences'],2)
                    self.assertEqual([e['event'] for e in self.trace_events()],['alpha.enter.1','beta.b','alpha.enter.2','alpha.c'])
                else:
                    self.assertEqual(result['started_occurrences'],0)
                    self.assertEqual([e['event'] for e in self.trace_events()],['alpha.enter.1'])

    def test_unknown_and_duplicate_raw_occurrences_refuse_after_real_case(self):
        for fault in ['unknown', 'duplicate']:
            with self.subTest(case=fault):
                # Each fresh Git repository contains a real completed case;
                # its teardown mutates only the child event proof boundary.
                if self.repo.exists():
                    import shutil
                    shutil.rmtree(self.repo)
                    (self.repo/'tests').mkdir(parents=True)
                code = r"""
import json,os,unittest
from pathlib import Path
class Real(unittest.TestCase):
    def test_real(self): self.assertEqual(2+2,4)
def tearDownModule():
    path=next(Path(os.environ['TMPDIR']).parent.glob('worker-*/events.jsonl'))
    rows=[json.loads(x) for x in path.read_text().splitlines()]
    if FAULT=='duplicate':
        extra=[x for x in rows if x['kind'] in ('start','stop')]
        with path.open('a') as stream:
            for x in extra: stream.write(json.dumps(x)+'\n')
    else:
        next(x for x in rows if x['kind']=='success')['id']='not.discovered.test'
        path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
""".replace('FAULT', repr(fault))
                self.make_source({'test_proof.py':code})
                result,out=self.run_suite(exit_code=2)
                self.assertTrue(any(f['code'] in ('RESULT_INCOMPLETE','RESULT_ID_MISMATCH','RESULT_INVALID') for f in result['infrastructure_failures']))
                self.assertTrue((out/'worker-0/raw.log').exists())

    def test_actual_terminal_outcome_missing_duplicate_conflict_and_order_refuse(self):
        for fault in ['missing', 'duplicate', 'conflict', 'reordered', 'skip_unknown', 'wrong_ordinal', 'invalid_id', 'bool_index', 'huge_monotonic']:
            with self.subTest(case=fault):
                if self.repo.exists():
                    import shutil
                    shutil.rmtree(self.repo)
                    (self.repo/'tests').mkdir(parents=True)
                code = r"""
import json,os,unittest
from pathlib import Path
class Real(unittest.TestCase):
    def test_real(self): self.assertEqual(2+2,4)
def tearDownModule():
    path=next(Path(os.environ['TMPDIR']).parent.glob('worker-*/events.jsonl'))
    rows=[json.loads(x) for x in path.read_text().splitlines()]
    outcome=next(x for x in rows if x['kind']=='success')
    if FAULT=='missing': rows.remove(outcome)
    elif FAULT=='duplicate': rows.insert(2,dict(outcome))
    elif FAULT=='conflict':
        extra=dict(outcome); extra.update(kind='skip',reason='fake'); rows.insert(2,extra)
    elif FAULT=='reordered': rows[1],rows[2]=rows[2],rows[1]
    elif FAULT=='skip_unknown': outcome.update(kind='skip',id='not.planned',reason='fake')
    elif FAULT=='wrong_ordinal': outcome['ordinal']=99
    elif FAULT=='invalid_id': outcome['id']=[]
    elif FAULT=='bool_index': outcome['index']=True
    elif FAULT=='huge_monotonic': rows[0]['monotonic']=10**400
    if FAULT!='reordered':
        for i,row in enumerate(rows,1): row['sequence']=i
    path.write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
""".replace('FAULT', repr(fault))
                self.make_source({'test_terminal.py':code})
                result,out=self.run_suite(exit_code=2)
                self.assertTrue(any(f['code'] in ('RESULT_INCOMPLETE','RESULT_ID_MISMATCH','RESULT_INVALID') for f in result['infrastructure_failures']))
                self.assertTrue((out/'worker-0/raw.log').exists())

    def test_repeated_subtests_skips_and_multiple_cleanup_errors_are_real(self):
        self.make_source({'test_parts.py':r"""
import unittest
class Real(unittest.TestCase):
    def test_repeated(self):
        for value in [1,1]:
            with self.subTest(case=value): self.assertEqual(value,1)
    def test_subskip(self):
        with self.subTest(case=1): self.skipTest('actual subtest skip')
        with self.subTest(case=2): self.assertEqual(2,2)
    def test_multiple_errors(self):
        def error(): raise LookupError('actual cleanup error')
        self.addCleanup(error); self.addCleanup(error)
        self.fail('actual parent failure')
"""})
        result,_=self.run_suite(exit_code=1)
        self.assertFalse(result['infrastructure_failures'])
        self.assertEqual(result['started_occurrences'],3)
        self.assertEqual(result['workers'][0]['errors'],2)
        self.assertEqual(result['workers'][0]['failures'],1)
        self.assertEqual(result['workers'][0]['skips'],1)
        self.assertEqual(sum(e['kind']=='subtest' for e in result['events']),3)

    def test_real_worker_report_schema_and_bounded_reads_refuse(self):
        self.make_source({'test_ok.py':'import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): pass\n'})
        for fault in ['completed_string', 'array', 'duplicate_key', 'oversize']:
            with self.subTest(case=fault):
                args,out=self.command()
                driver=r"""
import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.read_json
fault=sys.argv[2]
def poisoned(path):
    if path.name=='result.json':
        value=json.loads(path.read_text())
        if fault=='completed_string': value['completed']='yes';path.write_text(json.dumps(value))
        elif fault=='array': path.write_text('[]')
        elif fault=='duplicate_key': path.write_text('{"completed":true,"completed":false}')
        elif fault=='oversize': path.write_bytes(b' '*(16*1024*1024+1))
    return original(path)
m.read_json=poisoned
raise SystemExit(m.main(sys.argv[3:]))
"""
                result=subprocess.run([sys.executable,'-B','-c',driver,str(RUNNER),fault,*args[3:]],cwd=self.cwd,
                                      env=self.env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                summary=json.loads((out/'summary.json').read_text())
                self.assertEqual(summary['status'],'INCOMPLETE')
                self.assertTrue(summary['infrastructure_failures'])
                self.assertEqual(summary['started_occurrences'],1)
                self.assertEqual(summary['worker_returncodes'],[0])
                self.assertTrue((out/'worker-0/raw.log').exists())

    def test_oversize_event_line_retains_real_prefix_and_refuses(self):
        self.make_source({'test_big.py':r"""
import os,unittest
from pathlib import Path
class Real(unittest.TestCase):
    def test_real(self): self.assertEqual(2+2,4)
def tearDownModule():
    path=next(Path(os.environ['TMPDIR']).parent.glob('worker-*/events.jsonl'))
    with path.open('ab') as stream: stream.write(b' '*(1024*1024+1)+b'\n')
"""})
        result,out=self.run_suite(exit_code=2)
        self.assertEqual(result['started_occurrences'],1)
        self.assertEqual(result['stopped_occurrences'],1)
        self.assertTrue(any(f['code']=='EVENTS_INVALID' for f in result['infrastructure_failures']))
        self.assertTrue((out/'worker-0/raw.log').exists())

    def test_missing_rss_observation_never_becomes_zero_success(self):
        self.make_source({'test_ok.py':'import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): pass\n'})
        args,out=self.command()
        driver='import importlib.util,sys; s=importlib.util.spec_from_file_location("runner",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.stat=lambda pid:None;raise SystemExit(m.main(sys.argv[2:]))'
        result=subprocess.run([sys.executable,'-B','-c',driver,str(RUNNER),*args[3:]],cwd=self.cwd,env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        summary=json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['status'],'INCOMPLETE')
        self.assertEqual(summary['started_occurrences'],1)
        self.assertTrue(all(row['completed'] and row['successful'] for row in summary['workers']))
        self.assertIsNone(summary['sampled_aggregate_peak_rss_bytes'])
        self.assertTrue(any(f['code']=='RSS_UNAVAILABLE' for f in summary['infrastructure_failures']))

    def test_clone_crossing_deadline_never_launches_a_worker(self):
        self.make_source({'test_ok.py':'import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): pass\n'})
        args,out=self.command(timeout=.6)
        driver=r"""
import importlib.util,sys,time
spec=importlib.util.spec_from_file_location('runner',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.subprocess.run
clones=0
def delayed(args,**kwargs):
    global clones
    if args[:2]==['git','clone']:
        clones+=1
        if clones==2: time.sleep(.8)
    return original(args,**kwargs)
m.subprocess.run=delayed
raise SystemExit(m.main(sys.argv[2:]))
"""
        result=subprocess.run([sys.executable,'-B','-c',driver,str(RUNNER),*args[3:]],cwd=self.cwd,
                              env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        summary=json.loads((out/'summary.json').read_text())
        self.assertTrue(any(f['code']=='TIMEOUT' for f in summary['infrastructure_failures']))
        self.assertEqual(summary['worker_returncodes'],[])
        self.assertFalse(list(out.glob('worker-*')))

    def test_final_launch_preparation_crossing_deadline_never_launches(self):
        self.make_source({'test_ok.py':'import unittest\nclass Ok(unittest.TestCase):\n def test_ok(self): pass\n'})
        for fault in ['collector_log', 'worker_command']:
            with self.subTest(case=fault):
                args,out=self.command(timeout=.6)
                driver=r"""
import importlib.util,os,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
fault=sys.argv[2]
def delay():
    Path(os.environ['FIXTURE_TRACE']+'.delayed').write_text(fault)
    time.sleep(.8)
if fault=='worker_command':
    original=m.save
    def saved(path,value):
        original(path,value)
        if path.name=='command.json': delay()
    m.save=saved
else:
    original=Path.open
    def opened(path,*args,**kwargs):
        value=original(path,*args,**kwargs)
        if path.name=='discovery.log': delay()
        return value
    Path.open=opened
raise SystemExit(m.main(sys.argv[3:]))
"""
                result=subprocess.run([sys.executable,'-B','-c',driver,str(RUNNER),fault,*args[3:]],cwd=self.cwd,
                                      env=self.env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                self.assertEqual(Path(str(self.trace)+'.delayed').read_text(),fault)
                summary=json.loads((out/'summary.json').read_text())
                self.assertTrue(any(f['code']=='TIMEOUT' for f in summary['infrastructure_failures']))
                self.assertEqual(summary['worker_returncodes'],[])
                if fault=='collector_log': self.assertEqual(summary['collector_returncodes'],[])
                else: self.assertEqual(summary['collector_returncodes'],[0])

    def test_discovery_import_timeout_is_owned_and_bounded(self):
        self.make_source({'test_import_wait.py':'import time; time.sleep(60)\n'})
        result,out=self.run_suite(timeout=.5,exit_code=2)
        self.assertTrue(any(f['code']=='TIMEOUT' for f in result['infrastructure_failures']))
        self.assertEqual(result['started_occurrences'],0)
        self.assertFalse(list(out.glob('worker-*')))
        self.assertNotEqual(result['collector_returncodes'],[0])
        self.assertTrue((out/'discovery.log').exists())

    def test_truncated_event_keeps_prefix_and_refuses_saved_success(self):
        self.make_source({'test_events.py':'''\nimport unittest,os
from pathlib import Path
def tearDownModule():
        root=Path(os.environ['TMPDIR']).parent
        event=next(root.glob('worker-*/events.jsonl'))
        with event.open('ab') as stream: stream.write(b'{broken')
class Events(unittest.TestCase):
    def test_corrupt(self): pass
'''})
        result,out=self.run_suite(exit_code=2)
        self.assertTrue(any(f['code']=='EVENTS_INVALID' for f in result['infrastructure_failures']))
        self.assertEqual(result['started_occurrences'],1)
        self.assertTrue(b'{broken' in (out/'worker-0/events.jsonl').read_bytes())


if __name__=='__main__':
    unittest.main(verbosity=2)
