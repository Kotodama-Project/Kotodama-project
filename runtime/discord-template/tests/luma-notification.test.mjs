import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {exampleConfig} from '../src/config.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {startBridge} from '../src/bridge.mjs';
import {parseLumaCsv,lumaSource} from '../src/integrations.mjs';

async function fixture(t,{onImported}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-luma-notify-')),store=new Store(root),config=exampleConfig(),actor=config.discord.operators[0],other='100000000000000009';
  config.discord.operators.push(other);config.bridge={enabled:true,host:'127.0.0.1',port:0,actorId:actor,tokenEnv:'KOTODAMA_TEST_NOTIFICATION_TOKEN'};config.integrations.luma={eventRef:'event-fixture',eventUrl:'https://example.invalid/event'};process.env.KOTODAMA_TEST_NOTIFICATION_TOKEN='synthetic-notification-bridge-only';
  const state={member:true,canRead:true,failSend:false,sends:[],errors:[],flags:[],workers:0,afterAccess:null};
  const pipeline=new Pipeline({store,config,analyzer:{analyze:async()=>({summary:'合成の取込',intents:[],replyRequested:false,reply:''})},worker:{run:async()=>{state.workers++;throw new Error('unexpected worker');}}});pipeline.draining=true;
  const adapter=new DiscordAdapter({config,store,pipeline,policy:()=>config,onError:code=>state.errors.push(code)});adapter.verifiedInstallation=true;adapter.voice={paused:true,control:{suspension:'provider_credit'}};
  const guild={id:config.discord.guildId,members:{fetch:async({user})=>{if(!state.member)throw new Error('membership unavailable');return {id:user,guild};}},roles:{fetch:async()=>[]}};
  const channel={id:config.discord.resultChannelId,guildId:guild.id,guild,type:0,permissionsFor:()=>({has:()=>state.canRead})};
  adapter.client.guilds.fetch=async id=>{assert.equal(id,guild.id);return guild;};adapter.client.channels.fetch=async id=>{assert.equal(id,channel.id);return channel;};
  adapter.client.users.fetch=async id=>({id,send:async message=>{state.sends.push({actor:id,message});if(state.failSend)throw new Error('synthetic private delivery diagnostic');return {id:'100000000000000077'};}});
  const canRead=adapter.canRead.bind(adapter);adapter.canRead=async(...args)=>{const allowed=await canRead(...args),after=state.afterAccess;state.afterAccess=null;after?.();return allowed;};
  const stoppedKey=store.ingest({provider:'discord',guildId:guild.id,channelId:channel.id,sourceId:'stopped-work',actorId:actor,readers:[actor],revision:1,final:true,text:'合成の停止済み依頼'}).key;
  const task=store.createTask(store.source(stoppedKey,actor),{title:'停止済み',request:'合成',action:'research'});store.cancel(task.id,actor);
  const server=await startBridge({config,store,pipeline:{ingest:(source,flags)=>{state.flags.push(flags);return pipeline.ingest(source,flags);}},readConfig:async()=>config,onImported:onImported??(receipt=>adapter.notifyLumaImport(receipt,{readConfig:async()=>config}))});
  t.after(async()=>{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await pipeline.close();await adapter.client.destroy();store.close();delete process.env.KOTODAMA_TEST_NOTIFICATION_TOKEN;assert(path.basename(root).startsWith('ktdm-luma-notify-'));await rm(root,{recursive:true,force:true});});
  const body={eventRef:'event-fixture',csv:'Name,Email,Ticket ID,Approval Status\nSample,sample@example.invalid,t1,approved\nSample,sample@example.invalid,t2,private_status\n',revision:1};
  const send=async(payload=body)=>{const response=await fetch('http://127.0.0.1:'+server.address().port+'/v1/luma/import',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+process.env.KOTODAMA_TEST_NOTIFICATION_TOKEN},body:JSON.stringify(payload)});return {status:response.status,body:await response.json()};};
  const source=()=>store.sources(actor).find(item=>item.provider==='luma');
  return {root,store,config,actor,other,state,pipeline,adapter,task,body,send,source};
}

test('new import and duplicate produce one owner DM with verified aggregates while voice and work remain stopped',async t=>{
  const f=await fixture(t),first=await f.send(),second=await f.send();
  assert.equal(first.status,200);assert.equal(first.body.state,'analyzed');assert.equal(first.body.notification.state,'sent');assert.equal(second.body.state,'duplicate');assert.equal(second.body.notification.state,'already_sent');assert.equal(f.state.sends.length,1);
  const sent=f.state.sends[0];assert.equal(sent.actor,f.actor);assert(sent.message.content.startsWith('Lumaの取込が完了しました。'));assert(sent.message.content.includes('取込行数: 2'));assert(sent.message.content.includes('識別できた参加者: 1'));assert(sent.message.content.includes('識別できたチケット: 2'));assert.deepEqual(sent.message.allowedMentions,{parse:[]});
  assert(!JSON.stringify([sent,first.body,second.body]).includes('sample@example.invalid'));assert(!sent.message.content.includes('private_status'));assert(!sent.message.content.includes('仕事'));assert.equal(f.store.sources(f.other).filter(s=>s.provider==='luma').length,0);
  assert.deepEqual(f.state.flags,[{execute:false,reply:false}]);assert.equal(f.state.workers,0);assert.equal(f.store.task(f.task.id,f.actor).state,'cancelled');assert.equal(f.store.tasks(f.actor).length,1);assert.equal(f.pipeline.draining,true);assert.equal(f.adapter.voice.control.suspension,'provider_credit');assert.equal(f.adapter.voice.paused,true);
});

test('the first bridge call can notify an existing unnotified CLI import, including an empty CSV',async t=>{
  const f=await fixture(t);f.body.csv='Name,Email,Ticket ID\n';const data=parseLumaCsv(f.body.csv,{eventRef:f.body.eventRef});f.store.ingest(lumaSource(data,{guildId:f.config.discord.guildId,channelId:f.config.discord.resultChannelId,actorId:f.actor,readers:[f.actor],revision:1}));
  const first=await f.send(),second=await f.send();assert.equal(first.body.state,'duplicate');assert.equal(first.body.notification.state,'sent');assert.equal(second.body.notification.state,'already_sent');assert.equal(f.state.flags.length,0);assert.equal(f.state.sends.length,1);assert(f.state.sends[0].message.content.includes('取込行数: 0'));
});

test('unknown delivery remains unknown and retries do not send another DM or fail the import',async t=>{
  const f=await fixture(t);f.state.failSend=true;const first=await f.send();f.state.failSend=false;const second=await f.send();
  assert.equal(first.status,200);assert.equal(first.body.state,'analyzed');assert.equal(first.body.notification.state,'unknown');assert.equal(second.status,200);assert.equal(second.body.notification.state,'unknown');assert.equal(f.state.sends.length,1);assert(f.source());assert.deepEqual(f.state.errors,['LUMA_IMPORT_NOTIFICATION_UNKNOWN']);assert(!JSON.stringify(first.body).includes('diagnostic'));
  const reopened=new Store(f.root);try{assert.equal(reopened.db.prepare('SELECT state FROM deliveries').get().state,'unknown');}finally{reopened.close();}
});

test('concurrent duplicate requests claim at most one delivery',async t=>{
  const f=await fixture(t);const results=await Promise.all([f.send(),f.send(),f.send()]);assert(results.every(r=>r.status===200));assert.equal(results.filter(r=>r.body.notification.state==='sent').length,1);assert.equal(f.state.sends.length,1);
});

for(const reason of ['operator','actor','member','channel_acl','source_acl','withdrawn','revision','source_actor','result_channel'])test(`${reason} revocation or mismatch before delivery prevents notification`,async t=>{
  const f=await fixture(t);
  if(reason==='member')f.state.member=false;else if(reason==='channel_acl')f.state.canRead=false;else f.state.afterAccess=()=>{
    if(reason==='operator')f.config.discord.operators=[f.other];
    else if(reason==='actor')f.config.bridge.actorId=f.other;
    else if(reason==='result_channel')f.config.discord.resultChannelId='100000000000000008';
    else {const source=f.source();f.store.ingest({...source,revision:source.revision+1,...(reason==='source_acl'?{readers:[]}:reason==='withdrawn'?{withdrawn:true}:reason==='source_actor'?{actorId:f.other,readers:[f.other]}:{text:'訂正後の資料'})});}
  };
  const result=await f.send();assert.equal(result.status,200);assert.equal(result.body.state,'analyzed');assert.equal(result.body.notification.state,'blocked');assert.equal(f.state.sends.length,0);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM deliveries').get().n,0);
  if(reason==='withdrawn'){const retry=await f.send();assert.equal(retry.status,400);assert.equal(retry.body.error,'LUMA_SOURCE_WITHDRAWN');assert.equal(f.state.sends.length,0);}
});

test('notification callback failure cannot rewrite import success or expose its private error',async t=>{
  const f=await fixture(t,{onImported:async()=>{throw new Error('synthetic private contact sample@example.invalid');}});const result=await f.send();assert.equal(result.status,200);assert.equal(result.body.state,'analyzed');assert.deepEqual(result.body.notification,{state:'unknown'});assert(f.source());assert(!JSON.stringify(result.body).includes('sample@example.invalid'));
});
