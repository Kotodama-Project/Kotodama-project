import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as nextTick,setTimeout as delay} from 'node:timers/promises';
import {TranscriptTurns} from '../src/transcripts.mjs';

const fragment=(id,text,startMs,endMs)=>({id,text,startMs,endMs});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
const expectedText=(fragments,turn)=>fragments.filter(f=>f.startMs<turn.endMs&&f.endMs>turn.startMs).sort((a,b)=>a.startMs-b.startMs||a.endMs-b.endMs).map(f=>f.text).join('');

test('a long disjoint stream releases delivery promises and only reads matching history',async t=>{
  let timestampReads=0,delivered=0;
  const transcript=new TranscriptTurns({settleMs:60000,onTurn:turn=>{delivered++;assert.equal(turn.text,'前後');}});
  t.after(()=>transcript.close());
  const count=3000;
  for(let i=0;i<count;i++){
    const start=i*100,turn=transcript.begin(start);let end=turn.endMs;
    Object.defineProperty(turn,'endMs',{get(){timestampReads++;return end;},set(value){end=value;}});
    transcript.end(turn,start+80);
    for(const [suffix,text,offset] of [['b','後',40],['a','前',10]]){
      const item={id:`${i}-${suffix}`,text};
      Object.defineProperties(item,{startMs:{enumerable:true,get(){timestampReads++;return start+offset;}},endMs:{enumerable:true,get(){timestampReads++;return start+offset+10;}}});
      transcript.fragment(item);
    }
    const draining=transcript.flush();
    assert.equal(transcript.pending.size,1);
    await draining;
    assert.equal(transcript.pending.size,0);
  }
  assert.equal(delivered,count);
  assert.equal(transcript.fragments.size,count*2);
  assert(timestampReads<count*40,`stream timestamp reads grew with history: ${timestampReads}`);
  const readsBeforeCorrection=timestampReads;
  transcript.onTurn=turn=>{assert.equal(turn.id,transcript.turns[0].id);assert.equal(turn.text,'前訂正後');};
  transcript.fragment(fragment('late','訂正',25,30));
  await transcript.flush();
  assert(timestampReads-readsBeforeCorrection<30,'a late correction walked unrelated historical turns or fragments');
});

test('out-of-order, equal-start and overlapping intervals preserve all matching text',async t=>{
  const emitted=[];const transcript=new TranscriptTurns({settleMs:60000,onTurn:turn=>emitted.push(turn)});t.after(()=>transcript.close());
  let state=47;const random=max=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state%max;};
  const fragments=[];
  const addFragment=i=>{const start=random(300)*10,item=fragment(`fragment-${i}`,`(${i})`,start,start+10+random(600));fragments.push(item);transcript.fragment(item);};
  for(let i=0;i<300;i++)addFragment(i);
  const turns=[];
  for(let i=0;i<160;i++){const start=random(280)*10,turn=transcript.begin(start);turns.push(turn);}
  for(const turn of [...turns].reverse())transcript.end(turn,turn.startMs+100+random(800));
  for(let i=300;i<600;i++)addFragment(i);
  await transcript.flush();
  assert.equal(emitted.length,turns.length);
  for(const turn of turns)assert.equal(emitted.find(item=>item.id===turn.id).text,expectedText(fragments,turn));
  const correction=fragment('correction','訂正',turns[0].startMs+1,turns[0].endMs-1);fragments.push(correction);transcript.fragment(correction);
  const before=emitted.length;await transcript.close();
  const matching=turns.filter(turn=>correction.startMs<turn.endMs&&correction.endMs>turn.startMs);
  assert.equal(emitted.length-before,matching.length);
  for(const turn of matching){const revisions=emitted.filter(item=>item.id===turn.id);assert.equal(revisions.length,2);assert(revisions[1].revision>revisions[0].revision);assert.equal(revisions[1].text,expectedText(fragments,turn));}
});

test('strict interval boundaries, fragments before VAD and updated turn endpoints stay correct',async t=>{
  const emitted=[];const transcript=new TranscriptTurns({settleMs:60000,onTurn:turn=>emitted.push(turn)});t.after(()=>transcript.close());
  for(const item of [fragment('before','外',-10,0),fragment('middle','中',20,30),fragment('tail','末',90,110),fragment('after','外',100,120)])transcript.fragment(item);
  const turn=transcript.begin(0);transcript.end(turn,100);await transcript.flush();assert.equal(emitted.at(-1).text,'中末');
  transcript.end(turn,80);await transcript.flush();assert.equal(emitted.at(-1).text,'中');
  transcript.end(turn,100);await transcript.flush();assert.equal(emitted.at(-1).text,'中末');
  assert(emitted.every(item=>item.id===turn.id));assert.deepEqual(emitted.map(item=>item.revision),[1,2,3]);
  const open=transcript.begin(200);transcript.fragment(fragment('open','後',200,210));await transcript.flush();assert.equal(emitted.length,3);
  transcript.end(open,220);await transcript.close();assert.equal(emitted.at(-1).text,'後');
});

test('close drains corrections admitted while delivery is pending and is idempotent',async t=>{
  const first=deferred(),second=deferred(),emitted=[];
  const transcript=new TranscriptTurns({settleMs:60000,onTurn:turn=>{emitted.push(turn);return emitted.length===1?first.promise:second.promise;}});
  t.after(()=>{first.resolve();second.resolve();return transcript.close();});
  const turn=transcript.begin(0);transcript.end(turn,100);transcript.fragment(fragment('first','最初',0,10));
  const closing=transcript.close();assert.equal(transcript.close(),closing);assert.equal(transcript.pending.size,1);
  transcript.fragment(fragment('late','訂正',20,30));first.resolve();await nextTick();
  assert.equal(transcript.closed,false);assert.equal(transcript.pending.size,1);assert.equal(emitted.length,2);assert.equal(emitted[0].id,emitted[1].id);assert.equal(emitted[1].text,'最初訂正');
  second.resolve();await closing;assert.equal(transcript.pending.size,0);assert.equal(transcript.closed,true);
  assert.throws(()=>transcript.begin(100),{code:'TRANSCRIPT_CLOSED'});transcript.fragment(fragment('after-close','追加',40,50));await transcript.flush();assert.equal(emitted.length,2);
});

test('timer delivery reports synchronous and asynchronous callback failures and continues',async t=>{
  const reported=[],emitted=[];let calls=0;
  const transcript=new TranscriptTurns({settleMs:1,onTurn:turn=>{emitted.push(turn);if(++calls===1)throw new Error('synchronous fixture');if(calls===2)return Promise.reject(new Error('asynchronous fixture'));},onError:error=>{reported.push(error.message);return Promise.reject(new Error('reporter fixture'));}});t.after(()=>transcript.close());
  const turn=transcript.begin(0);transcript.end(turn,100);transcript.fragment(fragment('first','最初',0,10));await delay(10);
  transcript.fragment(fragment('second','後',20,30));await delay(10);
  transcript.fragment(fragment('third','続',40,50));await transcript.close();
  assert.deepEqual(reported,['synchronous fixture','asynchronous fixture']);assert.equal(emitted.length,3);assert(emitted.every(item=>item.id===turn.id));assert.equal(transcript.pending.size,0);
});

test('duplicate events stay idempotent and conflicting or nonfinite timestamps are refused',async t=>{
  const emitted=[];const transcript=new TranscriptTurns({settleMs:60000,onTurn:turn=>emitted.push(turn)});t.after(()=>transcript.close());
  assert.throws(()=>transcript.begin(NaN),{code:'TRANSCRIPT_INVALID'});
  const turn=transcript.begin(0);assert.throws(()=>transcript.end(turn,Infinity),{code:'TRANSCRIPT_INVALID'});transcript.end(turn,100);
  const item=fragment('same','本文',10,20);transcript.fragment(item);transcript.fragment({...item});
  assert.throws(()=>transcript.fragment({...item,text:'変更'}),{code:'TRANSCRIPT_EVENT_CONFLICT'});
  assert.throws(()=>transcript.fragment(fragment('infinite','本文',10,Infinity)),{code:'TRANSCRIPT_INVALID'});
  await transcript.flush();await transcript.flush();assert.equal(emitted.length,1);
});
