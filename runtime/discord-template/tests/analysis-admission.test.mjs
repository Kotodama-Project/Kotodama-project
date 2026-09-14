import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {setImmediate as tick} from 'node:timers/promises';
import {Store} from '../src/store.mjs';
import {AnalysisAdmission,AnalysisBudget,admissionLimits} from '../src/analysis-admission.mjs';

const latch=()=>{let release;const promise=new Promise(resolve=>release=resolve);return {promise,release};};
async function database(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-budget-'));const store=new Store(root);t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});return {root,store};}

test('admission validates every bound and refuses undeclared keys',()=>{
  for(const limits of [{concurrency:0},{perActor:-1},{maxPending:-1},{maxDailyCalls:NaN},{unknown:1},{perRoom:1.5}])assert.throws(()=>admissionLimits(limits),/ANALYSIS_LIMIT_INVALID/);
  assert.equal(admissionLimits({maxDailyCalls:0}).maxDailyCalls,0);
});

test('400 calls cannot exceed the active or pending limits',async()=>{
  const gate=new AnalysisAdmission({concurrency:2,maxPending:32});const barrier=latch();let peak=0,active=0;
  const jobs=Array.from({length:400},(_,n)=>gate.run({room:'r'+n,actor:'a'+n},async()=>{active++;peak=Math.max(peak,active);await barrier.promise;active--;return n;}).then(value=>({value}),error=>({code:error.code})));
  await tick();assert.deepEqual(gate.snapshot(),{active:2,pending:32,closed:false});
  barrier.release();const results=await Promise.all(jobs);await tick();
  assert.equal(peak,2);assert.equal(results.filter(r=>r.code==='ANALYSIS_QUEUE_FULL').length,366);
  assert.equal(results.filter(r=>Object.hasOwn(r,'value')).length,34);
  assert.deepEqual(gate.snapshot(),{active:0,pending:0,closed:false});assert.equal(gate.rooms.size,0);assert.equal(gate.actors.size,0);
});

test('room and actor bounds apply across other available slots',async()=>{
  const gate=new AnalysisAdmission({concurrency:4,perRoom:1,perActor:1});const barrier=latch(),started=[];
  const jobs=[['r1','a1'],['r1','a2'],['r2','a1'],['r3','a3']].map(([room,actor])=>gate.run({room,actor},async()=>{started.push(room+actor);await barrier.promise;}));
  await tick();assert.deepEqual(started,['r1a1','r3a3']);assert.equal(gate.snapshot().pending,2);
  barrier.release();await Promise.all(jobs);await tick();assert.equal(started.length,4);
});

test('direct or corrected input takes priority over queued background input',async()=>{
  const gate=new AnalysisAdmission({concurrency:1});const barrier=latch(),order=[];
  const jobs=[gate.run({room:'r',actor:'a'},()=>barrier.promise),gate.run({room:'r',actor:'a'},()=>order.push('background')),
    gate.run({room:'r',actor:'a',priority:2},()=>order.push('correction'))];
  barrier.release();await Promise.all(jobs);assert.deepEqual(order,['correction','background']);
});

test('cancelling a queued analysis releases its pending slot',async()=>{
  const gate=new AnalysisAdmission({concurrency:1,maxPending:1});const barrier=latch(),controller=new AbortController();let ran=false;
  const first=gate.run({room:'r',actor:'a'},()=>barrier.promise);
  const rejected=assert.rejects(gate.run({room:'r',actor:'a',signal:controller.signal},()=>{ran=true;}),/CANCELLED/);
  controller.abort();await rejected;assert.equal(gate.snapshot().pending,0);
  barrier.release();await first;assert.equal(ran,false);
});

test('close rejects queued work and prevents new admission',async()=>{
  const gate=new AnalysisAdmission({concurrency:1});const barrier=latch();
  const first=gate.run({room:'r',actor:'a'},()=>barrier.promise);await tick();
  const rejected=assert.rejects(gate.run({room:'r',actor:'a'},()=>assert.fail('queued work ran')),/CANCELLED/);
  gate.close();await rejected;await assert.rejects(gate.run({room:'other',actor:'other'},()=>{}),/CANCELLED/);
  barrier.release();await first;
});

test('zero pending quota still allows an immediately available slot',async()=>{
  const gate=new AnalysisAdmission({concurrency:1,maxPending:0});const barrier=latch();
  const first=gate.run({room:'r',actor:'a'},()=>barrier.promise);
  await assert.rejects(gate.run({room:'r',actor:'a'},()=>{}),/ANALYSIS_QUEUE_FULL/);barrier.release();await first;
});

test('a failed analysis does not leak an active slot',async()=>{
  const gate=new AnalysisAdmission({concurrency:1});
  await assert.rejects(gate.run({room:'r',actor:'a'},()=>{throw Error('fixture');}),/fixture/);
  assert.equal(await gate.run({room:'r',actor:'a'},()=>42),42);await tick();assert.equal(gate.snapshot().active,0);
});

test('daily reservations persist after reopening the installation database',async t=>{
  const {root,store}=await database(t),clock=()=>new Date('2026-09-14T01:00:00Z'),limits={maxDailyCalls:2,maxTotalCalls:10};
  new AnalysisBudget(store,limits,clock).reserve(2);
  const reopened=new Store(root);try{assert.throws(()=>new AnalysisBudget(reopened,limits,clock).reserve(),/ANALYSIS_DAILY_LIMIT/);}finally{reopened.close();}
  assert.equal(store.db.prepare('SELECT reserved_calls FROM analysis_usage').get().reserved_calls,2);
});

test('total reservations survive a date change and preserve audio accounting',async t=>{
  const {store}=await database(t);store.reserveAudio(1000,2,'2026-09-14');
  new AnalysisBudget(store,{maxDailyCalls:5,maxTotalCalls:2},()=>new Date('2026-09-14')).reserve(2);
  assert.throws(()=>new AnalysisBudget(store,{maxDailyCalls:5,maxTotalCalls:2},()=>new Date('2026-09-15')).reserve(),/ANALYSIS_TOTAL_LIMIT/);
  assert.equal(store.db.prepare('SELECT reserved_ms FROM usage').get().reserved_ms,1000);
});

test('primary and fallback reservations are atomic and fail closed',async t=>{
  const {store}=await database(t),budget=new AnalysisBudget(store,{maxDailyCalls:1});
  assert.throws(()=>budget.reserve(2),/ANALYSIS_DAILY_LIMIT/);assert.equal(store.db.prepare('SELECT COUNT(*) AS n FROM analysis_usage').get().n,0);
  budget.reserve();assert.throws(()=>budget.reserve(),/ANALYSIS_DAILY_LIMIT/);
});

test('zero analysis budget refuses provider admission',async t=>{
  const {store}=await database(t);assert.throws(()=>new AnalysisBudget(store,{maxDailyCalls:0}).reserve(),/ANALYSIS_DAILY_LIMIT/);
  assert.throws(()=>new AnalysisBudget({},{}),/ANALYSIS_BUDGET_STORE_REQUIRED/);
});

test('addressed input can replace lower-priority pending background at capacity',async()=>{
  const gate=new AnalysisAdmission({concurrency:1,maxPending:1,maxPendingPerRoom:1,maxPendingPerActor:1});const barrier=latch();
  const active=gate.run({room:'r',actor:'a'},()=>barrier.promise);await tick();
  const background=assert.rejects(gate.run({room:'r',actor:'a'},()=>assert.fail('preempted work ran')),/ANALYSIS_QUEUE_PREEMPTED/);
  const direct=gate.run({room:'r',actor:'a',priority:1},()=>42);await background;
  barrier.release();await active;assert.equal(await direct,42);
});

test('priority does not evict another actor when its own quota is full',async()=>{
  const gate=new AnalysisAdmission({concurrency:1,maxPending:2,maxPendingPerActor:1});const barrier=latch();
  const active=gate.run({room:'busy',actor:'busy'},()=>barrier.promise);await tick();
  const first=gate.run({room:'r',actor:'a',priority:1},()=>1),other=gate.run({room:'s',actor:'b'},()=>2);
  await assert.rejects(gate.run({room:'r',actor:'a',priority:1},()=>3),/ANALYSIS_QUEUE_FULL/);
  barrier.release();assert.deepEqual(await Promise.all([active,first,other]),[undefined,1,2]);
});
