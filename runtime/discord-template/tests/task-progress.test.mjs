import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {Config,exampleConfig,loadConfig} from '../src/config.mjs';
import {atomicJson,inside} from '../src/common.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {QuietTaskProgress} from '../src/task-progress.mjs';
import {Pipeline} from '../src/pipeline.mjs';

async function fixture(t,{enabled=true,otherReader=false,acknowledge=true}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'quiet-progress-')),config=exampleConfig({workspace:root});config.dataDir=root;config.discord.voiceChannelId=config.discord.resultChannelId;config.notifications.taskProgress.enabled=enabled;
  const store=new Store(root),actor=config.discord.operators[0],other='100000000000000099';if(otherReader)config.voice.participantIds.push(other);
  const source={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.voiceChannelId,sourceId:'synthetic-source',actorId:actor,readers:otherReader?[actor,other]:[actor],revision:1,final:true,text:'SYNTHETIC_PRIVATE_REQUEST',metadata:{kind:'voice',voiceEpoch:7}};
  const sr=store.ingest(source),s=store.source(sr.key,actor),task=store.createTask(s,{key:'synthetic',title:'SYNTHETIC_PRIVATE_REQUEST',request:source.text,action:'research',acceptance:[]});
  const edits=[],sent=[],errors=[];let now=100000,active=true,members=[actor];
  const pipeline={owner:store,readPolicy:async()=>config,authorize:async()=>{}};
  const adapter=new DiscordAdapter({config,store,pipeline,onError:e=>errors.push(e)});adapter.verifiedInstallation=true;
  adapter.voice={target:{guildId:source.guildId,voiceChannelId:source.channelId},epoch:7,generation:0,paused:false,recovering:false,connectionReady:()=>active,audience:()=>[...members],audienceAllowed:()=>members.every(a=>config.voice.participantIds.includes(a)),dispose:async()=>{}};
  const dm={messages:{edit:async(id,payload)=>{edits.push({id,...payload});return {id};}}};
  const user={send:async payload=>{sent.push(payload);return {id:'200000000000000001'};},createDM:async()=>dm};
  adapter.member=async()=>({});adapter.canRead=async()=>true;adapter.client.channels.fetch=async id=>({id});adapter.client.users.fetch=async()=>user;adapter.progress.clock=()=>now;
  t.after(async()=>{await adapter.close();store.close();assert(inside(os.tmpdir(),root)&&path.basename(root).startsWith('quiet-progress-'));await rm(root,{recursive:true,force:true});});
  if(acknowledge)await adapter.acknowledgeTask(task);sent.length=0;
  return {root,config,store,actor,source:s,task,adapter,pipeline,edits,sent,errors,dm,user,advance:n=>{now+=n;},depart:()=>{active=false;members=[];},setMembers:value=>{members=value;},start:()=>store.claim(task.id,task.revision),tick:()=>adapter.progress.tick()};
}

test('default off and strict limits; remote Task owners are refused when enabled',async t=>{
  assert.equal(exampleConfig().notifications.taskProgress.enabled,false);
  for(const limits of [{minIntervalSeconds:29},{maxUpdates:7},{maxUpdates:0},{enabled:true,unknown:true}])assert.throws(()=>Config.parse({...exampleConfig(),notifications:{taskProgress:limits}}));
  const f=await fixture(t,{enabled:false});f.start();await f.tick();assert.equal(f.edits.length,0);assert.equal(f.sent.length,0);
  const file=path.join(f.root,'config.json');await atomicJson(file,{...f.config,owner:{kind:'remote',url:'http://127.0.0.1:1',tokenEnv:'SYNTHETIC_TOKEN'},notifications:{taskProgress:{enabled:true}}});await assert.rejects(loadConfig(file),/QUIET_PROGRESS_LOCAL_OWNER_REQUIRED/);
});

test('only the existing start DM is edited, once per current state; no request text or speech is added',async t=>{
  const f=await fixture(t);f.start();await f.tick();assert.equal(f.edits.length,1);assert.equal(f.edits[0].id,'200000000000000001');assert.match(f.edits[0].content,/確認時点/);assert(!f.edits[0].content.includes('SYNTHETIC_PRIVATE_REQUEST'));assert.equal(f.sent.length,0);
  f.advance(30000);f.store.event('task.started',{},f.task.id);await f.tick();assert.equal(f.edits.length,1);
  f.store.finish(f.task.id,1,{state:'needs_review',summary:'SYNTHETIC_RESULT',artifacts:[]});await f.tick();assert.equal(f.edits.length,2);assert.match(f.edits[1].content,/確認待ち/);assert(!f.edits[1].content.includes('SYNTHETIC_RESULT'));assert.equal(f.store.taskInternal(f.task.id).state,'needs_review');
});

test('a delayed start DM triggers a fresh current-state check after earlier events were consumed',async t=>{
  const f=await fixture(t,{acknowledge:false});let release,entered;const sending=new Promise(r=>{entered=r;});
  f.user.send=async()=>{entered();return new Promise(r=>{release=()=>r({id:'200000000000000001'});});};
  const ack=f.adapter.acknowledgeTask(f.task);await sending;f.start();await f.tick();assert.equal(f.edits.length,0);
  release();await ack;await f.tick();assert.equal(f.edits.length,1);assert.match(f.edits[0].content,/実行中/);
});

test('stop, confirmed cancellation and resume keep the existing DM across Task revisions',async t=>{
  const f=await fixture(t);f.start();await f.tick();f.advance(30000);f.store.cancel(f.task.id,f.actor);await f.tick();assert.equal(f.edits.length,2);assert.match(f.edits[1].content,/停止処理中/);
  f.advance(30000);f.store.confirmStop(f.task.id,f.actor,true);await f.tick();assert.equal(f.edits.length,3);assert.match(f.edits[2].content,/停止済み/);
  f.advance(30000);const resumed=f.store.resume(f.task.id,f.actor);f.store.claim(resumed.id,resumed.revision);await f.tick();assert.equal(f.edits.length,4);assert.match(f.edits[3].content,/実行中/);assert.match(f.edits[3].content,/版: 3/);
  assert(f.edits.every(item=>item.id==='200000000000000001'));assert.equal(f.sent.length,0);
});

test('spacing, task-wide cap and deduplication survive a restarted progress reader',async t=>{
  const f=await fixture(t);f.config.notifications.taskProgress.maxUpdates=2;f.start();await f.tick();f.store.finish(f.task.id,1,{state:'failed',summary:'failed',artifacts:[]});await f.tick();assert.equal(f.edits.length,1);
  f.advance(30000);f.store.event('task.result',{},f.task.id);await f.tick();assert.equal(f.edits.length,2);
  await f.adapter.progress.close();f.adapter.progress=new QuietTaskProgress({store:f.store,policy:()=>f.config,deliver:(task,options)=>f.adapter.updateTaskProgress(task,options),clock:()=>999999,onError:e=>f.errors.push(e)});
  await f.tick();f.store.cancel(f.task.id,f.actor);const newer=f.store.taskInternal(f.task.id);f.adapter.progress.remember(newer,'200000000000000001');await f.tick();assert.equal(f.edits.length,2);
});

test('quiet hours, departed room, denied participant and disabled intervals are skipped without cancelling work',async t=>{
  const f=await fixture(t);f.start();f.adapter.notifications.quiet=()=>true;await f.tick();assert.equal(f.edits.length,0);
  f.adapter.notifications.quiet=()=>false;f.setMembers([f.actor,'100000000000000099']);f.store.event('task.started',{},f.task.id);await f.tick();assert.equal(f.edits.length,0);
  f.setMembers([f.actor]);f.config.notifications.taskProgress.enabled=false;f.store.event('task.started',{},f.task.id);await f.tick();f.config.notifications.taskProgress.enabled=true;await f.tick();assert.equal(f.edits.length,0);
  f.depart();f.store.event('task.started',{},f.task.id);await f.tick();assert.equal(f.edits.length,0);assert.equal(f.store.taskInternal(f.task.id).state,'running');
});

test('a consented participant without source access cannot receive progress even indirectly',async t=>{
  const f=await fixture(t),other='100000000000000099';f.config.voice.participantIds.push(other);f.setMembers([f.actor,other]);f.start();await f.tick();assert.equal(f.edits.length,0);assert(f.errors.includes('SOURCE_ACCESS_DENIED'));
});

for(const change of ['operator','source','task','epoch','permission','disable'])test('recheck '+change+' changes after asynchronous DM lookup',async t=>{
  const f=await fixture(t);f.start();f.user.createDM=async()=>{
    if(change==='operator')f.config.discord.operators=[];
    if(change==='source')f.store.ingest({...f.source,revision:2,withdrawn:true,text:''});
    if(change==='task')f.store.finish(f.task.id,1,{state:'failed',summary:'failed',artifacts:[]});
    if(change==='epoch')f.adapter.voice.epoch++;
    if(change==='permission')f.adapter.canRead=async()=>false;
    if(change==='disable')f.config.notifications.taskProgress.enabled=false;
    return f.dm;
  };await f.tick();assert.equal(f.edits.length,0);assert.equal(f.store.statement("SELECT count(*) AS n FROM events WHERE type='task.progress_attempt'").get().n,0);
});

for(const event of ['threadUpdate','channelDelete','guildUpdate'])test('permission event '+event+' during final owner authorization invalidates audience proof',async t=>{
  const f=await fixture(t,{otherReader:true}),other='100000000000000099';f.setMembers([f.actor,other]);let revoked=false;
  f.adapter.canRead=async(_channel,actor)=>actor!==other||!revoked;
  f.pipeline.authorize=async()=>{revoked=true;f.adapter.client.emit(event,{guildId:f.source.guildId},{guildId:f.source.guildId});};
  f.start();await f.tick();assert.equal(f.edits.length,0);assert.equal(f.store.statement("SELECT count(*) AS n FROM events WHERE type='task.progress_attempt'").get().n,0);
});

test('an uncertain edit is not resent; close waits for its owned in-flight request',async t=>{
  const f=await fixture(t);let release,entered;const started=new Promise(r=>{entered=r;});f.dm.messages.edit=async()=>{entered();await new Promise(r=>{release=r;});throw Error('SYNTHETIC_PRIVATE_ERROR');};f.start();const tick=f.tick();await started;const close=f.adapter.progress.close();let closed=false;void close.then(()=>{closed=true;});await new Promise(r=>setImmediate(r));assert.equal(closed,false);release();await tick;await close;assert(f.errors.includes('PROGRESS_EDIT_UNKNOWN'));assert(!f.errors.includes('SYNTHETIC_PRIVATE_ERROR'));
  const retry=new QuietTaskProgress({store:f.store,policy:()=>f.config,clock:()=>999999,deliver:async(task,{claim})=>{assert.equal(claim(),false);}});f.store.event('task.started',{},f.task.id);await retry.tick();await retry.close();
});

test('a real worker still completes after leaving the VC; progress creates no extra Task or message',async t=>{
  const f=await fixture(t);let release;
  const pipeline=new Pipeline({store:f.store,config:f.config,analyzer:{},worker:{run:async()=>new Promise(r=>{release=()=>r({state:'needs_review',summary:'done',artifacts:[]});})}});
  pipeline.enqueue(f.task.id,f.actor,1);while(!release)await new Promise(r=>setImmediate(r));f.depart();await f.tick();release();await pipeline.tail;await pipeline.close();assert.equal(f.store.taskInternal(f.task.id).state,'needs_review');assert.equal(f.store.tasks(f.actor).length,1);assert.equal(f.edits.length,0);assert.equal(f.sent.length,0);
});
