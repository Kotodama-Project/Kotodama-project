"""Measure the actual Node diagnostic query with SQLite's VM progress counter.

Node exposes no VM counter. Capture the real Store DDL and diagnostic query,
then replay their synthetic rows in Python SQLite; this is not live evidence.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = r"""
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {Store} from './runtime/discord-template/src/store.mjs';
import {collectVoiceDiagnostics} from './runtime/discord-template/src/voice-diagnostics.mjs';
const root=mkdtempSync(path.join(tmpdir(),'kotodama-diagnostic-vm-'));
let store;
try{
  store=new Store(root);
  const table=store.db.prepare("SELECT sql FROM sqlite_schema WHERE type='table' AND name='events'").get().sql;
  const index=store.db.prepare("SELECT sql FROM sqlite_schema WHERE type='index' AND name='events_diagnostic_window'").get()?.sql;
  store.close();store=null;
  const prepare=DatabaseSync.prototype.prepare;let query,parameters;
  DatabaseSync.prototype.prepare=function(sql){
    const statement=prepare.call(this,sql);
    if(/FROM events WHERE at >= \? AND at < \?/.test(sql)){
      query=sql;const iterate=statement.iterate;
      statement.iterate=function(...args){parameters=args;return iterate.apply(this,args);};
    }
    return statement;
  };
  try{collectVoiceDiagnostics({database:path.join(root,'kotodama.sqlite'),since:'2026-01-01T00:00:00.000Z',until:'2026-01-01T00:30:00.000Z',revision:'a'.repeat(40)});}
  finally{DatabaseSync.prototype.prepare=prepare;}
  console.log(JSON.stringify({table,index,query,parameters}));
}finally{store?.close();rmSync(root,{recursive:true,force:true});}
"""


class VoiceDiagnosticIndexWorkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if node is None:
            raise AssertionError("Diagnostic work test requires Node with node:sqlite")
        result = subprocess.run([node, "--input-type=module", "-e", CAPTURE],
                                cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", timeout=30, check=False)
        if result.returncode:
            raise AssertionError(result.stderr[-3000:])
        cls.actual = json.loads(result.stdout)
        if not all(cls.actual.get(key) for key in ("table", "index", "query", "parameters")):
            raise AssertionError("Real Store index or diagnostic query was not observed")

    def measure(self, history, *, indexed=True):
        actual = self.actual
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute(actual["table"])
            if indexed:
                db.execute(actual["index"])
            types = actual["parameters"][2:-1]
            insert = "INSERT INTO events(type,at,body) VALUES(?,?,?)"
            db.executemany(insert, ((types[i % len(types)], "2025-12-31T23:59:59.999Z", "{}")
                                    for i in range(history)))
            # Also retain nonmatching types *inside* the selected time window.
            db.executemany(insert, (("source.created", actual["parameters"][0], "{}")
                                    for _ in range(history)))
            db.executemany(insert, ((kind, actual["parameters"][0], "{}")
                                    for _ in range(3) for kind in reversed(types)))
            steps = [0]
            db.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
            try:
                rows = db.execute(actual["query"], actual["parameters"]).fetchall()
            finally:
                db.set_progress_handler(None, 0)
            return rows, steps[0]

    def test_actual_multi_type_window_work_does_not_grow_with_retained_history(self):
        expected, baseline = self.measure(0)
        self.assertEqual(len(expected), 21)
        for history in (1000, 10000):
            with self.subTest(retained_history=history):
                rows, steps = self.measure(history)
                self.assertEqual(rows, expected)
                self.assertLessEqual(steps, baseline * 2 + 500,
                                     "Diagnostic VM work must follow the matching window, not retained history")

    def test_removing_index_exposes_a_real_history_scan_regression(self):
        expected, indexed = self.measure(10000)
        unindexed_rows, unindexed = self.measure(10000, indexed=False)
        self.assertEqual(unindexed_rows, expected)
        self.assertGreater(unindexed, indexed * 10,
                           "The fixture must detect a full scan even when returned rows are unchanged")


if __name__ == "__main__":
    unittest.main()
