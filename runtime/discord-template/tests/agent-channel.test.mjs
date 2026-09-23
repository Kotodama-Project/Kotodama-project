import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {exampleConfig,loadConfig} from '../src/config.mjs';

const actor='100000000000000002',other='100000000000000009',agentChannel='100000000000000021',plainChannel='100000000000000003';
const source=(extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:plainChannel,sourceId:'message-1',actorId:actor,revision:1,readers:[actor],text:'資料を作って',final:true,...extra});
const intent=(extra={})=>({kind:'request',title:'資料作成',request:'資料を作って',action:'write_file',explicit:true,complete:true,acceptance:['本文がある'],...extra});
const analysis=(items=[intent()])=>({summary:'資料作成の依頼',intents:items,replyRequested:false,reply:''});
async function temp(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-agent-channel-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}
// Close the store before removing its directory: Windows cannot unlink an open SQLite file.
async function fixture(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-agent-channel-')),store=new Store(root);t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});return {root,store};}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('a request extracted from conversation is acknowledged at once and still runs once',async t=>{
  const {root,store}=await fixture(t);
  const config=exampleConfig({workspace:root});config.worker.actions=['write_file'];const queued=[];let runs=0;
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>analysis()},worker:{run:async()=>{runs++;return {state:'needs_review',summary:'候補',artifacts:[]};}},onTaskQueued:async(task,options)=>{queued.push({task,options});}});
  const receipt=await p.ingest(source(),{execute:true});await p.tail;await settle();
  assert.equal(receipt.tasks.length,1);assert.equal(queued.length,1);assert.equal(queued[0].task.id,receipt.tasks[0]);assert.equal(queued[0].task.title,'資料作成');assert.deepEqual(queued[0].options,{revised:false});assert.equal(runs,1);
});

test('chat, questions and non-executable turns are never acknowledged as work',async t=>{
  const {root,store}=await fixture(t);
  const config=exampleConfig({workspace:root});config.worker.actions=['write_file'];const queued=[];
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>analysis([intent({kind:'question',explicit:false}),intent({kind:'request',explicit:true,complete:false})])},worker:{run:async()=>assert.fail('must not run')},onTaskQueued:async task=>{queued.push(task);}});
  await p.ingest(source({text:'どう思う？'}),{execute:true});await p.ingest(source({sourceId:'unaddressed',text:'資料を作って'}),{execute:false});await p.tail;await settle();
  assert.equal(queued.length,0);assert.equal(store.tasks(actor).length,0);
});

test('a re-run of the same request is acknowledged as revised',async t=>{
  const {root,store}=await fixture(t);
  const config=exampleConfig({workspace:root});config.worker.actions=['write_file'];const queued=[];
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>analysis()},worker:{run:async()=>({state:'needs_review',summary:'候補',artifacts:[]})},onTaskQueued:async(task,options)=>{queued.push(options);}});
  await p.ingest(source(),{execute:true});await p.tail;await settle();
  await p.ingest(source({revision:2,text:'資料を作って。'}),{execute:true});await p.tail;await settle();
  assert.deepEqual(queued,[{revised:false},{revised:true}]);
});

test('a failed acknowledgement is reported but never cancels the queued work',async t=>{
  const {root,store}=await fixture(t);
  const config=exampleConfig({workspace:root});config.worker.actions=['write_file'];const errors=[];let runs=0;
  const p=new Pipeline({store,config,analyzer:{analyze:async()=>analysis()},worker:{run:async()=>{runs++;return {state:'needs_review',summary:'候補',artifacts:[]};}},onTaskQueued:async()=>{throw new Error('dm unavailable');},onError:code=>errors.push(code)});
  await p.ingest(source(),{execute:true});await p.tail;await settle();
  assert.equal(runs,1);assert.deepEqual(errors,['OPERATION_FAILED']);
});

test('agent channels must be channels the Bot already reads',async t=>{
  const root=await temp(t),config=exampleConfig({workspace:root,channelId:plainChannel}),file=path.join(root,'config.json');
  config.discord.agentChannelIds=[agentChannel];await writeFile(file,JSON.stringify(config));
  await assert.rejects(loadConfig(file),{code:'AGENT_CHANNEL_NOT_TEXT_CHANNEL'});
  config.discord.textChannelIds.push(agentChannel);await writeFile(file,JSON.stringify(config));
  assert.deepEqual((await loadConfig(file)).discord.agentChannelIds,[agentChannel]);
  delete config.discord.agentChannelIds;await writeFile(file,JSON.stringify(config));
  assert.deepEqual((await loadConfig(file)).discord.agentChannelIds,[]);
});

function adapter(t){
  const config=exampleConfig({channelId:plainChannel});config.discord.textChannelIds.push(agentChannel);config.discord.agentChannelIds=[agentChannel];
  const received=[],sent=[];
  const a=new DiscordAdapter({config,store:{},pipeline:{ingest:async(s,flags)=>{received.push({s,flags});return {tasks:[]};}}});t.after(()=>a.client.destroy());
  a.verifiedInstallation=true;a.client.user={id:'bot'};a.source=async message=>({text:message.content,metadata:{kind:'text'}});
  a.client.users.fetch=async id=>({id,send:async value=>{sent.push({id,...value});return {id:'dm-'+sent.length};}});
  const message=(channelId,author,{mention=false,others=[],roles=0,replyTo=null}={})=>({guildId:config.discord.guildId,channelId,author:{id:author},content:'資料を作って',reference:replyTo?{messageId:'earlier'}:undefined,mentions:{users:new Map([...(mention?[['bot',{}]]:[]),...others.map(id=>[id,{}])]),roles:{size:roles},repliedUser:replyTo?{id:replyTo}:null}});
  return {a,config,received,sent,message};
}

test('operators do not need an @mention inside an agent channel',async t=>{
  const {a,received,message}=adapter(t);
  await a.message(message(agentChannel,actor));
  await a.message(message(agentChannel,other));
  await a.message(message(plainChannel,actor));
  await a.message(message(plainChannel,actor,{mention:true}));
  assert.deepEqual(received.map(r=>r.flags),[{execute:true,reply:true},{execute:false,reply:false},{execute:false,reply:false},{execute:true,reply:true}]);
  assert.equal(received[0].s.metadata.agentChannel,true);assert.equal(received[0].s.metadata.directlyAddressed,false,'only a real @mention asks for a reply to everything');
  assert.equal(received[3].s.metadata.directlyAddressed,true);assert.equal(received[3].s.metadata.agentChannel,undefined);
});

test('in an agent channel, messages for other people and edits do not start work',async t=>{
  const {a,received,message}=adapter(t);
  await a.message(message(agentChannel,actor,{others:[other]}));
  await a.message(message(agentChannel,actor,{roles:1}));
  await a.message(message(agentChannel,actor,{replyTo:other}));
  await a.message(message(agentChannel,actor,{replyTo:'bot'}));
  await a.message(message(agentChannel,actor),{edited:true});
  await a.message(message(agentChannel,actor,{mention:true}),{edited:true});
  assert.deepEqual(received.map(r=>r.flags.execute),[false,false,false,true,false,true]);
});

test('quiet hours hold the acknowledgement like every other DM',async t=>{
  const {a,sent}=adapter(t);a.notifications={quiet:()=>true};
  assert.deepEqual(await a.acknowledgeTask({id:'task-q',actor,title:'資料作成'}),{state:'quiet'});assert.equal(sent.length,0);
});

test('the acknowledgement goes only to the requesting operator and names the Task',async t=>{
  const {a,sent}=adapter(t);
  assert.deepEqual(await a.acknowledgeTask({id:'task-1',actor,title:'資料作成'}),{state:'sent'});
  assert.equal(sent.length,1);assert.equal(sent[0].id,actor);assert.match(sent[0].content,/走り始めました：資料作成/);assert.match(sent[0].content,/task-1/);assert.deepEqual(sent[0].allowedMentions,{parse:[]});
  await a.acknowledgeTask({id:'task-1',actor,title:'資料作成'},{revised:true});assert.match(sent[1].content,/走り直しています/);
  await assert.rejects(a.acknowledgeTask({id:'task-2',actor:other,title:'x'}),{code:'OPERATOR_REQUIRED'});
  a.verifiedInstallation=false;assert.deepEqual(await a.acknowledgeTask({id:'task-3',actor,title:'x'}),{state:'blocked'});assert.equal(sent.length,2);
});
