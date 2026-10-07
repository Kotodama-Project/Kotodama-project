import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import OpusScript from 'opusscript';
import {VoiceConnectionStatus as State} from '@discordjs/voice';
import {Config,exampleConfig} from '../src/config.mjs';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {VoiceRoom} from '../src/voice.mjs';
import {ResponsesAnalyzer} from '../src/llm.mjs';
import {ProactiveLedger,isProactiveDecline} from '../src/proactive.mjs';
import {voiceNotice} from '../src/consent.mjs';

const a='100000000000000002',b='100000000000000004';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function configFor(enabled=true){const config=exampleConfig();config.discord.voiceChannelId='100000000000000005';
  config.analyzer={kind:'responses',apiKeyEnv:'KOTODAMA_PROACTIVE_TEST_KEY'};
  Object.assign(config.voice,{proactive:{enabled},maxDailyAudioSeconds:1000,apiKeyEnv:'KOTODAMA_PROACTIVE_TEST_KEY',transcriptSource:'local',localAsr:{url:'http://127.0.0.1:9000/v1/audio/transcriptions',model:'fixture'},participantIds:[a,b]});return Config.parse(config);}
async function fixture(t,{enabled=true,cue=async()=>({cue:'question',declined:false})}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-proactive-')),store=new Store(root),config=configFor(enabled),providers=[],calls=[],errors=[];
  process.env.KOTODAMA_PROACTIVE_TEST_KEY='synthetic-fixture';
  const analyzer={proactiveCue:async(...args)=>{calls.push(args);return cue(...args);},analyze:async()=>({summary:'fixture',intents:[],replyRequested:false,reply:'',voiceAction:'none'})};
  const pipeline=new Pipeline({store,config,analyzer,worker:{run:async()=>assert.fail('unsolicited Task')}});
  const channel={id:config.discord.voiceChannelId,guildId:config.discord.guildId,members:new Map([[a,{id:a,user:{bot:false}}],[b,{id:b,user:{bot:false}}]])};
  const client=new EventEmitter();client.channels={cache:new Map([[channel.id,channel]])};let readers=[a,b];
  const room=new VoiceRoom({client,config,store,pipeline,sourceReaders:async()=>readers,localAsrFactory:()=>({transcribe:async()=>''}),onError:code=>errors.push(code),providerFactory:options=>{
    const provider={options,active:false,sessionId:'output-'+providers.length,appended:0,spoken:[],start:async()=>{provider.active=true;},append:()=>provider.appended++,respond:async text=>{provider.spoken.push(text);return {outputGeneration:1};},interrupt(){},abort(){this.active=false;},close:async()=>{provider.active=false;}};providers.push(provider);return provider;
  }});
  room.connection={state:{status:State.Ready},receiver:{subscribe:()=>new PassThrough()},destroy(){this.state={status:State.Destroyed};}};
  let serial=0;
  const source=(text='何を調べればいいですか？',extra={})=>{const item={provider:'discord',guildId:config.discord.guildId,channelId:channel.id,sourceId:'fixture-'+(++serial),actorId:a,revision:serial,final:true,text,readers:[a,b],metadata:{kind:'voice',voiceEpoch:room.epoch,transcriptOrigin:'local_asr',createdAt:new Date().toISOString()},...extra};return {...item,key:store.ingest(item).key};};
  t.after(async()=>{await room.dispose();store.close();delete process.env.KOTODAMA_PROACTIVE_TEST_KEY;assert(path.dirname(root)===os.tmpdir());await rm(root,{recursive:true,force:true});});
  return {root,store,config,room,pipeline,providers,calls,errors,channel,client,source,setReaders:value=>{readers=value;}};
}

test('proactive defaults off and rejects unsupported or looser configurations',()=>{
  assert.equal(exampleConfig().voice.proactive.enabled,false);
  for(const change of [c=>{c.voice.transcriptSource='live';},c=>{c.voice.naturalConversation=true;},c=>{c.analyzer={kind:'codex_cli',executable:'fixture'};}]){const c=configFor();change(c);assert.throws(()=>Config.parse(c),/PROACTIVE_REQUIRES_LOCAL_TRANSCRIPT_AND_RESPONSES/);}
  for(const [key,value]of [['minIntervalSeconds',599],['maxPerDay',4],['declineCooldownSeconds',3599],['checkIntervalSeconds',29],['maxDailyChecks',201]]){const c=configFor();c.voice.proactive[key]=value;assert.throws(()=>Config.parse(c));}
});

test('enabling proactive changes the consent notice and invalidates an existing room binding',async t=>{
  const f=await fixture(t,{enabled:false}),before=voiceNotice(f.config);assert(!before.text.includes('呼びかけのない発話も'));
  f.config.voice.proactive.enabled=true;const after=voiceNotice(f.config);assert.notEqual(after.id,before.id);assert(after.text.includes('呼びかけのない発話も'));assert.equal(f.room.targetMatches(),false);
});

test('disabled proactive sends neither a classifier request nor speech',async t=>{
  const f=await fixture(t,{enabled:false});await f.room.proactive.consider(f.source());assert.equal(f.calls.length,0);assert.equal(f.providers.length,0);
});

test('installation quotas survive reopen, use UTC, and retain cooldown across midnight',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-proactive-quota-'));let store=new Store(root),now=Date.UTC(2026,0,1,23,50),ledger=new ProactiveLedger(store,{now:()=>now});const cfg=configFor().voice.proactive;
  t.after(async()=>{store.close();assert(path.dirname(root)===os.tmpdir());await rm(root,{recursive:true,force:true});});
  assert(ledger.update('check',cfg));assert(!ledger.update('check',cfg));assert(ledger.update('offer',cfg));store.close();store=new Store(root);ledger=new ProactiveLedger(store,{now:()=>now});assert(!ledger.update('offer',cfg));
  now+=600000;assert(ledger.update('check',cfg));ledger.update('decline',cfg);now+=3599999;assert(!ledger.update('check',cfg));now++;assert(ledger.update('check',cfg));
  ledger.update('decline',cfg);now+=3600000;assert(!ledger.update('check',cfg));now=Date.UTC(2026,0,3);assert(ledger.update('check',cfg));
});

test('check and offer caps are independent from intent analysis and cannot reset on rollback',async t=>{
  const f=await fixture(t),cfg={...f.config.voice.proactive,maxDailyChecks:2,maxPerDay:2};let now=100000000;const ledger=new ProactiveLedger(f.store,{now:()=>now});
  assert(ledger.update('check',cfg));now+=30000;assert(ledger.update('check',cfg));now+=30000;assert(!ledger.update('check',cfg));assert(ledger.update('offer',cfg));now+=600000;assert(ledger.update('offer',cfg));now+=600000;assert(!ledger.update('offer',cfg));now=0;assert(!ledger.update('check',cfg));
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM analysis_usage').get().n,0);
});

for(const gate of ['paused','recovering','epoch','unknown','optout','active'])test(`proactive refuses ${gate} before classification`,async t=>{
  const f=await fixture(t),source=f.source();
  if(gate==='paused')f.room.paused=true;if(gate==='recovering')f.room.recovering={};if(gate==='epoch')source.metadata.voiceEpoch--;
  if(gate==='unknown')f.config.discord.unattributedUsers=[b];
  if(gate==='optout')f.config.voice.participantIds=[a];
  if(gate==='active')source.metadata.conversationActive=true;
  await f.room.proactive.consider(source);assert.equal(f.calls.length,0);assert.equal(f.providers.length,0);f.room.recovering=null;
});

test('ambient local transcript reaches an offer without Analysis, intents, or Tasks',async t=>{
  const f=await fixture(t);await f.room.queueLocalTurn(f.room.localState(a),{id:'ambient',text:'予定はどうしましょう？',startMs:0,endMs:200});
  for(let i=0;i<20&&!f.room.reply;i++)await flush();
  assert.equal(f.calls.length,1);assert.equal(f.providers.length,1);assert.equal(f.room.sessions.size,0);
  const p=f.providers[0];assert.equal(p.appended,0);assert.deepEqual(p.options.initialHistory,[]);assert.equal(p.options.naturalConversation,false);assert.match(p.spoken[0],/^Kotodama のエージェントです。質問が出たようだったので/);
  assert.equal(f.store.tasks(a).length,0);assert.equal(f.store.listIntents(a).length,0);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM analysis_usage').get().n,0);
  await f.room.stopSpeech({interruptProvider:false});assert.equal(p.active,false);assert.equal(f.room.proactive.output,null);
});

test('intro interruption closes the output-only provider without forwarding human PCM',async t=>{
  const f=await fixture(t);await f.room.proactive.consider(f.source());assert(f.room.reply);
  const input=new PassThrough();f.room.connection.receiver.subscribe=()=>input;await f.room.capture(a);
  const encoder=new OpusScript(48000,2,OpusScript.Application.AUDIO),packet=Buffer.from(encoder.encode(Buffer.alloc(3840),960));for(let i=0;i<6;i++)input.write(packet);encoder.delete();input.end();await flush();
  assert.equal(f.providers[0].active,false);assert.equal(f.providers[0].appended,0);assert.equal(f.room.sessions.size,0);assert.equal(f.room.reply,null);
  await f.room.proactive.consider(f.source());assert.equal(f.calls.length,1);
});

test('local and classifier declines suppress further sends and speech',async t=>{
  assert(isProactiveDecline('今はいいです。'));assert(!isProactiveDecline('今はいいですか？'));
  const f=await fixture(t,{cue:async()=>({cue:'none',declined:true})});await f.room.proactive.consider(f.source());assert.equal(f.providers.length,0);await f.room.proactive.consider(f.source());assert.equal(f.calls.length,1);
  const g=await fixture(t);await g.room.proactive.consider(g.source('今はいい'));await g.room.proactive.consider(g.source());assert.equal(g.calls.length,0);
});

for(const change of ['epoch','readers','revision','wake'])test(`late cue cannot speak after ${change} changes`,async t=>{
  let resolve;const f=await fixture(t,{cue:()=>new Promise(r=>{resolve=r;})}),source=f.source();const run=f.room.proactive.consider(source);while(!resolve)await flush();
  if(change==='epoch')f.room.epoch++;
  if(change==='readers')f.setReaders([a]);
  if(change==='revision')f.store.ingest({...source,revision:source.revision+1,text:'corrected'});
  if(change==='wake'){const request=f.room.queueLocalTurn(f.room.localState(a),{id:'wake',text:'ことだま、こんにちは',startMs:1,endMs:2});await request;assert.equal(f.room.sessions.size,1);assert.equal(f.calls[0][2].signal.aborted,true);}
  resolve({cue:'question',declined:false});await run;assert.equal(f.providers.filter(p=>p.spoken.length).length,0);
});

test('playback rechecks source revision, audience, and stop commands retain silence',async t=>{
  const f=await fixture(t),source=f.source();await f.room.proactive.consider(source);assert(f.room.canPlay(f.room.reply));
  f.store.ingest({...source,revision:source.revision+1,text:'new'});assert.equal(f.room.canPlay(f.room.reply),false);await f.room.reply.refreshAccess();assert.equal(f.room.reply,null);assert.equal(f.providers[0].active,false);
  await f.room.control.command('stop_speech',{actor:a});assert(!f.room.proactive.ledger.update('check',f.config.voice.proactive));
});

test('an unknown audience member stops an existing intro immediately',async t=>{
  const f=await fixture(t);await f.room.proactive.consider(f.source());assert(f.room.canPlay(f.room.reply));
  f.config.discord.unattributedUsers=[b];assert.equal(f.room.canPlay(f.room.reply),false);await f.room.reply.refreshAccess();assert.equal(f.room.reply,null);assert.equal(f.providers[0].active,false);
});

test('a stale or other-room decline cannot mute the current room',async t=>{
  const f=await fixture(t),source=f.source('今はいい');source.metadata.voiceEpoch--;
  await f.room.proactive.consider(source);await f.room.proactive.consider({...source,channelId:'100000000000000099',metadata:{...source.metadata,voiceEpoch:f.room.epoch}});
  assert(f.room.proactive.ledger.update('check',f.config.voice.proactive));
});

test('Responses cue sends only four truncated texts with strict output and no retries',async t=>{
  const f=await fixture(t);let request,options;const analyzer=new ResponsesAnalyzer(f.config,{sdk:{OpenAI:class{constructor(){this.responses={create:async(body,opts)=>{request=body;options=opts;return {status:'completed',output_text:'{"cue":"schedule","declined":false}'};}};}}}});
  const controller=new AbortController();assert.deepEqual(await analyzer.proactiveCue('a'.repeat(1000),Array.from({length:5},()=>({text:'b'.repeat(1000),secret:'not sent'})),{signal:controller.signal}),{cue:'schedule',declined:false});
  const input=JSON.parse(request.input);assert.equal(input.current.length,600);assert.equal(input.previous.length,3);assert(input.previous.every(s=>s.text.length===600));assert(!request.input.includes('secret'));assert.equal(request.store,false);assert.equal(request.text.format.strict,true);assert.equal(options.signal,controller.signal);assert.equal(options.maxRetries,0);
});
