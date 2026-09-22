import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {AnalysisAdmission,analysisLimits} from '../src/analysis-admission.mjs';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {exampleConfig} from '../src/config.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const actor='100000000000000002';
const source=(id,extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:id,actorId:actor,revision:1,readers:[actor],text:'synthetic conversation',final:true,...extra});
const empty={summary:'fixture',intents:[],replyRequested:false,reply:''};
async function fixture(t){const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-admission-')),store=new Store(dir);t.after(async()=>{store.close();await rm(dir,{recursive:true,force:true});});return {dir,store};}

test('400 concurrent submissions keep finite active and pending sets',async()=>{
  const gate=new AnalysisAdmission(()=>({maxConcurrent:2,maxQueued:8,maxPerActor:2,maxPerRoom:2}));let active=0,peak=0,release;const blocker=new Promise(r=>release=r);
  const jobs=Array.from({length:400},(_,i)=>gate.submit({room:'r',actor:'a'},async()=>{active++;peak=Math.max(peak,active);await blocker;active--;return i;}).catch(e=>e.code));
  await tick();assert.equal(gate.status().running,2);assert.equal(gate.status().queued,8);release();const values=await Promise.all(jobs);assert.equal(peak,2);assert.equal(values.filter(v=>typeof v==='number').length,10);assert.equal(values.filter(v=>v==='ANALYSIS_QUEUE_FULL').length,390);assert.equal(gate.running,0);
});
test('per-room and per-actor admission are independent of global capacity',async()=>{
  const gate=new AnalysisAdmission(()=>({maxConcurrent:4,maxQueued:8}));let release;const wait=new Promise(r=>release=r),started=[];
  const jobs=[['r1','a1'],['r1','a2'],['r2','a1'],['r3','a3']].map(([room,actor],i)=>gate.submit({room,actor},async()=>{started.push(i);await wait;}));
  await tick();assert.deepEqual(started,[0,3]);release();await Promise.all(jobs);assert.equal(gate.running,0);
});
test('a direct request displaces passive backlog without increasing the queue',async()=>{
  const gate=new AnalysisAdmission(()=>({maxConcurrent:1,maxQueued:1}));let release;const wait=new Promise(r=>release=r);
  const first=gate.submit({room:'r',actor:'a'},()=>wait),passive=gate.submit({room:'r',actor:'a'},()=>assert.fail('superseded job ran')).catch(e=>e.code);
  const direct=gate.submit({room:'r',actor:'a',priority:1},()=> 'direct');assert.equal(gate.queue.length,1);assert.equal(await passive,'ANALYSIS_SUPERSEDED');release();await first;assert.equal(await direct,'direct');
});
test('abort does not release a running slot until the actual operation settles',async()=>{
  const gate=new AnalysisAdmission(()=>({maxConcurrent:1})),controller=new AbortController();let release,started=false;const wait=new Promise(r=>release=r);
  const first=gate.submit({room:'r',actor:'a',signal:controller.signal},()=>wait);await tick();controller.abort();
  const second=gate.submit({room:'r',actor:'a'},()=>{started=true;});await tick();assert.equal(started,false);assert.equal(gate.running,1);release();await Promise.all([first,second]);assert.equal(started,true);
});
test('queued abort and shutdown never start their payloads',async()=>{
  const gate=new AnalysisAdmission(()=>({maxConcurrent:1}));let release;const wait=new Promise(r=>release=r),first=gate.submit({room:'r',actor:'a'},()=>wait);await tick();
  const controller=new AbortController(),queued=gate.submit({room:'r',actor:'a',signal:controller.signal},()=>assert.fail('cancelled job ran')).catch(e=>e.code);controller.abort();assert.equal(await queued,'CANCELLED');
  const last=gate.submit({room:'r',actor:'a'},()=>assert.fail('closed job ran')).catch(e=>e.code);gate.close();assert.equal(await last,'RUNTIME_STOPPING');assert.throws(()=>gate.submit({room:'r',actor:'a'},()=>{}),/RUNTIME_STOPPING/);release();await first;
});
test('daily and total analysis reservations survive new connections and date rollover',async t=>{
  const {dir,store}=await fixture(t),limits=analysisLimits({maxDailyAnalyses:2,maxTotalAnalyses:3});store.reserveAnalysis(limits,'2026-01-01');store.reserveAnalysis(limits,'2026-01-01');assert.throws(()=>store.reserveAnalysis(limits,'2026-01-01'),/ANALYSIS_BUDGET_EXHAUSTED/);
  const reopened=new Store(dir);try{assert.throws(()=>reopened.reserveAnalysis(limits,'2026-01-01'),/ANALYSIS_BUDGET_EXHAUSTED/);reopened.reserveAnalysis(limits,'2026-01-02');assert.throws(()=>reopened.reserveAnalysis(limits,'2026-01-03'),/ANALYSIS_TOTAL_BUDGET_EXHAUSTED/);}finally{reopened.close();}
});
test('zero allowance records the source without starting a model or executing work',async t=>{
  const {dir,store}=await fixture(t),config=exampleConfig({workspace:dir});config.analyzer.limits.maxDailyAnalyses=0;let calls=0;
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>{calls++;return empty;}}});const result=await p.ingest(source('zero'),{execute:true});assert.equal(result.analysis,'deferred');assert.equal(calls,0);assert.equal(store.sources(actor).length,1);assert.equal(store.tasks(actor).length,0);await p.close();
});
test('source recording continues during overload and no passive message becomes work',async t=>{
  const {dir,store}=await fixture(t),config=exampleConfig({workspace:dir});Object.assign(config.analyzer.limits,{maxConcurrent:1,maxQueued:2});let release,calls=0;const wait=new Promise(r=>release=r);
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>{calls++;await wait;return empty;}}});const jobs=Array.from({length:40},(_,i)=>p.ingest(source('overload-'+i)));await tick();assert.equal(store.sources(actor).length,40);assert.equal(p.analysisAdmission.status().queued,2);release();const results=await Promise.all(jobs);assert.equal(calls,3);assert.equal(results.filter(r=>r.analysis==='deferred').length,37);assert.equal(store.tasks(actor).length,0);await p.close();
});
test('permission is rechecked after queueing and before charging or dispatch',async t=>{
  const {dir,store}=await fixture(t),config=exampleConfig({workspace:dir});config.analyzer.limits.maxConcurrent=1;let release,allowed=true,calls=0;const wait=new Promise(r=>release=r);
  const p=new Pipeline({store,config,authorizeAnalysis:async(s)=>{if(s.sourceId==='blocked'&&!allowed)throw Error('revoked');},analyzer:{analyze:async()=>{calls++;await wait;return empty;}}});
  const first=p.ingest(source('first'));await tick();const queued=p.ingest(source('blocked')).catch(e=>e.message);allowed=false;release();await first;assert.equal(await queued,'revoked');assert.equal(calls,1);assert.equal(store.db.prepare('SELECT SUM(reserved) n FROM analysis_usage').get().n,1);await p.close();
});
test('a cancelled pending revision cannot consume a new model call',async t=>{
  const {dir,store}=await fixture(t),config=exampleConfig({workspace:dir});config.analyzer.limits.maxConcurrent=1;let release;const wait=new Promise(r=>release=r),seen=[];
  const p=new Pipeline({store,config,analyzer:{analyze:async(s)=>{seen.push([s.sourceId,s.revision]);await wait;return empty;}}});
  const first=p.ingest(source('first',{channelId:'100000000000000004'}));await tick();const pending=p.ingest(source('edit')).catch(e=>e.code);const revised=p.ingest(source('edit',{revision:2,text:'corrected'}));release();await first;assert.equal(await pending,'CANCELLED');await revised;assert.deepEqual(seen,[['first',1],['edit',2]]);await p.close();
});
test('failed model work consumes its reserved allowance rather than retrying for free',async t=>{
  const {dir,store}=await fixture(t),config=exampleConfig({workspace:dir});config.analyzer.limits.maxDailyAnalyses=1;let calls=0;const p=new Pipeline({store,config,analyzer:{analyze:async()=>{calls++;throw Error('fixture failure');}}});await assert.rejects(p.ingest(source('failure')),/fixture failure/);const second=await p.ingest(source('retry'));assert.equal(second.analysis,'deferred');assert.equal(calls,1);await p.close();
});
