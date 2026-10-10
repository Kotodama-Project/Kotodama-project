import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';

const actor='100000000000000002';
const candidate={state:'needs_review',summary:'synthetic candidate',artifacts:[]};
async function fixture(t,run){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-skill-policy-'));
  const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');
  const filename=path.join(root,'config.json');await atomicJson(filename,config);
  const runtime=await startRuntime(filename,{offline:true,worker:{run},log:()=>{}});
  t.after(async()=>{await runtime.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-skill-policy-'));await rm(root,{recursive:true,force:true});});
  return {config,filename,runtime,request:()=>controlCommand(config,{action:'request',actor,operation:'research',text:'合成の調査',requestId:'skill-policy-fixture'})};
}

test('changed Skill selection is refused before Task creation or worker invocation',async t=>{
  let calls=0;const f=await fixture(t,async()=>{calls++;return candidate;});
  f.config.worker.projectSkills={research:['new-method']};await atomicJson(f.filename,f.config);
  await assert.rejects(f.request(),{code:'PROJECT_SKILL_CONFIG_CHANGED'});
  assert.equal(calls,0);assert.equal(f.runtime.store.tasks(actor).length,0);
});

test('equivalent absent and empty selections preserve existing behavior',async t=>{
  const f=await fixture(t,async()=>candidate);
  f.config.worker.projectSkills={research:[],summarize:[],develop:[],write_file:[]};await atomicJson(f.filename,f.config);
  const task=await f.request();await f.runtime.pipeline.tail;
  assert.equal(f.runtime.store.task(task.id,actor).state,'needs_review');
});

for(const checkpoint of [true,false])test(`current selection drift rejects ${checkpoint?'worker checkpoint':'final result adoption'}`,async t=>{
  let release,started;const waiting=new Promise(resolve=>{release=resolve;}),entered=new Promise(resolve=>{started=resolve;});
  const f=await fixture(t,async(task,context,options)=>{started();await waiting;if(checkpoint)await options.authorize();return candidate;});
  t.after(release);
  const task=await f.request();await entered;
  f.config.worker.projectSkills={research:['new-method']};await atomicJson(f.filename,f.config);release();
  await f.runtime.pipeline.tail;
  const current=f.runtime.store.task(task.id,actor);
  assert.equal(current.state,'failed');assert.equal(current.result.summary,'PROJECT_SKILL_CONFIG_CHANGED');
});

test('finished results remain readable under current access after selection changes',async t=>{
  const f=await fixture(t,async()=>candidate),task=await f.request();await f.runtime.pipeline.tail;
  f.config.worker.projectSkills={research:['new-method']};await atomicJson(f.filename,f.config);
  const tasks=await controlCommand(f.config,{action:'tasks',actor});assert.equal(tasks.length,1);assert.equal(tasks[0].id,task.id);
});

test('judgment status reports Skill configuration drift without granting execution',async t=>{
  const f=await fixture(t,async()=>candidate);
  f.config.worker.projectSkills={research:[]};await atomicJson(f.filename,f.config);
  const equivalent=await controlCommand(f.config,{action:'judgment',actor});
  assert(!equivalent.effective.configurationDrift.includes('projectSkills'));
  f.config.worker.projectSkills={research:['new-method']};await atomicJson(f.filename,f.config);
  const changed=await controlCommand(f.config,{action:'judgment',actor});
  assert(changed.effective.configurationDrift.includes('projectSkills'));
  assert.equal(changed.effective.executionAuthorized,false);
  assert.equal(changed.tasks.reason,'RUNTIME_CONFIGURATION_CHANGED');
});
