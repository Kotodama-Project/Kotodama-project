import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {VoiceConnectionStatus as State} from '@discordjs/voice';
import {VoicePool,createVoicePool} from '../src/voice-pool.mjs';
import {VoiceRoom} from '../src/voice.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {createAnalysisAuthorizer} from '../src/analysis-policy.mjs';
import {Store} from '../src/store.mjs';
import {Config,exampleConfig,loadConfig} from '../src/config.mjs';
import {voiceNotice} from '../src/consent.mjs';
import {startRuntime} from '../src/runtime.mjs';
import {errorCode} from '../src/common.mjs';

const a='100000000000000002',b='100000000000000004';
const channels=['100000000000000005','100000000000000006','100000000000000007'];
const applications=['100000000000000011','100000000000000012'];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
class Connection extends EventEmitter{
  constructor(options){super();this.options=options;this.state={status:State.Ready};this.receiver={speaking:new EventEmitter()};}
  subscribe(){}
  destroy(){this.state={status:State.Destroyed};this.emit(State.Destroyed);}
}
async function fixture(t,{bots=2}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-pool-')),store=new Store(root);
  store.claimHost('pool-owner',process.pid,new Date().toISOString());
  const config=Config.parse({...exampleConfig({applicationId:applications[0]}),voice:{participantIds:[a,b],maxDailyAudioSeconds:1000},
    voicePool:{rooms:channels.map((channelId,index)=>({channelId,participantIds:index===1?[b]:[a]})),bots:bots===2?[{applicationId:applications[1],botTokenEnv:'SYNTHETIC_SECOND_BOT'}]:[]}});
  const clients=applications.slice(0,bots).map(applicationId=>{
    const client=new EventEmitter();client.application={id:applicationId};client.ready=true;client.externalChannel=null;client.isReady=()=>client.ready;client.destroy=async()=>{client.ready=false;client.destroyed=true;};
    const guild={id:config.discord.guildId,voiceAdapterCreator:{applicationId},members:{fetchMe:async()=>({voice:{channelId:client.externalChannel}})}};
    client.guilds={fetch:async()=>guild};client.channels={cache:new Map(channels.map((id,index)=>[id,{id,guildId:guild.id,guild,isVoiceBased:()=>true,members:new Map([[index===1?b:a,{id:index===1?b:a,user:{bot:false}}]])}])),fetch:async id=>client.channels.cache.get(id)};
    return {applicationId,client};
  });
  const connections=[],errors=[];
  const pool=new VoicePool({config,policy:()=>config,store,ownerId:'pool-owner',pipeline:{},clients,readers:async room=>room.audience(),onError:code=>errors.push(code),
    roomFactory:options=>new VoiceRoom({...options,waitForState:async connection=>connection,connectionFactory:options=>{const c=new Connection(options);connections.push(c);return c;}})});
  t.after(async()=>{await pool.dispose();store.close();assert(path.basename(root).startsWith('ktdm-pool-'));await rm(root,{recursive:true,force:true});});
  return {root,store,config,pool,clients,connections,errors};
}

test('two rooms have independent states and Bot slots; a full pool is busy without moving either connection',async t=>{
  const f=await fixture(t),[first,second,third]=channels.map(id=>f.pool.forChannel(id));
  await Promise.all([first.join(),second.join()]);
  assert.notEqual(f.connections[0].options.group,f.connections[1].options.group);
  assert.notEqual(f.connections[0].options.adapterCreator.applicationId,f.connections[1].options.adapterCreator.applicationId);
  await assert.rejects(third.join(),error=>errorCode(error)==='VOICE_POOL_BUSY');assert.equal(f.connections.length,2);
  await first.setMode('minutes');assert.equal(second.mode,'assist');
  await first.pause();assert.equal(second.paused,false);assert.equal(second.connectionReady(),true);
  assert.equal(first.allowed(b),false);assert.equal(second.allowed(a),false);
  assert.notEqual(first.sessions,second.sessions);assert.notEqual(first.localCaptures,second.localCaptures);
  await first.close();await third.join();assert.equal(f.connections.length,3);
  assert.equal(f.connections[0].state.status,State.Destroyed);assert.equal(second.connectionReady(),true);
  assert.equal(f.pool.forSource({provider:'discord',guildId:f.config.discord.guildId,channelId:channels[1]}),second);
  assert.equal(f.pool.forSource({provider:'discord',guildId:'other',channelId:channels[1]}),null);
});

test('duplicate joins and concurrent slot claims cannot reserve one Bot twice',async t=>{
  const f=await fixture(t,{bots:1}),[first,second]=channels.map(id=>f.pool.forChannel(id));
  const joining=first.join();await assert.rejects(first.join(),{code:'VOICE_ALREADY_CONNECTED'});await joining;
  await assert.rejects(second.join(),{code:'VOICE_POOL_BUSY'});
  await assert.rejects(f.pool.acquire(first.target),{code:'VOICE_ALREADY_CONNECTED'});
  assert.equal(f.connections.length,1);
});

test('failed connections and destroyed Bots release their owned room without closing a neighbor',async t=>{
  const f=await fixture(t),[first,second,third]=channels.map(id=>f.pool.forChannel(id));
  first.connectionFactory=()=>{throw new Error('synthetic failure');};
  await assert.rejects(first.join(),/synthetic failure/);assert.equal(f.pool.slots[0].lease,null);
  await second.join();await third.join();const secondConnection=second.connection;
  f.clients[0].client.ready=false;f.clients[0].client.emit('shardDisconnect');await flush();
  assert.equal(secondConnection.state.status,State.Destroyed);assert.equal(second.connection,null);
  assert.equal(f.pool.slots[0].lease,null);assert.equal(third.connectionReady(),true);
  third.connection.destroy();await flush();assert.equal(f.pool.slots[1].lease,null);
});

test('an occupied external Bot is not moved; host ownership loss prevents new joins',async t=>{
  const f=await fixture(t,{bots:1}),first=f.pool.forChannel(channels[0]);
  f.clients[0].client.externalChannel='100000000000000099';
  await assert.rejects(first.join(),{code:'VOICE_POOL_BUSY'});assert.equal(f.connections.length,0);
  f.clients[0].client.externalChannel=null;f.store.releaseHost('pool-owner');
  await assert.rejects(first.join(),{code:'VOICE_JOIN_SUPERSEDED'});
  await assert.rejects(f.pool.acquire(first.target),{code:'VOICE_POOL_OWNER_CHANGED'});
});

test('closing while slot discovery awaits prevents late connection and returns the reservation',async t=>{
  const f=await fixture(t,{bots:1}),first=f.pool.forChannel(channels[0]);let release;
  const guild=await f.clients[0].client.guilds.fetch();guild.members.fetchMe=()=>new Promise(resolve=>{release=resolve;});
  const joining=first.join(),rejected=assert.rejects(joining,{code:'VOICE_JOIN_SUPERSEDED'});await flush();
  assert(f.pool.slots[0].lease);await first.close();release({voice:{channelId:null}});await rejected;
  assert.equal(f.connections.length,0);assert.equal(f.pool.slots[0].lease,null);
});

test('room policy revocation closes only that room and ambiguous commands are refused',async t=>{
  const f=await fixture(t),[first,second]=channels.map(id=>f.pool.forChannel(id));await Promise.all([first.join(),second.join()]);
  f.config.voicePool.rooms[0].participantIds=[];await f.pool.control.check();
  assert.equal(first.connection,null);assert.equal(second.connectionReady(),true);
  await assert.rejects(f.pool.control.command('leave',{actor:a}),{code:'VOICE_ROOM_REQUIRED'});
  await f.pool.control.command('pause',{actor:b,channelId:channels[1]});assert.equal(second.paused,true);
  assert.equal(f.pool.control.status().rooms.length,3);
});

test('consent buttons bind the selected room, use bounded IDs, and revoke only its source scope',async t=>{
  const f=await fixture(t),[first,second]=channels.map(id=>f.pool.forChannel(id));await Promise.all([first.join(),second.join()]);
  const adapter=new DiscordAdapter({config:f.config,policy:()=>f.config,store:f.store,pipeline:{}});adapter.voice=f.pool;adapter.canRead=async()=>true;
  adapter.client.channels.fetch=async id=>f.clients[0].client.channels.cache.get(id);
  t.after(()=>adapter.client.destroy());let output;
  const interaction={guildId:f.config.discord.guildId,id:'100000000000000101',user:{id:a},options:{getChannel:()=>({id:channels[0]})},isButton:()=>false,deferReply:async()=>{},editReply:async value=>{output=value;}};
  await adapter.consentInteraction(interaction);const button=output.components[0].components[0];assert(button.custom_id.length<=100);assert(button.custom_id.endsWith(channels[0]));
  await adapter.consentInteraction({...interaction,isButton:()=>true,customId:button.custom_id});
  assert.equal(f.store.voiceOptedOut(f.config.discord.guildId,channels[0],a),true);
  assert.equal(f.store.voiceOptedOut(f.config.discord.guildId,channels[1],b),false);
  assert.equal(second.connectionReady(),true);assert.equal(voiceNotice(first.policy()).id.length,64);
  assert.equal(adapter.roomFor({provider:'discord',guildId:f.config.discord.guildId,channelId:channels[1]}),second);
});

test('analysis access resolves the source room rather than borrowing another room participant grant',async t=>{
  const f=await fixture(t),authorize=createAnalysisAuthorizer({config:f.config,readConfig:async()=>f.config,voice:source=>f.pool.forSource(source),owner:f.store,offline:true});
  const source={provider:'discord',guildId:f.config.discord.guildId,channelId:channels[1],actorId:b,readers:[b],metadata:{kind:'voice'}};
  await authorize(source,b);
  await assert.rejects(authorize({...source,channelId:channels[0]},b),{code:'GRANT_REVOKED'});
  await assert.rejects(authorize({...source,channelId:'100000000000000099',actorId:a,readers:[a]},a),{code:'SOURCE_ACCESS_DENIED'});
});

test('a second runtime cannot claim an installation already managing the pool',async t=>{
  const f=await fixture(t),file=path.join(f.root,'runtime.json');
  await writeFile(file,JSON.stringify({...f.config,dataDir:f.root}));
  await assert.rejects(startRuntime(file,{offline:true,log:()=>{}}),{code:'RUNTIME_RECOVERY_DOMAIN_MISMATCH'});
  assert.equal(f.store.lock().owner,'pool-owner');
});

test('replies and model actions return to the original room, and unknown rooms have no delivery',async t=>{
  const f=await fixture(t),adapter=new DiscordAdapter({config:f.config,store:f.store,pipeline:{}});adapter.voice=f.pool;t.after(()=>adapter.client.destroy());
  const delivered=[],actions=[];
  for(const [channelId,room] of f.pool.rooms){room.speak=async(text,options)=>delivered.push({channelId,text,epoch:options.epoch});room.applyModelAction=async action=>actions.push({channelId,action});}
  const source={provider:'discord',guildId:f.config.discord.guildId,channelId:channels[1],actorId:b,metadata:{kind:'voice',voiceEpoch:7}};
  await adapter.reply({source,text:'synthetic'});await adapter.voiceAction({source,action:'stop_speech'});
  await adapter.reply({source:{...source,channelId:'100000000000000099'},text:'not delivered'});
  assert.deepEqual(delivered,[{channelId:channels[1],text:'synthetic',epoch:7}]);assert.deepEqual(actions,[{channelId:channels[1],action:'stop_speech'}]);
});

test('configuration preserves single VC defaults and rejects ambiguous pool bindings and shared archives',async t=>{
  const f=await fixture(t),file=path.join(f.root,'config.json');
  assert.equal(exampleConfig().voicePool,undefined);
  await writeFile(file,JSON.stringify(f.config));await loadConfig(file);
  for(const mutate of [c=>c.voicePool.rooms.push(c.voicePool.rooms[0]),c=>c.voicePool.bots[0].applicationId=c.discord.applicationId,c=>c.voicePool.bots[0].botTokenEnv=c.discord.botTokenEnv,c=>c.voice.rotation={enabled:true,channelId:c.discord.resultChannelId}]){
    const config=structuredClone(f.config);mutate(config);await writeFile(file,JSON.stringify(config));await assert.rejects(loadConfig(file));
  }
});

test('additional clients verify application identity and are destroyed after a failed login',async t=>{
  const f=await fixture(t);const extras=[];process.env.SYNTHETIC_SECOND_BOT='fixture';t.after(()=>delete process.env.SYNTHETIC_SECOND_BOT);
  await assert.rejects(createVoicePool({config:f.config,client:f.clients[0].client,store:f.store,ownerId:'pool-owner',pipeline:{},readers:async()=>[]},{clientFactory:()=>{
    const client=new EventEmitter();client.application={id:applications[0]};client.login=async()=>{queueMicrotask(()=>client.emit('clientReady'));};client.destroy=async()=>{client.destroyed=true;};extras.push(client);return client;
  }}),{code:'BOT_APPLICATION_MISMATCH'});
  assert.equal(extras.length,1);assert.equal(extras[0].destroyed,true);
});
