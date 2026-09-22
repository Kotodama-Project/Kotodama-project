import test from 'node:test';
import assert from 'node:assert/strict';
import {AccessGrace,AccessMonitor} from '../src/access-grace.mjs';
import {DiscordAdapter,accessFailure} from '../src/discord.mjs';
import {exampleConfig} from '../src/config.mjs';

const unavailable=Object.assign(new Error('fixture outage'),{code:'ACCESS_UNAVAILABLE'});
const apiError=(status,code)=>Object.assign(new Error('fixture api'),{status,code});

test('Discord failures are classified as denial only for definitive client errors',()=>{
  for(const [status,code] of [[403,50001],[403,50013],[404,10003],[404,10007]])assert.equal(accessFailure(apiError(status,code)),'denied');
  for(const error of [apiError(429,0),apiError(500),apiError(503),Object.assign(new Error('reset'),{code:'ECONNRESET'}),Object.assign(new Error('timeout'),{name:'AbortError'}),new TypeError('fixture'),null])assert.equal(accessFailure(error),'unavailable');
});

test('one transient access failure keeps a running Task; a longer outage or a denial stops it',()=>{
  let now=0;const grace=new AccessGrace({graceMs:5000,maxUnavailable:3,now:()=>now});
  assert.equal(grace.tolerate('task-a',unavailable),true);now+=1000;grace.clear('task-a');
  for(let i=0;i<3;i++){assert.equal(grace.tolerate('task-a',unavailable),true);now+=1000;}
  assert.equal(grace.tolerate('task-a',unavailable),false,'the fourth consecutive failure stops the Task');
  assert.equal(grace.tolerate('task-b',unavailable),true);now+=6000;assert.equal(grace.tolerate('task-b',unavailable),false,'the grace window is time bounded');
  assert.equal(grace.tolerate('task-c',Object.assign(new Error('denied'),{code:'SOURCE_ACCESS_DENIED'})),false,'a denial is never tolerated');
  assert.equal(grace.tolerate('task-d',new Error('unexpected')),false);
  grace.tolerate('task-e',unavailable);grace.tolerate('task-f',unavailable);grace.retain(['task-f']);assert.deepEqual([...grace.pending.keys()],['task-f']);
});

function fixture(t){
  const config=exampleConfig(),actor=config.discord.operators[0];
  const adapter=new DiscordAdapter({config,store:{},pipeline:{}});t.after(()=>adapter.client.destroy());
  const state={fetches:0,failure:null,allowed:true};adapter.member=async()=>({});
  const channel=id=>({id,type:0,guild:{members:{fetch:async()=>({})},roles:{fetch:async()=>{}}},permissionsFor:()=>({has:()=>state.allowed})});
  adapter.client.channels.fetch=async id=>{state.fetches++;if(state.failure)throw state.failure;return channel(id);};
  return {adapter,actor,state};
}

test('channel access is tri-state and a transient failure is never cached',async t=>{
  const {adapter,actor,state}=fixture(t),room={id:'100000000000000030'};
  assert.equal(await adapter.readAccess(room,actor),'allowed');
  state.failure=apiError(503);assert.equal(await adapter.readAccess(room,actor),'unavailable');assert.equal(await adapter.canRead(room,actor),false);
  assert.equal(adapter.accessCache.has(`${room.id}:${actor}`),false);
  state.failure=apiError(404,10003);assert.equal(await adapter.readAccess(room,actor),'denied');
  state.failure=null;state.allowed=false;assert.equal(await adapter.readAccess(room,actor),'denied');
  state.allowed=true;assert.equal(await adapter.readAccess(room,actor),'allowed');
  assert.equal(await adapter.readAccess({id:'100000000000000031'},actor,{cached:false}),'allowed');
});

test('monitoring deduplicates channels, reuses a short cache and drops it on permission events',async t=>{
  const {adapter,actor,state}=fixture(t),a='100000000000000040',b='100000000000000041';
  assert.equal(await adapter.actorAccess(actor,[a,a,b,a],{cached:true}),'allowed');assert.equal(state.fetches,2,'one REST check per distinct channel');
  assert.equal(await adapter.actorAccess(actor,[a,b],{cached:true}),'allowed');assert.equal(state.fetches,2,'cached within the short window');
  state.allowed=false;adapter.client.emit('roleUpdate',{},{});
  assert.equal(await adapter.actorAccess(actor,[a,b],{cached:true}),'denied','a permission event makes revocation visible at the next check');
  state.allowed=true;adapter.accessCache.clear();assert.equal(await adapter.actorAccess(actor,[a],{cached:true}),'allowed');
  state.allowed=false;for(const entry of adapter.accessCache.values())entry.expires=Date.now()-1;
  assert.equal(await adapter.actorAccess(actor,[a],{cached:true}),'denied','revocation without an event is visible once the short cache expires');
  state.allowed=true;adapter.accessCache.clear();state.failure=apiError(500);
  assert.equal(await adapter.actorAccess(actor,[a,b],{cached:true}),'unavailable');
  state.failure=null;adapter.member=async()=>{throw apiError(404,10007);};adapter.accessCache.clear();
  assert.equal(await adapter.actorAccess(actor,[a],{cached:true}),'denied','a removed member is denied');
  await assert.rejects(adapter.actorAccess('100000000000000099',[a]),{code:'OPERATOR_REQUIRED'});
});

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ticks(monitor,probe,{tickMs=20,max=40}={}){
  const started=Date.now();for(let n=1;n<=max;n++){if(!await monitor.check('task-a',probe))return {n,elapsed:Date.now()-started};await sleep(tickMs);}return null;
}

test('a check that never finishes cannot keep a revoked Task running past the bounded window',async()=>{
  // A hung connection or endless 429 retries inside discord.js never settles.
  const monitor=new AccessMonitor({grace:new AccessGrace({graceMs:200,maxUnavailable:3}),limitMs:50});
  const stopped=await ticks(monitor,()=>new Promise(()=>{}));
  assert(stopped,'the Task must be stopped');assert(stopped.elapsed<400,`stopped after ${stopped.elapsed} ms`);
});

test('a slow failure counts from the start of the check, and success resets the window',async()=>{
  const grace=new AccessGrace({graceMs:120,maxUnavailable:10}),monitor=new AccessMonitor({grace,limitMs:1000});
  const slowUnavailable=()=>sleep(80).then(()=>{throw Object.assign(new Error('503'),{code:'ACCESS_UNAVAILABLE'});});
  assert.equal(await monitor.check('task-a',slowUnavailable),true);
  assert.equal(await monitor.check('task-a',slowUnavailable),false,'the second slow failure exceeds 120 ms since the first check began');
  assert.equal(await monitor.check('task-b',slowUnavailable),true);assert.equal(await monitor.check('task-b',async()=>{}),true);assert.equal(grace.pending.has('task-b'),false);
  assert.equal(await monitor.check('task-c',async()=>{throw Object.assign(new Error('denied'),{code:'SOURCE_ACCESS_DENIED'});}),false,'a denial stops at once');
});

test('a hung check is not duplicated and a late success cannot confirm access',async()=>{
  let calls=0,release;const monitor=new AccessMonitor({grace:new AccessGrace({graceMs:10000,maxUnavailable:10}),limitMs:30});
  const probe=()=>{calls++;return new Promise(resolve=>{release=resolve;});};
  assert.equal(await monitor.check('task-a',probe),true);assert.equal(await monitor.check('task-a',probe),true);
  assert.equal(calls,1,'the in-flight check is reused, not stacked');assert.equal(monitor.grace.pending.get('task-a').count,2);
  release();await sleep(0);assert.equal(monitor.grace.pending.get('task-a').count,2,'the late result does not clear the failure');
  assert.equal(await monitor.check('task-a',async()=>{}),true);assert.equal(calls,1);assert.equal(monitor.grace.pending.has('task-a'),false);
});
