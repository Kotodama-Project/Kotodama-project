import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import OpusScript from 'opusscript';
import {VoiceConnectionStatus as State} from '@discordjs/voice';
import {Store} from '../src/store.mjs';
import {exampleConfig} from '../src/config.mjs';
import {VoiceRoom,accessEventRelevant} from '../src/voice.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {voiceNotice} from '../src/consent.mjs';
const a='100000000000000002',b='100000000000000004';
async function fixture(t,providerFactory,{configure=()=>{},localAsrFactory}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-voice-'));const store=new Store(root);const config=exampleConfig();config.discord.voiceChannelId='100000000000000005';config.voice.maxDailyAudioSeconds=100;config.voice.consentMode='participant_opt_in';config.voice.apiKeyEnv='KOTODAMA_TEST_VOICE_KEY';process.env.KOTODAMA_TEST_VOICE_KEY='fixture';
  configure(config);
  const channel={id:config.discord.voiceChannelId,guildId:config.discord.guildId,members:new Map([[a,{id:a,user:{bot:false}}],[b,{id:b,user:{bot:false}}]])};const client=new EventEmitter();client.channels={cache:new Map([[channel.id,channel]])};const sources=[];
  const room=new VoiceRoom({client,config,store,providerFactory,localAsrFactory,sourceReaders:async()=>[a,b],pipeline:{ingest:async(s,flags)=>sources.push({s,flags})}});
  room.connection={state:{status:State.Ready},destroy(){this.state={status:State.Destroyed};}};
  for(const actor of [a,b])store.recordConsent({guild:config.discord.guildId,channel:channel.id,actor,notice:voiceNotice(config).id,granted:true,interactionId:actor});
  t.after(async()=>{await room.dispose();store.close();delete process.env.KOTODAMA_TEST_VOICE_KEY;assert(path.basename(root).startsWith('ktdm-voice-'));await rm(root,{recursive:true,force:true});});
  return {store,config,room,channel,client,sources};
}
const provider=options=>({options,active:false,sessionId:'fixture-live',outputGeneration:0,start:async function(){this.active=true;},append(){},commit(){},respond:async function(){return {outputGeneration:++this.outputGeneration};},interrupt(){this.interrupted=true;},abort(){this.active=false;},close:async function(){this.active=false;}});
test('consent is bound to the current notice and does not add execution operators',async t=>{const {store,config,room}=await fixture(t,provider);assert(room.allowed(b));assert(!config.discord.operators.includes(b));config.discord.operators.push('100000000000000006');assert(!room.allowed(b));store.recordConsent({guild:config.discord.guildId,channel:config.discord.voiceChannelId,actor:b,notice:voiceNotice(config).id,granted:false,interactionId:'900000000000000003'});assert(!room.allowed(b));});
test('a failed old start cannot remove the replacement session after a mode switch',async t=>{
  let rejectOld,count=0;const {room}=await fixture(t,options=>{const p=provider(options);if(++count===1)p.start=()=>new Promise((_,reject)=>{rejectOld=reject;});return p;});
  const old=room.session(a);const oldRejected=assert.rejects(old,/old failed/);await room.setMode('minutes');const replacement=await room.session(a);rejectOld(new Error('old failed'));await oldRejected;assert.equal(room.sessions.get(a),replacement);await room.pause();assert.equal(replacement.provider.active,false);assert.equal(room.sessions.size,0);
});
test('pause finalizes input and drains final transcript before closing its assembler',async t=>{
  const {room,sources}=await fixture(t,options=>{const p=provider(options);p.close=async()=>{options.onFragment({id:'last',text:'最後の発言',startMs:0,endMs:100});p.active=false;};return p;});
  const stream=new PassThrough();room.connection={state:{status:State.Ready},receiver:{subscribe:()=>stream},destroy(){this.state={status:State.Destroyed};}};
  await room.capture(a);const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO);const packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));for(let i=0;i<6;i++)stream.write(packet);encoder.delete();await room.pause();
  assert.equal(sources.length,1);assert.equal(sources[0].s.text,'最後の発言');assert.equal(sources[0].flags.execute,false);assert.equal(sources[0].flags.reply,false);
});
test('voice answers keep source ACL through audience changes and late old-mode replies',async t=>{
  let starts=0;const {store,config,room,channel}=await fixture(t,options=>{starts++;return provider(options);});
  const source={provider:'discord',guildId:config.discord.guildId,channelId:channel.id,sourceId:'private',actorId:a,revision:1,final:true,readers:[a],text:'Aだけの資料',metadata:{kind:'voice',voiceEpoch:0}};source.key=store.ingest(source).key;
  const adapter=new DiscordAdapter({config,store,pipeline:{}});adapter.voice=room;adapter.canRead=async()=>true;adapter.client.channels.fetch=async()=>channel;t.after(()=>adapter.client.destroy());
  const reply={source,text:'Aだけの資料の回答',contextSources:[{key:source.key,revision:1}]};await assert.rejects(adapter.reply(reply),/SOURCE_ACCESS_DENIED/);assert.equal(starts,0);
  channel.members.delete(b);await room.session(a);await adapter.reply(reply);assert.equal(starts,1);assert(room.canPlay(room.reply));channel.members.set(b,{id:b,user:{bot:false}});assert.equal(room.canPlay(room.reply),false);await room.setMode('minutes');await room.setMode('assist');await adapter.reply(reply);assert.equal(starts,1);
});

test('late agree cannot override a newer revoke and replay is idempotent',async t=>{const {store,config,room}=await fixture(t,provider);const base={guild:config.discord.guildId,channel:config.discord.voiceChannelId,actor:a,notice:voiceNotice(config).id};store.recordConsent({...base,granted:false,interactionId:'900000000000000010'});const stale=store.recordConsent({...base,granted:true,interactionId:'900000000000000009'});assert.equal(stale.state,'stale');assert.equal(room.allowed(a),false);assert.equal(store.recordConsent({...base,granted:false,interactionId:'900000000000000010'}).state,'duplicate');assert.equal(room.allowed(a),false);});

test('an external permission revocation stops a current reply on access refresh',async t=>{const {store,room,channel,config}=await fixture(t,provider);channel.members.delete(b);await room.session(a);const source={provider:'discord',guildId:config.discord.guildId,channelId:channel.id,sourceId:'current',actorId:a,revision:1,final:true,readers:[a],text:'資料',metadata:{}};const key=store.ingest(source).key;let allowed=true;await room.speak('回答',{epoch:room.epoch,actorId:a,bindings:[{key,revision:1}],authorizeAudience:async()=>{assert(allowed,'permission removed');return [a];}});assert(room.reply);allowed=false;await room.reply.refreshAccess();assert.equal(room.reply,null);});

test('an exhausted one-time allowance pauses reception before opening another provider',async t=>{let starts=0;const {store,config,room,channel}=await fixture(t,options=>{starts++;return provider(options);});channel.members.delete(b);config.voice.maxTotalAudioSeconds=1;store.recordConsent({guild:config.discord.guildId,channel:config.discord.voiceChannelId,actor:a,notice:voiceNotice(config).id,granted:true,interactionId:'900000000000000020'});store.reserveAudio(1000,100,undefined,1);await assert.rejects(room.session(a),/AUDIO_TOTAL_BUDGET_EXHAUSTED/);assert.equal(starts,0);assert.equal(room.paused,true);});

test('owner-managed privacy scope needs no participant click but preserves explicit opt-out',async t=>{const {store,config,room}=await fixture(t,provider);const guest='100000000000000007';config.voice.consentMode='owner_managed';config.voice.participantIds=[guest];assert.equal(room.allowed(guest),true);assert.equal(config.discord.operators.includes(guest),false);assert.equal(store.consent(config.discord.guildId,config.discord.voiceChannelId,guest,voiceNotice(config).id),false);store.recordConsent({guild:config.discord.guildId,channel:config.discord.voiceChannelId,actor:guest,notice:voiceNotice(config).id,granted:false,interactionId:'900000000000000021'});assert.equal(room.allowed(guest),false);assert.equal(room.allowed(a),false);});

test('a live privacy-policy change invalidates the old input session without inventing new opt-in',async t=>{const {room,config,channel}=await fixture(t,provider);channel.members.delete(b);const old=await room.session(a);assert(room.current(old));config.voice.consentMode='owner_managed';config.voice.participantIds=[a];assert(room.allowed(a));assert.equal(room.current(old),false);await room.pause();await room.resume();const next=await room.session(a);assert.equal(next.privacyBasis,'owner_managed');assert(room.current(next));assert.equal(old.provider.active,false);});

test('local Japanese transcripts stay authoritative and open one Live session only after a typo-tolerant wake phrase',async t=>{
  const transcripts=['今日は雑談です','ことたま、サーバーの状態を教えて','それで負荷はどう？'],providers=[];
  const {room,channel,sources}=await fixture(t,options=>{const p=provider(options);p.appended=0;p.append=()=>p.appended++;providers.push(p);return p;},{configure:config=>{config.voice.transcriptSource='local';config.voice.localAsr={url:'http://127.0.0.1:9000/v1/audio/transcriptions',model:'tiny',language:'ja',timeoutSeconds:20,maxUtteranceSeconds:30};},localAsrFactory:()=>({transcribe:async()=>transcripts.shift()})});
  channel.members.delete(b);const streams=[];room.connection.receiver={subscribe:()=>streams.shift()};const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO),packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));encoder.delete();
  const utter=async()=>{const stream=new PassThrough();streams.push(stream);await room.capture(a);for(let i=0;i<6;i++)stream.write(packet);stream.end();await new Promise(resolve=>setImmediate(resolve));await Promise.allSettled([...room.draining]);};
  await utter();assert.equal(providers.length,0);assert.equal(sources[0].s.text,'今日は雑談です');assert.deepEqual(sources[0].flags,{execute:false,reply:false,analyze:false});assert.equal(sources[0].s.metadata.transcriptOrigin,'local_asr');
  await utter();assert.equal(providers.length,1);assert.equal(providers[0].options.initialHistory[0].text,'ことたま、サーバーの状態を教えて');assert.deepEqual(sources[1].flags,{execute:true,reply:true,analyze:true});
  await utter();assert.equal(providers.length,1);assert.deepEqual(sources[2].flags,{execute:true,reply:true,analyze:true});assert(providers[0].appended>0);
});

test('ending a conversation closes its Live session but leaves the Discord room connected',async t=>{const {room,channel}=await fixture(t,provider);channel.members.delete(b);const session=await room.session(a);session.conversationActive=true;await room.applyModelAction('end_conversation',{actorId:a,metadata:{kind:'voice',voiceEpoch:room.epoch,sessionId:session.id}});assert.equal(room.sessions.has(a),false);assert.equal(session.provider.active,false);assert(room.connectionReady());});

test('a delayed local wake after departure is recorded without starting Live',async t=>{
  let starts=0;const {room,channel,sources}=await fixture(t,o=>{starts++;return provider(o);});
  const state=room.localState(a);channel.members.clear();
  await room.queueLocalTurn(state,{id:'departed',text:'ことだま、こんにちは',startMs:0,endMs:1000});
  assert.equal(starts,0);assert.equal(sources.length,1);assert.equal(sources[0].flags.execute,false);assert.equal(sources[0].flags.reply,false);
});

test('a failed Live start does not discard the final local transcript',async t=>{
  const {room,channel,sources}=await fixture(t,o=>({...provider(o),start:async()=>{throw new Error('fixture startup failed');}}));
  channel.members.delete(b);await room.queueLocalTurn(room.localState(a),{id:'start-failed',text:'ことだま、こんにちは',startMs:0,endMs:1000});
  assert.equal(sources.length,1);assert.equal(sources[0].s.text,'ことだま、こんにちは');assert.equal(sources[0].flags.execute,false);
});
test('an idle Live conversation closes while the Discord room keeps local listening',async t=>{const {room,channel,config}=await fixture(t,provider);channel.members.delete(b);config.voice.conversationIdleSeconds=30;const session=await room.session(a);session.conversationActive=true;session.lastInput=Date.now()-31000;await new Promise(resolve=>setTimeout(resolve,1100));assert.equal(room.sessions.has(a),false);assert.equal(session.provider.active,false);assert(room.connectionReady());});

test('empty local ASR packets cannot renew the billable conversation timeout',async t=>{
  const {room,channel,config}=await fixture(t,provider);channel.members.delete(b);room.localAsr={};config.voice.conversationIdleSeconds=30;
  const session=await room.session(a);session.lastHumanInput=Date.now()-31000;session.lastInput=Date.now();
  await room.queueLocalTurn(room.localState(a),{id:'silence',text:'',startMs:0,endMs:1000});
  await new Promise(resolve=>setTimeout(resolve,1100));assert.equal(room.sessions.size,0);assert(room.connectionReady());
});

test('leaving seals the last local utterance and disconnects before ASR completes',async t=>{
  let resolveAsr;const {room,sources}=await fixture(t,provider,{configure:c=>{c.voice.localAsr={maxUtteranceSeconds:30};}});
  room.localAsr={transcribe:()=>new Promise(resolve=>{resolveAsr=resolve;})};
  const stream=new PassThrough();let destroyed=false;
  room.connection={state:{status:State.Ready},receiver:{subscribe:()=>stream},destroy(){destroyed=true;this.state={status:State.Destroyed};}};
  await room.captureLocal(a);const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO);const packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));for(let i=0;i<6;i++)stream.write(packet);encoder.delete();
  const closing=room.close();await new Promise(resolve=>setImmediate(resolve));assert(destroyed);assert.equal(typeof resolveAsr,'function');resolveAsr('最後の発言');await closing;
  assert.equal(sources.length,1);assert.equal(sources[0].s.text,'最後の発言');assert.equal(sources[0].flags.reply,false);assert.equal(sources[0].flags.execute,false);
});

test('speech admission starts one scoped Live session and preserves buffered startup audio',async t=>{
  let starts=0,bytes=0;const {room}=await fixture(t,o=>({...provider(o),start:async function(){starts++;this.active=true;},append:pcm=>{bytes+=pcm.length;}}),{configure:c=>{c.voice.conversationStart='speech';c.voice.localAsr={maxUtteranceSeconds:30};}});
  room.localAsr={transcribe:async()=>''};const stream=new PassThrough();room.connection={state:{status:State.Ready},receiver:{subscribe:()=>stream},destroy(){this.state={status:State.Destroyed};}};
  await room.captureLocal(a);const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO);const frame=Buffer.alloc(3840);for(let i=0;i<frame.length;i+=2)frame.writeInt16LE(Math.round(4000*Math.sin(i/2*0.05)),i);
  for(let i=0;i<35;i++)stream.write(Buffer.from(encoder.encode(frame,960)));encoder.delete();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(starts,1);assert.equal(bytes,35*960);assert(room.sessions.get(a).conversationActive);await room.close();
});

test('natural Live playback precedes ASR and remains bound to the original audience',async t=>{
  const {room,channel}=await fixture(t,provider,{configure:c=>{c.voice.naturalConversation=true;}});const session=await room.session(a);
  for(let i=0;i<7;i++)session.provider.options.onAudio(Buffer.alloc(960),session.provider.sessionId,0);
  assert(room.reply?.started);assert.equal(room.reply.naturalSession,session);assert(room.canPlay(room.reply));
  channel.members.set('100000000000000099',{id:'100000000000000099',user:{bot:false}});assert.equal(room.canPlay(room.reply),false);await room.close();
});

test('a natural-conversation speaker stops local playback and queued PCM immediately',async t=>{
  const {room,channel}=await fixture(t,provider,{configure:c=>{c.voice.naturalConversation=true;}});channel.members.delete(b);const session=await room.session(a);
  for(let i=0;i<7;i++)session.provider.options.onAudio(Buffer.alloc(960),session.provider.sessionId,0);assert(room.reply?.started);
  const input=new PassThrough();room.connection.receiver={subscribe:()=>input};await room.capture(a);
  assert.equal(room.reply,null);assert.equal(session.provider.interrupted,true);input.destroy();await room.close();
});

test('the receiver archives original 48k mono and links the fast transcript before leaving',async t=>{
  const {room,sources}=await fixture(t,provider,{configure:c=>{c.voice.localAsr={maxUtteranceSeconds:30};}});room.localAsr={transcribe:async()=> '最後の記録'};
  let packets=0,seals=0;room.archive={append:(actor,pcm,time)=>{assert.equal(actor,a);assert.equal(pcm.length,1920);assert(Number.isSafeInteger(time));packets++;return {sessionId:'session-fixture'};},seal:()=>{seals++;}};
  const stream=new PassThrough();room.connection={state:{status:State.Ready},receiver:{subscribe:()=>stream},destroy(){this.state={status:State.Destroyed};}};
  await room.captureLocal(a);const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO);const packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));for(let i=0;i<6;i++)stream.write(packet);encoder.delete();await room.close();
  assert.equal(packets,6);assert.equal(seals,1);assert.deepEqual(sources[0].s.metadata.archiveSessionRefs,['session-fixture']);
});

test('private project lookup narrows a formerly shared Live session audience',async t=>{
  const {room,channel}=await fixture(t,provider,{configure:c=>{c.voice.naturalConversation=true;}});const session=await room.session(a);
  assert.equal((await session.provider.options.onContext('資料')).status,'individual_conversation_required');
  channel.members.delete(b);await session.provider.options.onContext('資料');assert.deepEqual(session.readers,[a]);
  session.provider.options.onAudio(Buffer.alloc(960),session.provider.sessionId,0);channel.members.set(b,{id:b,user:{bot:false}});assert.equal(room.canPlay(room.reply),false);await room.close();
});

test('voice processing scope alone cannot grant a participant access to project files',async t=>{
  const {room,channel,config}=await fixture(t,provider,{configure:c=>{c.voice.naturalConversation=true;}});assert(!config.discord.operators.includes(b));channel.members.delete(a);
  const session=await room.session(b);await assert.rejects(session.provider.options.onContext('プロジェクト資料'),{code:'SOURCE_ACCESS_DENIED'});await room.close();
});

test('a delayed end decision cannot close a replacement Live session in the same VC epoch',async t=>{
  const {room}=await fixture(t,provider);const old=await room.session(a);await room.endSession(old);const current=await room.session(a);
  await room.applyModelAction('end_conversation',{actorId:a,metadata:{kind:'voice',voiceEpoch:room.epoch,sessionId:old.id}});assert.equal(room.sessions.get(a),current);assert(current.provider.active);
});
test('access events are scoped to the target guild and to audience membership changes',()=>{
  const target={guildId:'100000000000000010',voiceChannelId:'100000000000000011'},other='100000000000000012',state=(guild,channelId)=>({guild:{id:guild},channelId});
  assert.equal(accessEventRelevant('voiceStateUpdate',[state(other,target.voiceChannelId),state(other,null)],target),false);
  assert.equal(accessEventRelevant('voiceStateUpdate',[state(target.guildId,'100000000000000013'),state(target.guildId,null)],target),false);
  assert.equal(accessEventRelevant('voiceStateUpdate',[state(target.guildId,target.voiceChannelId),state(target.guildId,target.voiceChannelId)],target),false);
  assert.equal(accessEventRelevant('voiceStateUpdate',[state(target.guildId,null),state(target.guildId,target.voiceChannelId)],target),true);
  assert.equal(accessEventRelevant('voiceStateUpdate',[null,state(target.guildId,target.voiceChannelId)],target),true);
  assert.equal(accessEventRelevant('voiceStateUpdate',[state(target.guildId,target.voiceChannelId),state(target.guildId,'100000000000000013')],target),true);
  assert.equal(accessEventRelevant('voiceStateUpdate',[{},{}],target),true);
  for(const event of ['channelUpdate','guildMemberUpdate','roleUpdate']){
    assert.equal(accessEventRelevant(event,[{guildId:other},{guildId:other}],target),false);
    assert.equal(accessEventRelevant(event,[{guild:{id:target.guildId}},{guild:{id:target.guildId}}],target),true);
  }
  for(const event of ['guildMemberRemove','roleDelete']){assert.equal(accessEventRelevant(event,[{guild:{id:other}}],target),false);assert.equal(accessEventRelevant(event,[{guild:{id:target.guildId}}],target),true);}
  assert.equal(accessEventRelevant('threadMembersUpdate',[new Map(),new Map(),{guildId:other}],target),false);
  assert.equal(accessEventRelevant('threadMembersUpdate',[new Map(),new Map(),{guildId:target.guildId}],target),true);
  assert.equal(accessEventRelevant('channelUpdate',[{},{}],target),true);
});
test('unrelated voice and permission events do not stop the current reply; target changes still do',async t=>{
  const {store,room,channel,config,client}=await fixture(t,provider);channel.members.delete(b);await room.session(a);
  const key=store.ingest({provider:'discord',guildId:config.discord.guildId,channelId:channel.id,sourceId:'scoped-events',actorId:a,revision:1,final:true,readers:[a],text:'資料',metadata:{}}).key;
  const speak=async()=>{await room.speak('回答',{epoch:room.epoch,actorId:a,bindings:[{key,revision:1}],authorizeAudience:async()=>[a]});assert(room.reply);return room.reply;};
  const otherGuild='100000000000000020',otherVoice='100000000000000021',state=(guild,channelId)=>({guild:{id:guild},channelId});
  const reply=await speak();
  client.emit('voiceStateUpdate',state(otherGuild,null),state(otherGuild,otherVoice));
  client.emit('voiceStateUpdate',state(config.discord.guildId,otherVoice),state(config.discord.guildId,null));
  client.emit('voiceStateUpdate',state(config.discord.guildId,channel.id),state(config.discord.guildId,channel.id));
  client.emit('roleUpdate',{guild:{id:otherGuild}},{guild:{id:otherGuild}});client.emit('guildMemberRemove',{guild:{id:otherGuild}});
  assert.equal(room.reply,reply);assert.equal(reply.provider.interrupted,undefined);
  client.emit('voiceStateUpdate',state(config.discord.guildId,null),state(config.discord.guildId,channel.id));assert.equal(room.reply,null);
  await speak();client.emit('roleUpdate',{guild:{id:config.discord.guildId}},{guild:{id:config.discord.guildId}});assert.equal(room.reply,null);
  await speak();client.emit('channelUpdate',{},{});assert.equal(room.reply,null);
});
test('disposing the room removes every access listener it registered',async t=>{
  const {room,client}=await fixture(t,provider);const events=['voiceStateUpdate','channelUpdate','guildMemberUpdate','guildMemberRemove','roleUpdate','roleDelete','threadMembersUpdate'];
  const before=Object.fromEntries(events.map(e=>[e,client.listenerCount(e)]));assert(events.every(e=>before[e]>=1));await room.dispose();
  for(const e of events)assert.equal(client.listenerCount(e),before[e]-1);
});

// Issue #147: continued answers after the first reply. Synthetic PCM and a
// provider stub only; real-microphone acceptance is a separate human check.
const loudPcm=()=>{const pcm=Buffer.alloc(960);for(let i=0;i<pcm.length;i+=2)pcm.writeInt16LE(2000,i);return pcm;};
const voiceEvents=store=>store.db.prepare("SELECT type,body FROM events WHERE type LIKE 'voice.%' ORDER BY seq").all().map(row=>({type:row.type,body:JSON.parse(row.body)}));
const diagnosticTypes=new Set(['voice.local_turn','voice.local_asr_timing','voice.local_capture_dropped','voice.session_ended','voice.provider_command_rejected','voice.reply_skipped']);
function assertNoPrivateValues(store,config,texts){
  const bodies=voiceEvents(store).filter(e=>diagnosticTypes.has(e.type)).map(e=>JSON.stringify(e.body));assert(bodies.length>0);
  for(const value of [a,b,config.discord.guildId,config.discord.voiceChannelId,...texts])assert(bodies.every(body=>!body.includes(value)),`voice event exposes ${value}`);
}
async function localConversation(t,transcripts,{configure=()=>{}}={}){
  const providers=[],asrCalls=[],errors=[],streams=[];
  const ctx=await fixture(t,options=>{const p=provider(options);providers.push(p);return p;},{configure:config=>{config.voice.transcriptSource='local';config.voice.localAsr={url:'http://127.0.0.1:9000/v1/audio/transcriptions',model:'tiny',language:'ja',timeoutSeconds:20,maxUtteranceSeconds:30};configure(config);},localAsrFactory:()=>({transcribe:async pcm=>{asrCalls.push(pcm.length);return transcripts.shift();}})});
  ctx.channel.members.delete(b);ctx.room.onError=code=>errors.push(code);
  const receive={subscribes:0};ctx.room.connection.receiver={subscribe:()=>{receive.subscribes++;return streams.shift();}};
  const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO),packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));encoder.delete();
  const settle=async()=>{await new Promise(resolve=>setImmediate(resolve));await Promise.allSettled([...ctx.room.draining]);};
  const utter=async({packets=6}={})=>{const stream=new PassThrough();streams.push(stream);await ctx.room.capture(a);for(let i=0;i<packets;i++)stream.write(packet);stream.end();await settle();};
  return {...ctx,providers,asrCalls,errors,streams,receive,packet,settle,utter};
}
async function boundReply(store,config,channel,room){
  const key=store.ingest({provider:'discord',guildId:config.discord.guildId,channelId:channel.id,sourceId:'reply-source',actorId:a,revision:1,final:true,readers:[a],text:'資料',metadata:{}}).key;
  return async(text='回答')=>{await room.speak(text,{epoch:room.epoch,actorId:a,bindings:[{key,revision:1}],authorizeAudience:async()=>[a]});return room.reply;};
}

test('#147 a reply that finished normally is cleared without sending a stop instruction to Live',async t=>{
  const {store,config,room,channel}=await fixture(t,provider);channel.members.delete(b);const session=await room.session(a);const speak=await boundReply(store,config,channel,room);
  const reply=await speak();assert(reply);session.provider.options.onAudio(loudPcm(),session.provider.sessionId,reply.outputGeneration);assert(reply.audible);
  await new Promise(resolve=>setTimeout(resolve,1100));
  assert.equal(room.reply,null);assert.notEqual(session.provider.interrupted,true);assert(room.current(session));
  await room.close();
});

test('#147 speech over a reply and the reply time cap still stop Live output',async t=>{
  const {store,config,room,channel}=await fixture(t,provider);channel.members.delete(b);const session=await room.session(a);const speak=await boundReply(store,config,channel,room);
  const reply=await speak();session.provider.options.onAudio(loudPcm(),session.provider.sessionId,reply.outputGeneration);
  const input=new PassThrough();room.connection.receiver={subscribe:()=>input};await room.capture(a);
  assert.equal(room.reply,null);assert.equal(session.provider.interrupted,true);input.destroy();
  session.provider.interrupted=undefined;config.voice.replySeconds=0.2;assert(await speak());
  await new Promise(resolve=>setTimeout(resolve,300));assert.equal(room.reply,null);assert.equal(session.provider.interrupted,true);
  await room.close();
});

test('#147 a rejected Live command keeps the conversation, so a follow-up without the wake phrase is answered',async t=>{
  const texts=['ことだま、サーバーの状態を教えて','それで負荷はどう？'];const c=await localConversation(t,[...texts]);
  await c.utter();assert.equal(c.providers.length,1);const session=c.room.sessions.get(a);assert(session);assert.equal(c.sources[0].flags.reply,true);
  const speak=await boundReply(c.store,c.config,c.channel,c.room);assert(await speak());
  c.providers[0].options.onEvent('session.command.rejected',{commandType:'session.commentary.append',code:'fixture_rejected'});c.providers[0].options.onError('VOICE_PROVIDER_COMMAND_REJECTED');await c.settle();
  assert.equal(c.room.sessions.get(a),session);assert.equal(session.provider.active,true);assert.equal(c.room.reply,null);assert.notEqual(session.provider.interrupted,true);assert.deepEqual(c.errors,['VOICE_PROVIDER_COMMAND_REJECTED']);
  await c.utter();assert.equal(c.providers.length,1);assert.deepEqual(c.sources[1].flags,{execute:true,reply:true,analyze:true});
  // Answer audio shows the session still works, so only consecutive rejections count.
  const next=await speak();session.provider.options.onAudio(loudPcm(),session.provider.sessionId,next.outputGeneration);
  for(let i=0;i<2;i++)session.provider.options.onError('VOICE_PROVIDER_COMMAND_REJECTED');await c.settle();assert.equal(c.room.sessions.get(a),session);
  const events=voiceEvents(c.store);
  assert.deepEqual(events.filter(e=>e.type==='voice.provider_command_rejected').map(e=>e.body),[{voiceSession:session.id,commandType:'session.commentary.append',code:'fixture_rejected'}]);
  assert.deepEqual(events.filter(e=>e.type==='voice.local_turn').map(e=>[e.body.liveSession,e.body.conversationActive]),[[session.id,true],[session.id,true]]);
  assert.equal(events.some(e=>e.type==='voice.session_ended'),false);assertNoPrivateValues(c.store,c.config,texts);
  await c.room.close();
});

test('#147 a rejected Live command leaves natural-conversation playback to the provider',async t=>{
  const {room,channel}=await fixture(t,provider,{configure:c=>{c.voice.naturalConversation=true;}});channel.members.delete(b);const session=await room.session(a);
  for(let i=0;i<7;i++)session.provider.options.onAudio(Buffer.alloc(960),session.provider.sessionId,0);const reply=room.reply;assert(reply?.started);
  session.provider.options.onError('VOICE_PROVIDER_COMMAND_REJECTED');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(room.sessions.get(a),session);assert.equal(room.reply,reply);await room.close();
});

test('#147 repeated Live command rejections and provider failures still close the conversation',async t=>{
  const texts=['ことだま、状態を教えて','ことだま、もう一度','それで負荷はどう？'];const c=await localConversation(t,[...texts]);
  await c.utter();const first=c.room.sessions.get(a);assert(first);
  for(let i=0;i<3;i++)first.provider.options.onError('VOICE_PROVIDER_COMMAND_REJECTED');await c.settle();
  assert.equal(c.room.sessions.has(a),false);assert.equal(first.provider.active,false);
  await c.utter();const second=c.room.sessions.get(a);assert(second&&second!==first);
  second.provider.active=false;second.provider.options.onError('VOICE_PROVIDER_FAILED');await c.settle();assert.equal(c.room.sessions.has(a),false);
  await c.utter();assert.equal(c.providers.length,2);assert.equal(c.sources.at(-1).flags.reply,false);
  const ended=voiceEvents(c.store).filter(e=>e.type==='voice.session_ended').map(e=>e.body);
  assert.deepEqual(ended.map(e=>[e.voiceSession,e.reason,e.code,e.conversationActive]),[[first.id,'provider_error','VOICE_PROVIDER_COMMAND_REJECTED',true],[second.id,'provider_error','VOICE_PROVIDER_FAILED',true]]);
  assert(ended.every(e=>Number.isInteger(e.durationMs)&&e.durationMs>=0));assertNoPrivateValues(c.store,c.config,texts);
  await c.room.close();
});

test('#147 Live transcripts carry the active conversation to the reply decision after the wake phrase',async t=>{
  const {room,channel,sources}=await fixture(t,provider);channel.members.delete(b);const session=await room.session(a);
  const say=(id,text)=>{session.provider.options.onCompleted({id,text,startMs:0,endMs:1000});return session.chain;};
  await say('idle','今日は雑談です');await say('wake','ことだま、状態を教えて');await say('follow','それで負荷はどう？');
  assert.deepEqual(sources.map(x=>x.s.metadata.conversationActive),[false,true,true]);assert.deepEqual(sources.map(x=>x.flags.reply),[false,true,true]);
  await room.close();
});

test('#147 H1: a capture closed without an end event frees the speaker, and one speaker keeps one receive stream',async t=>{
  const c=await localConversation(t,['ことだま、状態を教えて','それで負荷はどう？']);
  const first=new PassThrough();c.streams.push(first);await c.room.capture(a);await c.room.capture(a);assert.equal(c.receive.subscribes,1);
  for(let i=0;i<6;i++)first.write(c.packet);first.destroy();await c.settle();
  assert.equal(c.room.localCaptures.size,0);assert.equal(c.asrCalls.length,1);
  await c.utter();assert.equal(c.receive.subscribes,2);assert.equal(c.sources.length,2);assert.equal(c.sources[1].flags.reply,true);
  await c.room.close();
});

test('#147 H2: over-long and too-short local captures are recorded as reason codes before any ASR request',async t=>{
  const c=await localConversation(t,['ことだま、状態を教えて'],{configure:config=>{config.voice.localAsr.maxUtteranceSeconds=0.1;}});
  await c.utter();assert.equal(c.asrCalls.length,0);assert.deepEqual(c.errors,['VOICE_UTTERANCE_LIMIT']);
  // The same 0.1 s limit: two packets stay under it but below the 100 ms ASR minimum; no packet records nothing.
  await c.utter({packets:2});await c.utter({packets:0});assert.equal(c.asrCalls.length,0);assert.equal(c.receive.subscribes,3);
  const dropped=voiceEvents(c.store).filter(e=>e.type==='voice.local_capture_dropped').map(e=>e.body);
  assert.deepEqual(dropped.map(e=>[e.reason,e.audioMs]),[['utterance_limit',100],['too_short',40]]);assert(dropped.every(e=>typeof e.voiceSession==='string'));
  assertNoPrivateValues(c.store,c.config,['ことだま、状態を教えて']);
  await c.room.close();
});

test('#147 a skipped voice reply records only a reason code',async t=>{
  const {store,config,room,channel}=await fixture(t,provider);channel.members.delete(b);const speak=await boundReply(store,config,channel,room);
  assert.equal(await speak('秘密の回答'),null);
  await room.speak('秘密の回答',{epoch:room.epoch+1,actorId:a,bindings:[{key:'unused',revision:1}],authorizeAudience:async()=>[a]});
  assert.deepEqual(voiceEvents(store).filter(e=>e.type==='voice.reply_skipped').map(e=>e.body.reason),['no_live_session','epoch_changed']);
  assertNoPrivateValues(store,config,['秘密の回答']);
});
