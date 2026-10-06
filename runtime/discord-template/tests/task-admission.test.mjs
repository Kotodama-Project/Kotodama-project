import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {exampleConfig} from '../src/config.mjs';
import {Refused} from '../src/common.mjs';

const actor='100000000000000002';
const source=()=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:'admission-message',actorId:actor,readers:[actor],revision:1,text:'調査と編集をお願いします',final:true});
const intent=action=>({kind:'request',title:action,request:action,action,explicit:true,complete:true,acceptance:['done']});
async function fixture(t,{actions=['research','develop'],current=actions,authorize=async()=>{},ownerFactory}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-admission-'));const store=new Store(root);
  const config=exampleConfig({workspace:root});config.worker.actions=actions;
  const policy=structuredClone(config);policy.worker.actions=current;
  let runs=0,notices=0,reads=0;
  const pipeline=new Pipeline({store,owner:ownerFactory?.(store)??store,config,policy:()=>policy,
    readPolicy:async()=>{reads++;return policy;},authorize,
    analyzer:{analyze:async()=>({summary:'requests',intents:[intent('research'),intent('develop')],replyRequested:false,reply:''})},
    worker:{run:async()=>{runs++;return {state:'needs_review',summary:'candidate',artifacts:[]};}},
    onTaskQueued:async()=>{notices++;}});
  t.after(async()=>{await pipeline.close();store.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-admission-'));await rm(root,{recursive:true,force:true});});
  return {store,pipeline,policy,counts:()=>({runs,notices,reads}),rows:()=>store.statement('SELECT id,state,revision FROM tasks').all()};
}

test('one disallowed action refuses the entire message before creating Tasks',async t=>{
  const f=await fixture(t,{actions:['research']});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/ACTION_NOT_ALLOWED/);
  await f.pipeline.tail;assert.equal(f.rows().length,0);assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);
});
test('a grant removed since startup refuses all Tasks before creation',async t=>{
  const f=await fixture(t,{current:['research']});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/ACTION_NOT_ALLOWED/);
  await f.pipeline.tail;assert.equal(f.rows().length,0);assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);
});
test('direct commands refresh policy and leave no refused queued Task',async t=>{
  const f=await fixture(t,{current:['research']});
  await assert.rejects(f.pipeline.request(source(),intent('develop')),/ACTION_NOT_ALLOWED/);
  await f.pipeline.tail;assert.equal(f.rows().length,0);assert.equal(f.counts().runs,0);assert(f.counts().reads>0);
});
test('second authorization failure cancels staged Tasks without executing or notifying the first',async t=>{
  let seen=0;const f=await fixture(t,{authorize:async()=>{if(++seen===2)throw Error('GRANT_REVOKED');}});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/GRANT_REVOKED/);
  await f.pipeline.tail;assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);
  assert.equal(f.rows().length,2);assert(f.rows().every(r=>r.state==='cancelled'));
});
test('owner creation failure retires the first staged Task',async t=>{
  let count=0;const f=await fixture(t,{ownerFactory:store=>new Proxy(store,{get(target,key){if(key==='createTask')return async(...args)=>{if(++count===2)throw Error('OWNER_RESULT_UNCERTAIN');return target.createTask(...args);};const value=target[key];return typeof value==='function'?value.bind(target):value;}})});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/OWNER_RESULT_UNCERTAIN/);
  await f.pipeline.tail;assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);assert(f.rows().every(r=>r.state==='cancelled'));
});
test('successful admission executes both Tasks only after both authorizations',async t=>{
  let admitted=0;const f=await fixture(t,{authorize:async()=>{admitted++;}});
  const result=await f.pipeline.ingest(source(),{execute:true});assert.equal(result.tasks.length,2);assert(admitted>=2);
  await f.pipeline.tail;assert.equal(f.counts().runs,2);assert.equal(f.counts().notices,2);
});
test('final admission snapshot catches an earlier action revoked during later authorization',async t=>{
  let f,seen=0;f=await fixture(t,{authorize:async()=>{if(++seen===2)f.policy.worker.actions=['develop'];}});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/ACTION_NOT_ALLOWED/);
  await f.pipeline.tail;assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);assert(f.rows().every(r=>r.state==='cancelled'));
});
test('cleanup cannot cancel a newer revision or a running Task',async t=>{
  const f=await fixture(t);const s=f.store.source(f.store.ingest(source()).key,actor);
  const first=f.store.createTask(s,intent('research'));const revised=f.store.reviseTask(first.id,s,intent('research'));
  assert.throws(()=>f.store.cancelQueued(first.id,actor,first.revision),/TASK_CHANGED/);
  f.store.claim(first.id,revised.revision);assert.throws(()=>f.store.cancelQueued(first.id,actor,revised.revision),/TASK_CHANGED/);
  assert.equal(f.store.taskInternal(first.id).state,'running');
});
test('unconfirmed cleanup drains admission instead of claiming cancellation',async t=>{
  let seen=0;const f=await fixture(t,{authorize:async()=>{if(++seen===2)throw Error('GRANT_REVOKED');},
    ownerFactory:store=>new Proxy(store,{get(target,key){if(key==='cancelQueued')return async()=>undefined;const value=target[key];return typeof value==='function'?value.bind(target):value;}})});
  await assert.rejects(f.pipeline.ingest(source(),{execute:true}),/GRANT_REVOKED/);
  assert.equal(f.pipeline.draining,true);assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);
  await assert.rejects(f.pipeline.request({...source(),sourceId:'next'},intent('research')),/RUNTIME_STOPPING/);
});
test('a direct command rejected after creation cancels its queued revision',async t=>{
  const f=await fixture(t,{authorize:async()=>{throw Error('GRANT_REVOKED');}});
  await assert.rejects(f.pipeline.request(source(),intent('research')),/GRANT_REVOKED/);
  assert.equal(f.rows().length,1);assert.equal(f.rows()[0].state,'cancelled');assert.equal(f.counts().runs,0);
});
test('unknown direct owner creation outcome stops new admissions',async t=>{
  const f=await fixture(t,{ownerFactory:store=>new Proxy(store,{get(target,key){if(key==='createTask')return async()=>{throw new Refused('OWNER_RESULT_UNCERTAIN');};const value=target[key];return typeof value==='function'?value.bind(target):value;}})});
  await assert.rejects(f.pipeline.request(source(),intent('research')),/OWNER_RESULT_UNCERTAIN/);
  assert.equal(f.pipeline.draining,true);assert.equal(f.counts().runs,0);assert.equal(f.counts().notices,0);
});
test('source revocation does not prevent cancelling an owned unexecuted revision',async t=>{
  const f=await fixture(t);const original=source();const s=f.store.source(f.store.ingest(original).key,actor);
  const task=f.store.createTask(s,intent('research'));
  f.store.ingest({...original,revision:2,withdrawn:true,text:''});
  // Revocation itself makes the task stale; admission cleanup must not overwrite it.
  assert.throws(()=>f.store.cancelQueued(task.id,actor,task.revision),/TASK_CHANGED/);
  assert.equal(f.store.taskInternal(task.id).state,'stale');
});
