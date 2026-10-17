import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson} from '../src/common.mjs';
import {startRuntime} from '../src/runtime.mjs';

test('Skill selection drift rejects active results and a queued parallel reader before execution',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-parallel-skills-'));
  const config=exampleConfig({workspace:root}),actors=['100000000000000002','100000000000000004','100000000000000006'];
  config.dataDir=path.join(root,'data');config.discord.operators=actors;
  config.worker.taskLimits.maxConcurrentReadOnly=2;
  config.worker.projectSkills={research:[]};
  const filename=path.join(root,'config.json');await atomicJson(filename,config);
  let release,entered;
  const hold=new Promise(resolve=>{release=resolve;}),bothStarted=new Promise(resolve=>{entered=resolve;}),started=[];
  const runtime=await startRuntime(filename,{offline:true,log:()=>{},worker:{run:async task=>{
    started.push(task.id);if(started.length===2)entered();await hold;
    return {state:'needs_review',summary:'synthetic candidate',artifacts:[]};
  }}});
  t.after(async()=>{release();await runtime.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-parallel-skills-'));await rm(root,{recursive:true,force:true});});
  const tasks=[];
  for(let index=0;index<actors.length;index++){
    const source={provider:'discord',guildId:config.discord.guildId,channelId:'20000000000000000'+index,sourceId:'parallel-skill-'+index,actorId:actors[index],readers:[actors[index]],revision:1,final:true,text:'synthetic research'};
    tasks.push(await runtime.pipeline.request(source,{title:'research',request:source.text,action:'research'}));
  }
  await bothStarted;
  assert.equal(runtime.pipeline.taskAdmission.status().running,2);
  assert.equal(runtime.pipeline.taskAdmission.status().queued,1);
  config.worker.projectSkills={research:['changed-method']};await atomicJson(filename,config);
  release();await runtime.pipeline.tail;
  assert.deepEqual(new Set(started),new Set(tasks.slice(0,2).map(task=>task.id)));
  for(const task of tasks.slice(0,2)){
    const current=runtime.store.task(task.id,task.actor);
    assert.equal(current.state,'failed');assert.equal(current.result.summary,'PROJECT_SKILL_CONFIG_CHANGED');
  }
  assert.equal(runtime.store.task(tasks[2].id,tasks[2].actor).state,'cancelled');
  assert.equal(runtime.pipeline.taskAdmission.status().running,0);
  assert.equal(runtime.pipeline.taskAdmission.status().queued,0);
});
