import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {exampleConfig} from '../src/config.mjs';
import {check,digest} from '../src/common.mjs';

async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-result-current-')),config=exampleConfig({workspace:root});config.dataDir=root;
  const store=new Store(root),actor=config.discord.operators[0];
  const raw={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'fixture',actorId:actor,readers:[actor],revision:1,text:'成果を作る',final:true};
  const source=store.source(store.ingest(raw).key,actor),created=store.createTask(source,{title:'fixture',request:'成果を作る',action:'research',contextSources:[{key:source.key,revision:1}]});
  const workspace=path.join(root,'worktrees',created.id),summary='取消後には返さない成果';
  await mkdir(path.join(workspace,'deliverables'),{recursive:true});
  const artifacts=[];
  for(const relative of ['result.md','deliverables/report.md']){const filename=path.join(workspace,relative);await writeFile(filename,summary);artifacts.push({path:filename,relative,bytes:Buffer.byteLength(summary),sha256:digest(summary)});}
  store.claim(created.id,created.revision);store.finish(created.id,created.revision,{state:'needs_review',summary,workspace,artifacts,taskRevision:created.revision,sourceRevision:1});
  let allowed=true;
  const pipeline=new Pipeline({store,config,authorize:async()=>check(allowed,'GRANT_REVOKED')});
  const adapter=new DiscordAdapter({config,store,pipeline});adapter.verifiedInstallation=true;adapter.member=async()=>({});adapter.canRead=async()=>true;adapter.client.channels.fetch=async()=>({});adapter.corrections.buttons=async()=>[];
  const replies=[],messages=[];adapter.client.users.fetch=async()=>({send:async message=>{messages.push(message);return {id:'fixture-dm'};}});
  const interaction={guildId:config.discord.guildId,channelId:source.channelId,id:'interaction',createdTimestamp:1,commandName:'kotodama',user:{id:actor},isButton:()=>false,isChatInputCommand:()=>true,options:{getSubcommand:()=> 'result',getString:()=>created.id},deferReply:async()=>{},editReply:async value=>replies.push(value)};
  t.after(async()=>{adapter.client.destroy();await pipeline.close();store.close();await rm(root,{recursive:true,force:true});});
  return {store,pipeline,adapter,actor,raw,source,task:store.task(created.id,actor),interaction,replies,messages,revoke:()=>{allowed=false;}};
}

test('generic result rechecks cancellation and grants after artifact reads',async t=>{
  for(const mode of ['cancel','grant'])await t.test(mode,async t=>{
    const f=await fixture(t),authorize=f.pipeline.authorize;let once=true;
    f.pipeline.authorize=async(...args)=>{await authorize(...args);if(once){once=false;queueMicrotask(()=>mode==='cancel'?f.store.cancel(f.task.id,f.actor):f.revoke());}};
    await assert.rejects(f.pipeline.result(f.task.id,f.actor),mode==='cancel'?/TASK_CHANGED/:/GRANT_REVOKED/);
  });
});

test('result snapshot catches cancellation during the final authorization',async t=>{
  const f=await fixture(t);let checks=0;
  f.pipeline.authorize=async()=>{if(++checks===2)f.store.cancel(f.task.id,f.actor);};
  await assert.rejects(f.pipeline.result(f.task.id,f.actor),/TASK_CHANGED/);assert.equal(checks,2);
});

test('local exposure closes the final asynchronous owner snapshot gap',async t=>{
  for(const surface of ['result','slash','delivery'])await t.test(surface,async t=>{
    const f=await fixture(t),original=f.store.task.bind(f.store);let reads=0;
    // result: initial + pre-authorize + post-authorize. Slash and delivery
    // additionally prepare their payload and perform their own final read.
    const finalRead={result:3,slash:7,delivery:4}[surface];
    f.store.task=(...args)=>{const value=original(...args);if(++reads===finalRead)queueMicrotask(()=>f.store.cancel(f.task.id,f.actor));return value;};
    if(surface==='slash'){await f.adapter.interaction(f.interaction);assert.match(f.replies[0].content,/TASK_CHANGED/);assert.equal(f.replies[0].files,undefined);}
    else await assert.rejects(surface==='result'?f.pipeline.result(f.task.id,f.actor):f.adapter.deliver(f.task),/TASK_CHANGED/);
    assert.equal(f.messages.length,0);assert.equal(f.store.taskInternal(f.task.id).state,'cancelled');
  });
});

test('Discord result refuses cancellation while preparing buttons after reading files',async t=>{
  const f=await fixture(t);f.adapter.corrections.buttons=async()=>{f.store.cancel(f.task.id,f.actor);return [];};
  await f.adapter.interaction(f.interaction);
  assert.equal(f.replies.length,1);assert.match(f.replies[0].content,/TASK_CHANGED/);assert.equal(f.replies[0].files,undefined);assert(!f.replies[0].content.includes(f.task.result.summary));
});

test('Discord delivery refuses cancellation or Source withdrawal during recipient lookup before claiming delivery',async t=>{
  for(const mode of ['cancel','withdraw'])await t.test(mode,async t=>{
    const f=await fixture(t);
    f.adapter.client.users.fetch=async()=>{if(mode==='cancel')f.store.cancel(f.task.id,f.actor);else f.store.ingest({...f.raw,revision:2,withdrawn:true});return {send:async value=>{f.messages.push(value);return {id:'stale'};}};};
    await assert.rejects(f.adapter.deliver(f.task),mode==='cancel'?/TASK_CHANGED/:/SOURCE_/);
    assert.equal(f.messages.length,0);assert.equal(f.store.deliveryState(digest([f.task.id,f.task.revision,'result'])),null);
  });
});

test('current Discord results retain attachments and a single delivery receipt',async t=>{
  const f=await fixture(t);await f.adapter.interaction(f.interaction);
  assert.equal(f.replies[0].content,f.task.result.summary);assert.equal(f.replies[0].files[0].name,'report.md');
  await f.adapter.deliver(f.task);await f.adapter.deliver(f.task);assert.equal(f.messages.length,1);assert.equal(f.messages[0].files[0].attachment.toString(),f.task.result.summary);
});
