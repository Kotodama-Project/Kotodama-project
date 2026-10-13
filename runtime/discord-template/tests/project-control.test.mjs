import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Config,exampleConfig} from '../src/config.mjs';
import {atomicJson} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';

const actor='100000000000000002',other='100000000000000009';
const brief={outcome:'原意を残す🌱',in_scope:['調査'],out_of_scope:['配備'],constraints:['原文を保持'],acceptance:['訂正を辿れる'],unknowns:['納期']};
async function fixture(t,operations=['read','create','inspect','correct']){
  const root=await mkdtemp(path.join(os.tmpdir(),'kotodama-project-control-'));
  const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.projects={operations};
  config.discord.operators.push(other);
  const file=path.join(root,'config.json');await atomicJson(file,config);
  let runtime=await startRuntime(file,{offline:true,log:()=>{},analyzer:{analyze:()=>{throw Error('unexpected model call');}},worker:{run:()=>{throw Error('unexpected worker');}}});
  t.after(async()=>{await runtime.close();await rm(root,{recursive:true,force:true});});
  const raw={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'project-fixture',actorId:actor,revision:1,final:true,readers:[actor],text:'この企画をプロジェクトにして',metadata:{kind:'text'}};
  const source={key:runtime.store.ingest(raw).key,revision:1};
  const command=input=>controlCommand(config,{action:'project',actor,...input});
  const create={operation:'create',request_id:'request-create',source,name:'調査の企画',brief};
  return {config,file,raw,source,command,create,get runtime(){return runtime;},
    restart:async()=>{await runtime.close();runtime=await startRuntime(file,{offline:true,log:()=>{}});}};
}

test('Project scope is disabled by default and rejects duplicate or unknown operations',()=>{
  assert.deepEqual(exampleConfig().projects,{operations:[]});
  for(const operations of [['read','read'],['dispatch']])assert.equal(Config.safeParse({...exampleConfig(),projects:{operations}}).success,false);
});

test('authenticated control persists one Project across duplicate delivery and runtime restart without Task creation',async t=>{
  const f=await fixture(t),results=await Promise.all([f.command(f.create),f.command(f.create)]);
  assert.equal(results[0].project.project_id,results[1].project.project_id);
  assert.equal(f.runtime.store.statement("SELECT count(*) AS n FROM events WHERE type='project.created'").get().n,1);
  assert.equal(f.runtime.store.tasks(actor).length,0);
  await f.restart();
  const read=await f.command({operation:'read',project_id:results[0].project.project_id});
  assert.equal(read.project_digest,results[0].project_digest);assert.deepEqual(read.project.brief,brief);
  assert.equal(read.execution_authorized,false);assert.equal(read.task_state_changed,false);
  await assert.rejects(f.command({...f.create,name:'同じ要求IDの別内容'}));
  await assert.rejects(f.command({operation:'read',project_id:read.project.project_id,actor:other}));
});

test('inspection has no write and correction compares revision and digest while preserving original intent',async t=>{
  const f=await fixture(t),created=await f.command(f.create);
  const change={project_id:created.project.project_id,expected_revision:1,base_digest:created.project_digest,source:f.source,reason:'納期を確認した',brief:{...brief,unknowns:[],constraints:[...brief.constraints,'今週中']}};
  const count=()=>f.runtime.store.statement('SELECT count(*) AS n FROM events').get().n;
  const before=count(),candidate=await f.command({operation:'inspect',...change});
  assert.equal(candidate.applied,false);assert.equal(count(),before);
  const corrected=await f.command({operation:'correct',request_id:'request-correct',...change});
  assert.equal(corrected.project.revision,2);assert.equal(corrected.project.original_ref,created.project.original_ref);
  assert.deepEqual(corrected.project.brief,change.brief);assert.equal(corrected.task_state_changed,false);
  const after=count();await assert.rejects(f.command({operation:'correct',request_id:'stale-write',...change}));assert.equal(count(),after);
  const duplicate=await f.command({operation:'correct',request_id:'request-correct',...change});
  assert.equal(duplicate.project_digest,corrected.project_digest);assert.equal(count(),after);
  assert.equal(f.runtime.store.tasks(actor).length,0);
});

test('current policy revocation, source access loss, and owner change refuse Project operations',async t=>{
  const f=await fixture(t),created=await f.command(f.create),read={operation:'read',project_id:created.project.project_id};
  f.config.projects.operations=[];await atomicJson(f.file,f.config);await assert.rejects(f.command(read));
  f.config.projects.operations=['read','create','inspect','correct'];await atomicJson(f.file,f.config);
  f.runtime.store.ingest({...f.raw,revision:2,readers:[]});await assert.rejects(f.command(read));await assert.rejects(f.command(f.create));
  f.runtime.store.ingest({...f.raw,revision:3});
  const restored=await f.command(read);assert.equal(restored.project.original_ref,created.project.original_ref);
  f.config.owner={kind:'remote',url:'http://127.0.0.1:1',tokenEnv:'PROJECT_SYNTHETIC_OWNER'};await atomicJson(f.file,f.config);
  await assert.rejects(f.command(read));
});

test('Project request rejects extra authority fields and an unconfigured installation',async t=>{
  const f=await fixture(t,[]);await assert.rejects(f.command(f.create));
  assert.equal(f.runtime.store.tasks(actor).length,0);
  const g=await fixture(t);
  await assert.rejects(g.command({...g.create,owner_ref:'ref/foreign'}));
  await assert.rejects(g.command({...g.create,source:{...g.source,revision:2}}));
  assert.equal(g.runtime.store.statement("SELECT count(*) AS n FROM events WHERE type='project.created'").get().n,0);
});

test('control accepts full Unicode and escaped Project briefs while bounding all commands',async t=>{
  const f=await fixture(t);
  for(const [index,unit] of ['🌱','\u0001'].entries()){
    const large={outcome:unit.repeat(4000)};
    for(const field of ['in_scope','out_of_scope','constraints','acceptance','unknowns'])large[field]=Array.from({length:20},(_,i)=>String.fromCharCode(65+i)+unit.repeat(999));
    assert.ok(Buffer.byteLength(JSON.stringify(large))>400000);
    const saved=await f.command({...f.create,request_id:`large-${index}`,brief:large});
    assert.deepEqual(saved.project.brief,large);
    assert.deepEqual((await f.command({operation:'read',project_id:saved.project.project_id})).project.brief,large);
  }
  await assert.rejects(controlCommand(f.config,{action:'tasks',actor,padding:'x'.repeat(200000)}),/CONTROL_BODY_LIMIT/);
  await assert.rejects(f.command({...f.create,padding:'x'.repeat(750000)}),/CONTROL_BODY_LIMIT/);
  assert.equal(f.runtime.store.statement('SELECT count(*) AS n FROM projects').get().n,2);
});
