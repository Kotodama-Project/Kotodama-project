import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {exampleConfig} from '../src/config.mjs';
const actor='100000000000000002';
async function fixture(t){const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-recovery-'));let store=new Store(dir);t.after(async()=>{store.close();await rm(dir,{recursive:true,force:true});});const source={provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:'task-source',actorId:actor,revision:1,readers:[actor],text:'fixture',final:true};const key=store.ingest(source).key;const task=store.createTask(store.source(key,actor),{title:'fixture',request:'fixture',action:'research'});return {dir,task,get store(){return store;},reopen(){store.close();store=new Store(dir);return store;}};}
test('reopen makes unstarted tasks explicitly resumable, preserving identity',async t=>{
  const f=await fixture(t),store=f.reopen();assert.equal(store.reconcileInterrupted(),1);const paused=store.task(f.task.id,actor);assert.equal(paused.state,'paused');assert.equal(paused.revision,1);assert.equal(store.reconcileInterrupted(),0);const resumed=store.resume(paused.id,actor);assert.equal(resumed.id,paused.id);assert.equal(resumed.state,'queued');assert.equal(resumed.revision,2);assert.throws(()=>store.resume(paused.id,actor),/TASK_CANNOT_RESUME/);
});
test('running tasks are uncertain after restart and cannot be automatically resumed',async t=>{
  const f=await fixture(t);f.store.claim(f.task.id,1);const store=f.reopen();store.reconcileInterrupted();assert.equal(store.task(f.task.id,actor).state,'uncertain');assert.throws(()=>store.resume(f.task.id,actor),/TASK_CANNOT_RESUME/);
});
test('revoked permission leaves a paused task unchanged, then one authorized resume runs once',async t=>{
  const f=await fixture(t);f.store.reconcileInterrupted();let allowed=false,calls=0;const p=new Pipeline({store:f.store,config:exampleConfig({workspace:f.dir}),authorize:async()=>{if(!allowed)throw Error('revoked');},worker:{run:async()=>{calls++;return {state:'needs_review',summary:'fixture',artifacts:[]};}}});await assert.rejects(p.resume(f.task.id,actor),/revoked/);assert.equal(f.store.task(f.task.id,actor).state,'paused');assert.equal(f.store.task(f.task.id,actor).revision,1);allowed=true;await p.resume(f.task.id,actor);await p.tail;assert.equal(calls,1);assert.equal(f.store.task(f.task.id,actor).state,'needs_review');await p.close();
});
test('withdrawn source prevents paused recovery and never resurrects an old task',async t=>{
  const f=await fixture(t);f.store.reconcileInterrupted();const s=f.store.source(f.task.source_key,actor);f.store.ingest({...s,revision:2,text:'',withdrawn:true});assert.throws(()=>f.store.resume(f.task.id,actor),/SOURCE_ACCESS_DENIED/);assert.equal(f.store.taskInternal(f.task.id).state,'stale');
});
