import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {VoiceRotation,ROTATION_MS} from '../src/voice-rotation.mjs';
import {VoiceRoom} from '../src/voice.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
import {voiceNotice} from '../src/consent.mjs';

async function fixture(t,{enabled=true,deliver}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-rotation-')),store=new Store(root);
  const config={discord:{guildId:'100000000000000001',voiceChannelId:'100000000000000002'},voice:{rotation:{enabled,channelId:'100000000000000003',maxExtendSeconds:60,postWaitSeconds:60}}};
  let clock=0;const sent=[],engines=[];
  const create=()=>{const engine=new VoiceRotation({store,config,now:()=>clock,deliver:async batch=>{sent.push(batch);return deliver?deliver(batch):{state:'sent'};}});engines.push(engine);engine.start({timer:false});return engine;};
  const engine=create();
  t.after(async()=>{for(const item of engines)await item.close();store.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-rotation-'));await rm(root,{recursive:true,force:true});});
  return {store,config,engine,create,sent,at:value=>{clock=value;engine.tick();},flush:()=>Promise.allSettled([...engine.inflight]),rows:()=>store.statement('SELECT * FROM voice_rotations ORDER BY started_ms').all()};
}

test('disabled rotation does not create a timer, table, interval or send',async t=>{
  const f=await fixture(t,{enabled:false});assert.equal(f.engine.begin('speaker'),null);f.at(ROTATION_MS*2);
  assert.equal(f.engine.timer,undefined);assert.equal(f.sent.length,0);
  assert.equal(f.store.statement("SELECT name FROM sqlite_master WHERE name='voice_rotations'").get(),undefined);
});

test('900 seconds closes at an idle boundary and starts the next interval without a gap',async t=>{
  const f=await fixture(t),turn=f.engine.begin('track-a');f.at(1000);f.engine.end(turn);f.engine.complete(turn,{key:'source-one',revision:1});
  f.at(ROTATION_MS-1);assert.equal(f.sent.length,0);
  f.at(ROTATION_MS);await f.flush();assert.equal(f.sent.length,1);
  assert.equal(f.sent[0].startedAt,0);assert.equal(f.sent[0].endedAt,ROTATION_MS);
  assert.equal(f.rows()[1].started_ms,f.rows()[0].ended_ms);assert.equal(f.rows()[0].state,'sent');
});

test('speaking extends the boundary and a late completed turn stays wholly in its original interval',async t=>{
  const f=await fixture(t);f.at(890000);const turn=f.engine.begin('track-a');
  f.at(900000);assert.equal(f.rows().length,1);assert.equal(f.sent.length,0);
  f.at(960000);assert.equal(f.rows().length,2);assert.equal(f.sent.length,0);
  f.at(970000);f.engine.end(turn);f.engine.complete(turn,{key:'whole-utterance',revision:1});await f.flush();
  assert.equal(f.sent.length,1);assert.equal(f.sent[0].endedAt,960000);assert.equal(f.sent[0].entries[0].startedAt,890000);
  assert.equal(f.sent[0].entries[0].key,'whole-utterance');assert.equal(f.sent[0].entries[0].inputAccountId,'track-a');
});

test('pending transcription times out without moving late text into the next file',async t=>{
  const f=await fixture(t);f.at(890000);const turn=f.engine.begin('track-a');f.at(960000);
  f.at(1020000);await f.flush();assert.equal(f.rows()[0].state,'empty');
  f.engine.end(turn);f.engine.complete(turn,{key:'late-source-still-owned-by-store',revision:1});
  f.at(1860000);await f.flush();assert.equal(f.sent.length,0);
});

test('uncertain send is recorded once and never automatically repeated',async t=>{
  const f=await fixture(t,{deliver:()=>{throw Error('synthetic unknown outcome');}}),turn=f.engine.begin('track-a');
  f.engine.end(turn);f.engine.complete(turn,{key:'source-one',revision:1});f.at(900000);await f.flush();
  assert.equal(f.rows()[0].state,'unknown');f.at(1800000);await f.flush();assert.equal(f.sent.length,1);
});

test('startup interrupts unpublished old intervals and begins a fresh interval',async t=>{
  const f=await fixture(t),old=f.engine.current.id;f.engine.stopped=true;f.at(500000);const replacement=f.create();
  assert.equal(f.rows()[0].id,old);assert.equal(f.rows()[0].state,'interrupted');
  assert.equal(replacement.current.startedAt,500000);assert.equal(f.sent.length,0);
});

test('a target or policy change stops the interval instead of publishing to a new audience',async t=>{
  const f=await fixture(t),turn=f.engine.begin('track-a');f.engine.end(turn);f.engine.complete(turn,{key:'source-one',revision:1});
  f.config.voice.rotation.channelId='100000000000000004';f.at(900000);await f.flush();
  assert.equal(f.rows()[0].state,'interrupted');assert.equal(f.sent.length,0);assert.equal(f.engine.begin('track-b'),null);
});

test('real Source commit makes the transcript available before slow intent analysis completes',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-rotation-bind-')),store=new Store(root);
  let clock=0,pipeline,rotation,work,release;const sent=[],errors=[];
  t.after(async()=>{release?.();await work;await pipeline?.close();await rotation?.close();store.close();assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-rotation-bind-'));await rm(root,{recursive:true,force:true});});
  const raw=exampleConfig({workspace:root});raw.discord.voiceChannelId='100000000000000020';raw.voice.mode='minutes';raw.voice.transcriptSource='local';raw.voice.localAsr={url:'http://127.0.0.1:18001',model:'synthetic'};raw.voice.rotation={enabled:true,channelId:'100000000000000021'};
  const config=Config.parse(raw),actor=config.discord.operators[0];
  let started;const analyzing=new Promise(resolve=>{started=resolve;}),hold=new Promise(resolve=>{release=resolve;});
  pipeline=new Pipeline({store,config,analyzer:{analyze:async()=>{started();await hold;return {summary:'synthetic',intents:[],replyRequested:false,reply:'',voiceAction:'none'};}}});
  rotation=new VoiceRotation({store,config,now:()=>clock,deliver:async batch=>{sent.push(batch);return {state:'sent'};}});rotation.start({timer:false});
  const state={actor,id:'synthetic-local-session',epoch:0,revision:0,chain:Promise.resolve(),privacyBasis:config.voice.consentMode,privacyNoticeId:voiceNotice(config).id};
  const room={config,store,pipeline,rotation,epoch:0,mode:'minutes',sessions:new Map(),allowed:()=>true,sourceReaders:async()=>[actor],policy:()=>config,
    connectionReady:()=>false,paused:false,recovering:false,audienceAllowed:()=>true,audience:()=>[actor],onError:code=>errors.push(code)};
  const rotationToken=rotation.begin(actor);clock=5000;rotation.end(rotationToken);
  work=VoiceRoom.prototype.queueLocalTurn.call(room,state,{id:'synthetic-local-turn',text:'合成の発話です',startMs:0,endMs:5000,rotationToken});
  await Promise.race([analyzing,work.then(()=>{throw Error('analysis did not start: '+errors.join(','));})]);
  assert.equal(rotation.current.entries.length,1);
  clock=ROTATION_MS;rotation.tick();await Promise.allSettled([...rotation.inflight]);
  assert.equal(sent.length,1);assert.equal(store.sourceInternal(sent[0].entries[0].key).text,'合成の発話です');
  release();await work;assert.deepEqual(errors,[]);
});
