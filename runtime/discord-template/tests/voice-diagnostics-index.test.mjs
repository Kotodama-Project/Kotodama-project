import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {collectVoiceDiagnostics} from '../src/voice-diagnostics.mjs';

const since='2026-01-01T00:00:00.000Z',until='2026-01-01T00:30:00.000Z';
const revision='a'.repeat(40),turn={wakeDetected:false,eligible:true,liveActive:true,conversationActive:true};
function fixture(t){
  const root=mkdtempSync(path.join(tmpdir(),'kotodama-diagnostic-index-'));
  t.after(()=>rmSync(root,{recursive:true,force:true}));
  const database=path.join(root,'kotodama.sqlite'),db=new DatabaseSync(database);
  db.exec('CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,type TEXT NOT NULL,at TEXT NOT NULL,body TEXT NOT NULL)');
  return {root,database,db,since,until,revision};
}
function observedQuery(f){
  const prepare=DatabaseSync.prototype.prepare;let query,parameters;
  DatabaseSync.prototype.prepare=function(sql){
    const statement=prepare.call(this,sql);
    if(/FROM events WHERE at >= \? AND at < \?/.test(sql)){
      query=sql;const iterate=statement.iterate;
      statement.iterate=function(...args){parameters=args;return iterate.apply(this,args);};
    }
    return statement;
  };
  try{return {report:collectVoiceDiagnostics(f),get query(){return query;},get parameters(){return parameters;}};}
  finally{DatabaseSync.prototype.prepare=prepare;}
}

test('read-only legacy diagnostic stays unchanged; Store upgrades the index without rewriting events',t=>{
  const f=fixture(t),insert=f.db.prepare('INSERT INTO events(task_id,type,at,body) VALUES(?,?,?,?)');
  insert.run('synthetic-task','voice.local_turn',since,JSON.stringify(turn));
  insert.run(null,'voice.local_asr_timing',since,'{"audioMs":1000,"queueMs":2,"elapsedMs":20}');
  const original=f.db.prepare('SELECT * FROM events ORDER BY seq').all();f.db.close();
  const before=collectVoiceDiagnostics(f),legacy=new DatabaseSync(f.database);
  assert.equal(legacy.prepare("SELECT name FROM sqlite_schema WHERE name='events_diagnostic_window'").get(),undefined);
  legacy.close();
  const store=new Store(f.root);
  try{
    assert.deepEqual(store.db.prepare('SELECT * FROM events ORDER BY seq').all(),original);
    assert.deepEqual(store.db.prepare('PRAGMA index_info(events_diagnostic_window)').all().map(row=>row.name),['type','at']);
  }finally{store.close();}
  assert.deepEqual(collectVoiceDiagnostics(f),before);
  const reopened=new Store(f.root);
  try{assert.deepEqual(reopened.db.prepare('SELECT * FROM events ORDER BY seq').all(),original);}
  finally{reopened.close();}
});

test('actual multi-type diagnostic query uses the time index and preserves half-open scope and insertion order',t=>{
  const f=fixture(t),insert=f.db.prepare('INSERT INTO events(type,at,body) VALUES(?,?,?)');
  f.db.exec('BEGIN');
  for(let i=0;i<10000;i++)insert.run(i%2?'voice.local_turn':'voice.local_asr_timing','2025-12-31T23:59:59.999Z','{}');
  // Insert deliberately out of type/time order. The contract orders by seq.
  insert.run('voice.local_asr_timing','2026-01-01T00:20:00.000Z','{"audioMs":20,"queueMs":2,"elapsedMs":20}');
  insert.run('voice.local_turn',since,JSON.stringify(turn));
  insert.run('task.created','2026-01-01T00:01:00.000Z','{"synthetic":"not returned"}');
  insert.run('voice.local_asr_timing','2026-01-01T00:10:00.000Z','{"audioMs":10,"queueMs":1,"elapsedMs":10}');
  insert.run('voice.reply_skipped',since,'{}');
  insert.run('voice.local_turn',until,JSON.stringify(turn));
  for(let i=0;i<1000;i++)insert.run('source.created',since,'{}');
  f.db.exec('COMMIT');f.db.close();
  const baseline=observedQuery(f),legacy=new DatabaseSync(f.database);
  const expected=legacy.prepare(baseline.query).all(...baseline.parameters);legacy.close();
  assert.deepEqual(expected.map(row=>row.type),['voice.local_asr_timing','voice.local_turn','task.created','voice.local_asr_timing','voice.reply_skipped']);
  const store=new Store(f.root);
  try{
    const indexed=observedQuery(f);
    assert.deepEqual(indexed.report,baseline.report);
    assert.equal(indexed.report.selected_events,5);
    assert.deepEqual(store.db.prepare(indexed.query).all(...indexed.parameters),expected);
    const plan=store.db.prepare('EXPLAIN QUERY PLAN '+indexed.query).all(...indexed.parameters).map(row=>row.detail).join('\n');
    assert.match(plan,/SEARCH events USING INDEX events_diagnostic_window \(type=\? AND at>\? AND at<\?\)/);
    assert(!/SCAN events/.test(plan),plan);
  }finally{store.close();}
});
