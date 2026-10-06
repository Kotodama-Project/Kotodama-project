import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {ChannelType,PermissionFlagsBits as P,PermissionsBitField} from 'discord.js';
import {Store} from '../src/store.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
import {voiceNotice} from '../src/consent.mjs';
import {deliverRotation,rotationViewers} from '../src/rotation-delivery.mjs';

const guildId='100000000000000001',actor='100000000000000010',other='100000000000000011';
const vc='100000000000000020',targetId='100000000000000021',botId='100000000000000030',botRole='100000000000000040';
const bits=value=>new PermissionsBitField(typeof value==='number'?BigInt(value):value);
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-rotation-post-')),store=new Store(root);
  t.after(()=>{store.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-rotation-post-'));return rm(root,{recursive:true,force:true});});
  const raw=exampleConfig({guildId,operatorId:actor,workspace:root});raw.discord.voiceChannelId=vc;
  raw.voice.transcriptSource='local';raw.voice.localAsr={url:'http://127.0.0.1:18001',model:'synthetic-asr'};
  raw.voice.rotation={enabled:true,channelId:targetId,maxExtendSeconds:60,postWaitSeconds:60};
  const config=Config.parse(raw),sent=[],revoked=new Set();
  const roles=new Map([[guildId,{id:guildId,permissions:bits(0)}],[botRole,{id:botRole,managed:true,tags:{botId},permissions:bits(P.Administrator)}]]);
  const overwrites=new Map([[guildId,{id:guildId,type:0,allow:bits(0),deny:bits(P.ViewChannel)}],[actor,{id:actor,type:1,allow:bits(P.ViewChannel),deny:bits(0)}]]);
  const guild={id:guildId,ownerId:actor,members:{fetch:async({user})=>({id:user})},roles:{fetch:async()=>roles}};
  const channel={id:targetId,guildId,type:ChannelType.GuildText,permissionOverwrites:{cache:overwrites},permissionsFor:()=>bits([P.ViewChannel,P.SendMessages,P.AttachFiles]),send:async value=>{sent.push(value);return {id:'100000000000000099'};}};
  const adapter={verifiedInstallation:true,accessGeneration:0,store,policy:()=>config,canRead:async()=>true,
    client:{user:{id:botId},isReady:()=>true,guilds:{fetch:async()=>guild},
      channels:{fetch:async id=>{assert([vc,targetId].includes(id));return id===vc?{id:vc,guildId}:channel;}}}};
  const voice={allowed:id=>config.voice.participantIds.includes(id)&&!revoked.has(id)};
  const batch={id:'synthetic-rotation',guildId,channelId:vc,targetChannelId:targetId,startedAt:0,endedAt:900000,entries:[]};
  function add(id='one',{input=actor,readers=[actor],unknown=false,text='合成の発話です'}={}){
    const source={provider:'discord',guildId,channelId:vc,sourceId:id,actorId:unknown?null:input,readers,revision:1,final:true,text,
      metadata:{kind:'voice',transcriptOrigin:'local_asr',inputAccountId:input,privacyNoticeId:voiceNotice(config).id,attribution:unknown?'unknown_speaker':'discord_input_track'}};
    const receipt=store.ingest(source);batch.entries.push({key:receipt.key,revision:1,inputAccountId:input,startedAt:5000});return source;
  }
  const source=add();
  const options={voice,readConfig:async()=>config};
  return {config,adapter,store,guild,roles,overwrites,channel,voice,batch,sent,revoked,source,add,options,post:()=>deliverRotation(adapter,batch,options)};
}

test('only an explicit private audience receives a track/timestamp file once',async t=>{
  const f=await fixture(t);assert.equal((await f.post()).state,'sent');assert.equal((await f.post()).state,'sent');assert.equal(f.sent.length,1);
  const message=f.sent[0];assert(message.files[0].attachment.toString('utf8').includes('[00:05] 話者1: 合成の発話です'));
  assert(message.content.includes(`<@${actor}>`));assert.deepEqual(message.allowedMentions,{parse:[]});assert.equal(message.enforceNonce,true);assert(message.nonce.length<=25);
});

for(const kind of ['everyone','role','administrator','thread','bot-permission','owner','member'])test('unproven publication audience is blocked: '+kind,async t=>{
  const f=await fixture(t);
  if(kind==='everyone')f.overwrites.get(guildId).allow=bits(P.ViewChannel);
  if(kind==='role')f.overwrites.set('100000000000000041',{id:'100000000000000041',type:0,allow:bits(P.ViewChannel),deny:bits(0)});
  if(kind==='administrator')f.roles.set('100000000000000041',{id:'100000000000000041',permissions:bits(P.Administrator)});
  if(kind==='thread')f.channel.type=ChannelType.PrivateThread;
  if(kind==='bot-permission')f.channel.permissionsFor=()=>bits(P.ViewChannel);
  if(kind==='owner')f.guild.ownerId=other;
  if(kind==='member')f.overwrites.set(other,{id:other,type:1,allow:bits(P.ViewChannel),deny:bits(P.ViewChannel)});
  assert.equal((await f.post()).state,'blocked');assert.equal(f.sent.length,0);
});

test('member allows are not incorrectly hidden by a simultaneous deny',async t=>{
  const f=await fixture(t);f.overwrites.set(other,{id:other,type:1,allow:bits(P.ViewChannel),deny:bits(P.ViewChannel)});
  assert(rotationViewers(f.channel,f.guild,f.roles,botId).includes(other));
});

test('every visible person must read every included source and the current VC',async t=>{
  const f=await fixture(t);f.config.voice.participantIds.push(other);f.add('two',{input:other,readers:[other],text:'SYNTHETIC_SECOND_PRIVATE_SOURCE'});
  assert.equal((await f.post()).state,'blocked');assert.equal(f.sent.length,0);
});

for(const cause of ['withdrawn','revision','optout'])test('ineligible sources are omitted before publishing: '+cause,async t=>{
  const f=await fixture(t);
  if(cause==='withdrawn')f.store.ingest({...f.source,revision:2,withdrawn:true,text:''});
  if(cause==='revision')f.store.ingest({...f.source,revision:2,text:'corrected after interval'});
  if(cause==='optout')f.revoked.add(actor);
  assert.equal((await f.post()).state,'empty');assert.equal(f.sent.length,0);
});

for(const cause of ['source','consent','target','permission','event','disconnect','stopping'])test('the final publication check catches '+cause+' after asynchronous lookup',async t=>{
  const f=await fixture(t);let active=true;f.options.isActive=()=>active;
  f.adapter.canRead=async()=>{
    if(cause==='source')f.store.ingest({...f.source,revision:2,withdrawn:true,text:''});
    if(cause==='consent')f.revoked.add(actor);
    if(cause==='target')f.config.voice.rotation.channelId='100000000000000023';
    if(cause==='permission')f.overwrites.set(other,{id:other,type:1,allow:bits(P.ViewChannel),deny:bits(0)});
    if(cause==='event')f.adapter.accessGeneration++;
    if(cause==='disconnect')f.adapter.client.isReady=()=>false;
    if(cause==='stopping')active=false;
    return true;
  };
  assert.equal((await f.post()).state,'blocked');assert.equal(f.sent.length,0);
});

test('unknown delivery never causes an automatic replay',async t=>{
  const f=await fixture(t);f.channel.send=async value=>{f.sent.push(value);throw Error('synthetic transport ambiguity');};
  assert.equal((await f.post()).state,'unknown');assert.equal((await f.post()).state,'unknown');assert.equal(f.sent.length,1);
});

test('unknown attribution is not mapped back to the input account in the public message',async t=>{
  const f=await fixture(t);f.batch.entries=[];f.add('unknown',{unknown:true});
  assert.equal((await f.post()).state,'sent');assert(!f.sent[0].content.includes(`<@${actor}>`));
  assert(f.sent[0].files[0].attachment.toString('utf8').includes('話者不明'));
});

test('disabled notice is byte-identical and enabled target changes require a new notice',async t=>{
  const f=await fixture(t),base=exampleConfig();const before=voiceNotice(base);delete base.voice.rotation;
  assert.deepEqual(voiceNotice(base),before);
  const enabled=voiceNotice(f.config);f.config.voice.rotation.channelId='100000000000000023';assert.notEqual(voiceNotice(f.config).id,enabled.id);
  assert(enabled.text.includes('15分ごと'));
});

test('enabled rotation refuses incompatible and incomplete configuration',async()=>{
  const base=exampleConfig();
  for(const extra of [{channelId:targetId},{channelId:undefined},{channelId:vc}]){
    const value=structuredClone(base);value.discord.voiceChannelId=vc;value.voice.rotation={enabled:true,...extra};
    assert.equal(Config.safeParse(value).success,false);
  }
});
