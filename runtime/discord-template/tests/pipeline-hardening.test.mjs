import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {setImmediate as tick} from 'node:timers/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {check} from '../src/common.mjs';

const actor='100000000000000002';
const source=(extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',
  sourceId:'message',actorId:actor,revision:1,readers:[actor],text:'合成の会話入力',final:true,...extra});
const config=(admission={})=>({analyzer:{admission},discord:{operators:[actor]},worker:{actions:['research']}});
const answer=()=>({summary:'合成の解析結果',intents:[],replyRequested:false,reply:'',voiceAction:'none'});
const latch=()=>{let release;const promise=new Promise(resolve=>release=resolve);return {promise,release};};
async function fixture(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-pipeline-'));let store=new Store(root);
  t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});return {root,get store(){return store;},reopen(){store.close();store=new Store(root);return store;}};}
function queued(store,name){const receipt=store.ingest(source({sourceId:name}));return store.createTask(store.source(receipt.key,actor),{title:name,request:'合成の調査',action:'research',key:name});}
function pipeline(t,store,options={}){const p=new Pipeline({store,config:config(),analyzer:{analyze:async()=>answer()},worker:{run:async()=>({state:'needs_review',summary:'合成の成果',artifacts:[]})},...options});t.after(()=>p.close());return p;}

test('400 background messages stay recorded with bounded analysis and no tasks',async t=>{
  const f=await fixture(t),barrier=latch();let active=0,peak=0,calls=0;
  const p=pipeline(t,f.store,{config:config({concurrency:2,perRoom:1,perActor:1,maxPending:10,maxPendingPerRoom:10,maxPendingPerActor:10}),
    analyzer:{analyze:async()=>{calls++;active++;peak=Math.max(peak,active);await barrier.promise;active--;return answer();}}});
  const jobs=Array.from({length:400},(_,n)=>p.ingest(source({sourceId:'message-'+n}),{execute:false,reply:false}));
  await tick();assert.equal(p.admission.snapshot().active,1);assert.equal(p.admission.snapshot().pending,10);
  assert.equal(f.store.sources(actor).length,400);barrier.release();const results=await Promise.all(jobs);await tick();
  assert.equal(calls,11);assert.equal(peak,1);assert.equal(results.filter(r=>r.reason==='ANALYSIS_QUEUE_FULL').length,389);
  assert.equal(f.store.tasks(actor).length,0);assert.equal(p.analysisControllers.size,0);assert.equal(p.analysisBindings.size,0);
});

test('source is preserved when analysis budget is zero',async t=>{
  const f=await fixture(t);let calls=0;const p=pipeline(t,f.store,{config:config({maxDailyCalls:0}),analyzer:{analyze:async()=>{calls++;return answer();}}});
  const result=await p.ingest(source());assert.equal(result.analysis,'recorded_only');assert.equal(result.reason,'ANALYSIS_DAILY_LIMIT');
  assert.equal(calls,0);assert.equal(f.store.sources(actor).length,1);
});

test('failed provider calls still consume the persistent reservation',async t=>{
  const f=await fixture(t),p=pipeline(t,f.store,{config:config({maxDailyCalls:1}),analyzer:{analyze:async()=>{throw Error('fixture provider failure');}}});
  await assert.rejects(p.ingest(source()),/fixture provider failure/);
  const second=await p.ingest(source({sourceId:'next'}));assert.equal(second.reason,'ANALYSIS_DAILY_LIMIT');
  assert.equal(f.store.db.prepare('SELECT reserved_calls FROM analysis_usage').get().reserved_calls,1);
});

test('a pending corrected source is not sent to the analyzer at its old revision',async t=>{
  const f=await fixture(t),barrier=latch(),seen=[];const p=pipeline(t,f.store,{config:config({concurrency:1}),analyzer:{analyze:async s=>{seen.push([s.sourceId,s.revision]);if(s.sourceId==='busy')await barrier.promise;return answer();}}});
  const busy=p.ingest(source({sourceId:'busy',channelId:'other-room'}));await tick();
  const oldRejected=assert.rejects(p.ingest(source()),/CANCELLED/);
  const corrected=p.ingest(source({revision:2,text:'訂正後の合成入力'}));await oldRejected;
  barrier.release();await Promise.all([busy,corrected]);assert.deepEqual(seen,[['busy',1],['message',2]]);
  assert.equal(f.store.db.prepare('SELECT reserved_calls FROM analysis_usage').get().reserved_calls,2);
});

test('access is rechecked before an already queued input reaches the provider',async t=>{
  const f=await fixture(t),barrier=latch(),seen=[];const p=pipeline(t,f.store,{config:config({concurrency:1}),analyzer:{analyze:async s=>{seen.push(s.sourceId);if(s.sourceId==='busy')await barrier.promise;return answer();}}});
  const busy=p.ingest(source({sourceId:'busy',channelId:'other-room'}));await tick();
  const denied=assert.rejects(p.ingest(source()),/SOURCE_ACCESS_DENIED/);
  f.store.ingest(source({revision:2,readers:[],text:'処理対象外'}));barrier.release();await Promise.all([busy,denied]);assert.deepEqual(seen,['busy']);
});

test('closing the pipeline cancels queued analyses without invoking them',async t=>{
  const f=await fixture(t);let calls=0;const p=pipeline(t,f.store,{config:config({concurrency:1}),analyzer:{analyze:async(s,c,{signal})=>{calls++;await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));return answer();}}});
  const running=assert.rejects(p.ingest(source({sourceId:'running'})),/CANCELLED/);await tick();
  const pending=assert.rejects(p.ingest(source({sourceId:'pending'})),/CANCELLED/);
  await p.close();await Promise.all([running,pending]);assert.equal(calls,1);assert.equal(p.analysis.size,0);
});

test('restart recovers queued work once and never replays uncertain work',async t=>{
  const f=await fixture(t),a=queued(f.store,'a'),b=queued(f.store,'b');f.store.claim(a.id,a.revision);
  const store=f.reopen();store.reconcileInterrupted();const runs=[];const p=pipeline(t,store,{worker:{run:async task=>{runs.push(task.id);return {state:'needs_review',summary:'合成の成果',artifacts:[]};}}});
  const result=await p.recoverQueued();await p.tail;assert.equal(result.enqueued,1);assert.equal(result.blocked,0);assert.deepEqual(runs,[b.id]);
  assert.equal(store.task(a.id,actor).state,'uncertain');assert.equal(store.task(b.id,actor).state,'needs_review');
  await p.recoverQueued();await p.tail;assert.deepEqual(runs,[b.id]);await assert.rejects(p.resume(a.id,actor),/TASK_RECONCILIATION_REQUIRED/);
});

test('recovery retains revoked work without dispatch and records the blocker',async t=>{
  const f=await fixture(t),a=queued(f.store,'a');let ran=0;const p=pipeline(t,f.store,{authorize:async()=>check(false,'GRANT_REVOKED'),worker:{run:async()=>ran++}});
  const result=await p.recoverQueued();await p.tail;assert.equal(result.enqueued,0);assert.equal(result.blocked,1);assert.equal(ran,0);
  assert.equal(f.store.task(a.id,actor).state,'queued');const event=f.store.db.prepare("SELECT body FROM events WHERE type='task.recovery_blocked'").get();assert.equal(JSON.parse(event.body).reason,'GRANT_REVOKED');
});

test('queued resume keeps the Task revision and deduplicates pending dispatch',async t=>{
  const f=await fixture(t),a=queued(f.store,'a'),barrier=latch();let ran=0;const p=pipeline(t,f.store,{worker:{run:async()=>{ran++;return {state:'needs_review',summary:'合成の成果',artifacts:[]};}}});
  p.tail=barrier.promise;const first=await p.resume(a.id,actor),second=await p.resume(a.id,actor);
  assert.equal(first.revision,a.revision);assert.equal(second.revision,a.revision);assert.equal(p.queued.size,1);
  barrier.release();await p.tail;assert.equal(ran,1);
});

test('resume rechecks authority before mutating a cancelled Task',async t=>{
  const f=await fixture(t),a=queued(f.store,'a');f.store.cancel(a.id,actor);const before=f.store.task(a.id,actor);
  const p=pipeline(t,f.store,{authorize:async()=>check(false,'GRANT_REVOKED')});await assert.rejects(p.resume(a.id,actor),/GRANT_REVOKED/);
  assert.deepEqual(f.store.task(a.id,actor),before);
});

test('a remote owner is not replayed by a local recovery scan',async t=>{
  const f=await fixture(t);queued(f.store,'local-stale-queue');let queried=false;
  const p=pipeline(t,f.store,{owner:{kind:'remote',tasks:()=>{queried=true;throw Error('unexpected remote list');}}});
  assert.deepEqual(await p.recoverQueued(),{state:'remote_owner',enqueued:0,blocked:0});assert.equal(queried,false);assert.equal(p.queued.size,0);
});

test('a direct turn at full capacity defers background analysis, not its source',async t=>{
  const f=await fixture(t),barrier=latch(),seen=[];const p=pipeline(t,f.store,{config:config({concurrency:1,maxPending:1,maxPendingPerActor:1}),analyzer:{analyze:async s=>{seen.push(s.sourceId);if(s.sourceId==='busy')await barrier.promise;return answer();}}});
  const busy=p.ingest(source({sourceId:'busy',channelId:'other-room'}));await tick();
  const background=p.ingest(source({sourceId:'background'}));const direct=p.ingest(source({sourceId:'direct'}),{reply:true});
  assert.equal((await background).reason,'ANALYSIS_QUEUE_PREEMPTED');assert.equal(f.store.sources(actor).length,3);
  barrier.release();await Promise.all([busy,direct]);assert.deepEqual(seen,['busy','direct']);
});

test('current provider authorization is checked before reserving model usage',async t=>{
  const f=await fixture(t);let calls=0;const p=pipeline(t,f.store,{authorizeAnalysis:async scope=>{assert.equal(scope.actor,actor);check(false,'GRANT_REVOKED');},analyzer:{analyze:async()=>{calls++;return answer();}}});
  await assert.rejects(p.ingest(source()),/GRANT_REVOKED/);assert.equal(calls,0);
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM analysis_usage').get().n,0);
});

test('revoked provider authority after analysis prevents storing derived intents',async t=>{
  const f=await fixture(t);let checks=0;const p=pipeline(t,f.store,{authorizeAnalysis:async()=>check(++checks===1,'GRANT_REVOKED')});
  await assert.rejects(p.ingest(source()),/GRANT_REVOKED/);assert.equal(checks,2);
  assert.equal(f.store.listIntents(actor).length,0);assert.equal(f.store.tasks(actor).length,0);
});
