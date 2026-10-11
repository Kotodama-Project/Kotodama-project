import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {TaskAdmission} from '../src/task-admission.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {Store} from '../src/store.mjs';
import {exampleConfig} from '../src/config.mjs';
import {Refused} from '../src/common.mjs';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
async function until(condition){for(let attempt=0;attempt<100;attempt++){if(condition())return;await tick();}assert.fail('condition did not settle');}
const descriptor=(id,actor=id,action='research',room=actor)=>({id,actor,action,room,revision:1});

test('queue bounds pending references and refuses an overflowing batch before starting it',async()=>{
  const gate=new TaskAdmission(()=>({maxConcurrentReadOnly:1,maxQueued:1})),hold=deferred(),started=[];
  const [first]=gate.submitBatch([{task:descriptor('one'),operation:async()=>{started.push('one');await hold.promise;}}]);
  assert.throws(()=>gate.submitBatch(['two','three'].map(id=>({task:descriptor(id),operation:async()=>started.push(id)}))),/TASK_QUEUE_FULL/);
  const [second]=gate.submitBatch([{task:descriptor('two'),operation:async()=>started.push('two')}]);
  const [duplicate]=gate.submitBatch([{task:descriptor('two'),operation:()=>assert.fail('duplicate operation')}]);
  assert.equal(second,duplicate);assert.equal(gate.status().queued,1);assert(gate.status().queuedBytes>0);
  hold.resolve();await Promise.all([first,second]);await gate.idle();assert.deepEqual(started,['one','two']);assert.equal(gate.status().queuedBytes,0);
});

test('queued byte budget is independent of available execution slots',async()=>{
  const gate=new TaskAdmission(()=>({maxConcurrentReadOnly:1,maxQueued:4,maxQueuedBytes:0})),hold=deferred();
  const [first]=gate.submitBatch([{task:descriptor('one'),operation:()=>hold.promise}]);
  assert.throws(()=>gate.submitBatch([{task:descriptor('two'),operation:()=>{}}]),/TASK_QUEUE_BYTES_EXCEEDED/);
  hold.resolve();await first;await gate.idle();
});

test('dynamic lower limits retain active operations and stop new admission until capacity returns',async()=>{
  const limits={maxConcurrentReadOnly:2},gate=new TaskAdmission(()=>limits),holds=[deferred(),deferred()],started=[];
  const jobs=gate.submitBatch(['a','b','c'].map((id,index)=>({task:descriptor(id),operation:async()=>{started.push(id);if(index<2)await holds[index].promise;}})));
  await until(()=>started.length===2);limits.maxConcurrentReadOnly=1;holds[0].resolve();await jobs[0];await tick();assert.equal(started.length,2);
  holds[1].resolve();await Promise.all(jobs);await gate.idle();assert.deepEqual(started,['a','b','c']);
});

test('same-room readers wait and writer FIFO prevents an endless stream of reads overtaking',async()=>{
  const gate=new TaskAdmission(()=>({maxConcurrentReadOnly:4})),holds=[deferred(),deferred(),deferred()],started=[];
  const tasks=[descriptor('a','a','research','room'),descriptor('b','b','research','room'),descriptor('w','w','develop','other'),descriptor('c','c')];
  const jobs=gate.submitBatch(tasks.map((task,index)=>({task,operation:async()=>{started.push(task.id);if(index<3)await holds[index].promise;}})));
  await until(()=>started.length===1);holds[0].resolve();await until(()=>started.length===2);assert.deepEqual(started,['a','b']);
  holds[1].resolve();await until(()=>started.length===3);assert.equal(started[2],'w');holds[2].resolve();await Promise.all(jobs);assert.deepEqual(started,['a','b','w','c']);
});

async function fixture(t,{limits={},run,authorize}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-task-parallel-')),store=new Store(root),config=exampleConfig({workspace:root});
  const actors=['100000000000000002','100000000000000004','100000000000000006','100000000000000008'];
  config.discord.operators=actors;config.worker.actions=['research','summarize','develop'];config.worker.taskLimits=limits;
  const started=[],controls=new Map(),errors=[];let sequence=0,running=0,peak=0;
  const pipeline=new Pipeline({store,config,authorize,worker:{run:async(task,context,{signal})=>{
    const hold=deferred();controls.set(task.id,hold);started.push(task);running++;peak=Math.max(peak,running);
    try{if(run)return await run(task,context,{signal,hold});await hold.promise;return {state:'needs_review',summary:'candidate',artifacts:[]};}finally{running--;}
  }},onError:code=>errors.push(code)});
  t.after(async()=>{for(const control of controls.values())control.resolve();await pipeline.close();store.close();await rm(root,{recursive:true,force:true});});
  async function request(index,action='research',text='fixture'){
    const actor=actors[index],source={provider:'discord',guildId:config.discord.guildId,channelId:'20000000000000000'+index,sourceId:'parallel-'+sequence++,actorId:actor,readers:[actor],revision:1,text,final:true};
    return pipeline.request(source,{title:action,request:text,action});
  }
  return {store,pipeline,request,started,controls,errors,config,peak:()=>peak};
}

test('opt-in read-only Tasks overlap across actors and rooms, retaining the current owner result',async t=>{
  const f=await fixture(t,{limits:{maxConcurrentReadOnly:2}}),a=await f.request(0),b=await f.request(1),c=await f.request(0,'summarize');
  await until(()=>f.started.length===2);assert.equal(f.peak(),2);assert.equal(f.pipeline.taskAdmission.status().queued,1);
  f.controls.get(b.id).resolve();await tick();assert.equal(f.started.length,2,'same actor must wait for its existing Task');
  f.controls.get(a.id).resolve();await until(()=>f.started.length===3);f.controls.get(c.id).resolve();await f.pipeline.tail;
  for(const task of [a,b,c])assert.equal(f.store.taskInternal(task.id).state,'needs_review');
});

test('a waiting writer is a barrier and never overlaps readers or another writer',async t=>{
  const f=await fixture(t,{limits:{maxConcurrentReadOnly:4}}),a=await f.request(0),b=await f.request(1,'develop'),c=await f.request(2,'develop'),d=await f.request(3,'summarize');
  await until(()=>f.started.length===1);f.controls.get(a.id).resolve();await until(()=>f.started.length===2);assert.equal(f.started[1].id,b.id);
  f.controls.get(b.id).resolve();await until(()=>f.started.length===3);assert.equal(f.started[2].id,c.id);
  f.controls.get(c.id).resolve();await until(()=>f.started.length===4);f.controls.get(d.id).resolve();await f.pipeline.tail;assert.equal(f.peak(),1);
});

test('overflow cancels only the refused owner revision and stopping a pending Task frees capacity',async t=>{
  const f=await fixture(t,{limits:{maxQueued:1}}),a=await f.request(0),b=await f.request(1);
  await assert.rejects(f.request(2),/TASK_QUEUE_FULL/);assert.equal(f.store.tasks(f.config.discord.operators[2])[0].state,'cancelled');
  await f.pipeline.stop(b.id,b.actor);assert.equal(f.store.taskInternal(b.id).state,'cancelled');assert.equal(f.pipeline.taskAdmission.status().queued,0);
  const c=await f.request(2);f.controls.get(a.id).resolve();await until(()=>f.controls.has(c.id));f.controls.get(c.id).resolve();await f.pipeline.tail;
  assert(!f.started.some(task=>task.id===b.id));
});

test('running cancellation retains the slot until the actual worker settles',async t=>{
  const f=await fixture(t),a=await f.request(0),b=await f.request(1);await until(()=>f.started.length===1);
  await f.pipeline.stop(a.id,a.actor);await tick();assert.equal(f.started.length,1);assert.equal(f.store.taskInternal(a.id).state,'stopping');
  f.controls.get(a.id).resolve();await until(()=>f.started.length===2);f.controls.get(b.id).resolve();await f.pipeline.tail;
  assert.equal(f.store.taskInternal(a.id).state,'cancelled');
});

test('duplicate owner requests execute once and policy reduction delays queued readers',async t=>{
  const f=await fixture(t,{limits:{maxConcurrentReadOnly:2}}),a=await f.request(0),b=await f.request(1),c=await f.request(2);
  // The same owner identity is already admitted; another notification cannot
  // create a second worker for the same revision.
  assert.doesNotThrow(()=>f.pipeline.enqueue(a.id,a.actor,a.revision));
  await until(()=>f.started.length===2);f.config.worker.taskLimits.maxConcurrentReadOnly=1;f.controls.get(a.id).resolve();await tick();assert.equal(f.started.length,2);
  f.controls.get(b.id).resolve();await until(()=>f.started.length===3);f.controls.get(c.id).resolve();await f.pipeline.tail;
  assert.equal(f.started.filter(task=>task.id===a.id).length,1);
});

test('an unconfirmed process stop drains admission and preserves queued work for owner recovery',async t=>{
  const f=await fixture(t,{run:async(task,context,{hold})=>{await hold.promise;throw new Refused('STOP_UNCONFIRMED');}}),a=await f.request(0),b=await f.request(1);
  await until(()=>f.controls.has(a.id));f.controls.get(a.id).resolve();await f.pipeline.tail;
  assert.equal(f.pipeline.draining,true);assert.equal(f.started.length,1);assert.equal(f.store.taskInternal(a.id).state,'uncertain');assert.equal(f.store.taskInternal(b.id).state,'queued');
  assert.equal(f.store.reconcileInterrupted(),1);assert.equal(f.store.taskInternal(b.id).state,'paused');
});

test('input and result byte limits reject before publishing successful owner results',async t=>{
  const input=await fixture(t,{limits:{maxInputBytes:1024}}),a=await input.request(0,'research','x'.repeat(1100));await input.pipeline.tail;
  assert.equal(input.started.length,0);assert.equal(input.store.taskInternal(a.id).state,'failed');assert(input.errors.includes('TASK_INPUT_BYTES_EXCEEDED'));
  const output=await fixture(t,{limits:{maxResultBytes:1024},run:async()=>({state:'needs_review',summary:'x'.repeat(1100),artifacts:[]})}),b=await output.request(0);await output.pipeline.tail;
  assert.equal(output.store.taskInternal(b.id).state,'failed');assert(output.errors.includes('TASK_RESULT_BYTES_EXCEEDED'));
});

test('closing does not start pending work and leaves its identity for existing restart reconciliation',async t=>{
  const f=await fixture(t),a=await f.request(0),b=await f.request(1);await until(()=>f.controls.has(a.id));const closing=f.pipeline.close();
  f.controls.get(a.id).resolve();await closing;assert.equal(f.started.length,1);assert.equal(f.store.taskInternal(b.id).state,'queued');
  assert.equal(f.store.reconcileInterrupted(),1);assert.equal(f.store.taskInternal(b.id).state,'paused');
});


for(const maxQueued of [1,32])test(`late older admission retains the newer queued owner revision with capacity ${maxQueued}`,async t=>{
  const paused=deferred(),seen=deferred();let block=false;
  const f=await fixture(t,{limits:{maxQueued},authorize:async task=>{if(block&&task.source_revision===1&&task.actor==='100000000000000004'){block=false;seen.resolve();await paused.promise;}}});
  const blocker=await f.request(0);await until(()=>f.controls.has(blocker.id));
  const source=revision=>({provider:'discord',guildId:f.config.discord.guildId,channelId:'200000000000000001',sourceId:'superseded',actorId:f.config.discord.operators[1],readers:[f.config.discord.operators[1]],revision,text:'fixture',final:true});
  const request=revision=>f.pipeline.request(source(revision),{title:'research',request:'fixture',action:'research'});
  block=true;const old=request(1);await seen.promise;const latest=await request(2);
  paused.resolve();await old;assert.notEqual(f.pipeline.draining,true);assert.equal(f.pipeline.taskAdmission.status().queued,1);f.controls.get(blocker.id).resolve();await until(()=>f.controls.has(latest.id));
  assert.equal(f.started.filter(task=>task.id===latest.id).length,1);assert.equal(f.started.find(task=>task.id===latest.id).revision,latest.revision);
  f.controls.get(latest.id).resolve();await f.pipeline.tail;assert.equal(f.store.taskInternal(latest.id).state,'needs_review');
});

test('input cap measures the exact worker task including context bindings',async t=>{
  const measured=[],f=await fixture(t,{limits:{maxInputBytes:1024},run:async(task,context)=>{measured.push(Buffer.byteLength(JSON.stringify({task,context})));return {state:'needs_review',summary:'ok',artifacts:[]};}});
  for(let size=0;size<=300;size+=10){
    const actor=f.config.discord.operators[0],source={provider:'discord',guildId:f.config.discord.guildId,channelId:String(200000000000000000n+BigInt(size)),sourceId:'byte'+size,actorId:actor,readers:[actor],revision:1,text:'x'.repeat(size),final:true};
    await f.pipeline.request(source,{title:'read',request:'read',action:'research'});await f.pipeline.tail;
  }
  assert(measured.length>0);assert(measured.every(bytes=>bytes<=1024),JSON.stringify(measured));assert(f.errors.includes('TASK_INPUT_BYTES_EXCEEDED'));
});
