import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Config,exampleConfig} from '../src/config.mjs';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {CliWorker} from '../src/worker.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {swarmPayload} from '../src/swarm-worker.mjs';
import {Analysis} from '../src/llm.mjs';
import {runCommand} from '../src/command.mjs';
import {resultFiles} from '../src/result-files.mjs';

const actor='100000000000000002';
const python=process.env.KOTODAMA_TEST_SWARM_PYTHON??process.env.KOTODAMA_TEST_PYTHON??'python3';
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'kotodama-swarm-worker-')),dataDir=path.join(root,'data');await mkdir(dataDir);
  const base=exampleConfig({workspace:root}),config=Config.parse({...base,dataDir,worker:{...base.worker,actions:['swarm_research'],swarm:{pythonExecutable:python,codexExecutable:'model-must-not-run',maxDailyTasks:3,ownerRef:'ref/owner/synthetic',authorityRef:'ref/authority/synthetic',authorityExpiresAt:new Date(Date.now()+3600000).toISOString()}}});
  const store=new Store(dataDir),errors=[];
  const pipeline=new Pipeline({store,config,analyzer:{analyze:async()=>{throw Error('analyzer-must-not-run');}},worker:new CliWorker(config,{store,syntheticSwarmFixture:true}),onError:code=>errors.push(code)});
  t.after(async()=>{await pipeline.close();store.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('kotodama-swarm-worker-'));await rm(root,{recursive:true,force:true});});
  const source=(id='100000000000000010')=>({provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:id,actorId:actor,revision:1,final:true,readers:[actor],text:'合成資料の観測値42と不明事項を示してください。',metadata:{kind:'command'}});
  return {root,config,store,pipeline,source,errors};
}

test('swarm is an optional manual action and does not widen model-selected or default actions',()=>{
  const base=exampleConfig();assert(!base.worker.actions.includes('swarm_research'));assert.equal(base.worker.swarm,undefined);
  const configured=Config.parse({...base,worker:{...base.worker,swarm:{ownerRef:'ref/owner/demo',authorityRef:'ref/authority/demo',authorityExpiresAt:'2099-01-01T00:00:00Z'}}});
  assert.equal(configured.worker.swarm.maxDailyTasks,0);
  assert.equal(Analysis.safeParse({summary:'fixture',intents:[{kind:'request',action:'swarm_research',title:'fixture',request:'fixture',explicit:true,complete:true,acceptance:[]}],replyRequested:false,reply:''}).success,false);
  assert.equal(Config.safeParse({...base,worker:{...configured.worker,swarm:{...configured.worker.swarm,backend:'synthetic'}}}).success,false);
});

test('remote, trusted CLI, zero budget and disabled actions refuse before Source or Task writes',async t=>{
  const f=await fixture(t),request={title:'fixture',request:'fixture',action:'swarm_research'};
  await assert.rejects(f.pipeline.request({...f.source(),metadata:{kind:'trusted_cli'}},request),{code:'SWARM_REQUIRES_SLASH_COMMAND'});
  f.config.worker.swarm.maxDailyTasks=0;await assert.rejects(f.pipeline.request(f.source(),request),{code:'SWARM_BUDGET_REQUIRED'});
  f.config.worker.swarm.maxDailyTasks=3;f.config.worker.actions=[];await assert.rejects(f.pipeline.request(f.source(),request),{code:'ACTION_NOT_ALLOWED'});
  f.config.worker.actions=['swarm_research'];f.config.owner={kind:'remote',url:'http://127.0.0.1',tokenEnv:'UNUSED'};
  await assert.rejects(f.pipeline.request(f.source(),request),{code:'SWARM_LOCAL_OWNER_REQUIRED'});
  assert.equal(f.store.statement('SELECT count(*) AS n FROM sources').get().n,0);assert.equal(f.store.statement('SELECT count(*) AS n FROM tasks').get().n,0);
});

test('daily reservations live in the same owner and cannot be reused or renewed by clock rollback',async t=>{
  const f=await fixture(t),tasks=[];
  for(let i=0;i<3;i++){const receipt=f.store.ingest(f.source('source-'+i)),s=f.store.source(receipt.key,actor);const task=f.store.createTask(s,{title:'fixture',request:'fixture',action:'swarm_research',intentIds:[]},'request-'+i);f.store.claim(task.id,task.revision);tasks.push(task);}
  assert.equal(f.store.reserveSwarmExecution(tasks[0].id,1,1,'2026-10-08'),true);
  assert.equal(f.store.reserveSwarmExecution(tasks[0].id,1,1,'2026-10-08'),false);
  assert.throws(()=>f.store.reserveSwarmExecution(tasks[1].id,1,1,'2026-10-08'),{code:'SWARM_DAILY_LIMIT'});
  assert.throws(()=>f.store.reserveSwarmExecution(tasks[1].id,1,3,'2026-10-07'),{code:'SWARM_CLOCK_ROLLBACK'});
  assert.equal(f.store.reserveSwarmExecution(tasks[1].id,1,1,'2026-10-09'),true);
  assert.equal(f.store.statement('SELECT count(*) AS n FROM tasks').get().n,3);
});

test('payload keeps exact Source versions and refuses silent truncation or incomplete bindings',()=>{
  const source={key:'a'.repeat(64),revision:1,text:'日本語😀資料'},task={id:'task-00000000-0000-4000-8000-000000000001',revision:1,source_key:source.key,source_revision:1,contextSources:[{key:source.key,revision:1}],request:'依頼',acceptance:['条件']};
  assert.equal(swarmPayload(task,[source]).sources[0].text,source.text);
  assert.throws(()=>swarmPayload(task,[{...source,text:'x'.repeat(12001)}]),{code:'SWARM_SOURCE_LIMIT'});
  assert.throws(()=>swarmPayload({...task,contextSources:[]},[source]),{code:'SWARM_CONTEXT_BINDING_MISMATCH'});
});

test('a liveness stdin remains open until a normally exiting child finishes',{timeout:30000},async()=>{
  const result=await runCommand(process.execPath,['-e',"process.stdin.on('end',()=>process.exit(9));process.stdin.resume();setTimeout(()=>{console.log('parent-pipe-open');process.exit(0)},100)"],{keepStdinOpen:true,timeoutMs:10000});
  assert.equal(result.code,0);assert.match(result.stdout,/parent-pipe-open/);
  await assert.rejects(runCommand(process.execPath,['-e','process.exit(0)'],{keepStdinOpen:true,input:'not-a-liveness-pipe'}),{code:'COMMAND_STDIN_POLICY_INVALID'});
});

test('Windows rejects a granted swarm Task before process launch or quota reservation',{skip:process.platform!=='win32'},async t=>{
  const f=await fixture(t);const task=await f.pipeline.request(f.source(),{title:'fixture',request:'fixture',action:'swarm_research'});await f.pipeline.tail;
  const latest=f.store.taskInternal(task.id);assert.equal(latest.state,'failed');assert.equal(latest.result.summary,'SWARM_WORKER_REQUIRES_POSIX_HOST');
  assert.equal(f.store.statement("SELECT count(*) AS n FROM events WHERE type='worker.started'").get().n,0);assert.equal(f.store.statement('SELECT count(*) AS n FROM swarm_reservations').get().n,0);
});

test('failed and uncertain results use truthful DM headings',async t=>{
  const f=await fixture(t),messages=[],adapter=new DiscordAdapter({config:f.config,store:f.store,pipeline:{authorize:async()=>{}},onError:code=>f.errors.push(code)});
  t.after(()=>adapter.client.destroy());adapter.member=async()=>({});adapter.canRead=async()=>true;adapter.client.channels.fetch=async()=>({});adapter.client.users.fetch=async()=>({send:async value=>{messages.push(value);return {id:'delivered-'+messages.length};}});
  for(const state of ['failed','uncertain']){
    const receipt=f.store.ingest(f.source('source-'+state)),s=f.store.source(receipt.key,actor),task=f.store.createTask(s,{title:'fixture',request:'fixture',action:'swarm_research',intentIds:[]},state);
    f.store.claim(task.id,task.revision);f.store.finish(task.id,task.revision,{state,summary:'SYNTHETIC_FAILURE',artifacts:[]});await adapter.deliver(f.store.task(task.id,actor));
  }
  assert.equal(messages.length,2);assert.match(messages[0].content,/失敗/);assert.match(messages[1].content,/状態を確認/);assert(messages.every(m=>!m.content.includes('成果ができました')));
});

test('an observed worker failure reaches the existing notification callback after owner finish',async t=>{
  const f=await fixture(t),delivered=[];f.pipeline.worker={run:async()=>{throw new Error('synthetic worker failure');}};f.pipeline.onTask=async task=>delivered.push(task);
  const task=await f.pipeline.request(f.source(),{title:'fixture',request:'fixture',action:'swarm_research'});await f.pipeline.tail;
  assert.equal(delivered.length,1);assert.equal(delivered[0].id,task.id);assert.equal(delivered[0].state,'failed');assert.equal(f.store.taskInternal(task.id).state,'failed');
});

test('actual slash command creates one Task, Python swarm, independent fixture review and result attachment',{skip:process.platform==='win32',timeout:60000},async t=>{
  const f=await fixture(t),adapter=new DiscordAdapter({config:f.config,store:f.store,pipeline:f.pipeline,onError:code=>f.errors.push(code)});adapter.verifiedInstallation=true;adapter.member=async()=>({id:actor,guild:{id:f.config.discord.guildId}});
  t.after(()=>adapter.client.destroy());
  const replies=[],interaction={id:'100000000000000015',createdTimestamp:Date.now(),guildId:f.config.discord.guildId,channelId:f.config.discord.resultChannelId,user:{id:actor},commandName:'kotodama',isChatInputCommand:()=>true,isButton:()=>false,options:{getSubcommand:()=> 'do',getString:name=>name==='action'?'swarm_research':'合成資料の観測値42と不明事項を示してください。'},deferReply:async()=>{},editReply:async value=>replies.push(value)};
  await adapter.interaction(interaction);await f.pipeline.tail;
  assert.equal(f.store.tasks(actor).length,1);const task=f.store.tasks(actor)[0];assert.equal(task.state,'needs_review',JSON.stringify(f.errors)+JSON.stringify(replies));
  assert.equal(task.result.independentReview,true);assert.equal(task.result.synthetic,true);assert.equal(task.result.modelRuntimeVerified,false);
  const result=await f.pipeline.result(task.id,actor),files=await resultFiles(result,{artifactRoot:path.join(f.config.dataDir,'worktrees')});assert.equal(files.length,1);assert.equal(files[0].name,'swarm-research.txt');
  const starts=f.store.statement("SELECT count(*) AS n FROM events WHERE type='worker.started'").get().n;
  await adapter.interaction(interaction);await f.pipeline.tail;assert.equal(f.store.tasks(actor).length,1);assert.equal(f.store.statement("SELECT count(*) AS n FROM events WHERE type='worker.started'").get().n,starts);
  const artifact=result.artifacts.find(a=>a.relative==='deliverables/swarm-research.txt');await writeFile(artifact.path,'changed');await assert.rejects(f.pipeline.result(task.id,actor),{code:'ARTIFACT_CHANGED'});
});
