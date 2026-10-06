import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {InteractionState} from '../src/interaction-state.mjs';
import {Analysis} from '../src/llm.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {VoiceRoom} from '../src/voice.mjs';

const actor='100000000000000002',other='100000000000000004';
const source=(id,extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:id,actorId:actor,readers:[actor],revision:1,text:'対象を調査してください',final:true,metadata:{kind:'text'},...extra});
const intent=(complete=false)=>({kind:'request',title:'調査',request:'指定対象の調査',action:'research',explicit:true,complete,acceptance:[]});
const analysis=(complete=false)=>({summary:'候補',intents:[intent(complete)],replyRequested:false,reply:'',voiceAction:'none',clarification:{intentIndex:0,question:'SYNTHETIC_PRIVATE_QUESTION: 調査する対象はどれですか？'}});
async function fixture(t,{analyze,send}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-clarify-')),store=new Store(root),config=exampleConfig({workspace:root});
  config.analyzer.limits={...config.analyzer.limits,maxConcurrent:4,maxPerRoom:4,maxPerActor:4};
  const calls=[],replies=[],runs=[];
  const pipeline=new Pipeline({store,config,analyzer:{analyze:async(s,c,o)=>{calls.push({source:s,context:c,options:o});return analyze?analyze(s,c,o):analysis();}},
    worker:{run:async task=>{runs.push(task.id);return {state:'needs_review',summary:'candidate',artifacts:[]};}},
    onReply:async reply=>{replies.push(reply);if(send)await send(reply);}});
  const f={root,store,config,pipeline,calls,replies,runs,closed:false};
  t.after(async()=>{if(!f.closed){await pipeline.close();store.close();}assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-clarify-'));await rm(root,{recursive:true,force:true});});
  return f;
}
const ingest=(f,s)=>f.pipeline.ingest(s,{execute:true,reply:true});

test('configuration has adopted once/600 defaults and finite strict limits',()=>{
  const config=exampleConfig();assert.deepEqual(config.interaction,{clarification:'once',clarificationWindowSeconds:600});
  for(const value of [59,3601,1.5])assert.equal(Config.safeParse({...config,interaction:{clarificationWindowSeconds:value}}).success,false);
  for(const clarification of [{intentIndex:-1,question:'q'},{intentIndex:30,question:'q'},{intentIndex:0,question:'x'.repeat(301)}])assert.equal(Analysis.safeParse({...analysis(),clarification}).success,false);
});

test('one question only: duplicate, incomplete answer and following fragments cannot ask again',async t=>{
  const f=await fixture(t);
  await ingest(f,source('first'));await ingest(f,source('first'));
  await ingest(f,source('answer'));await ingest(f,source('still-unclear'));
  assert.equal(f.replies.length,1);assert.equal(f.runs.length,0);assert.equal(f.calls.length,3);
  assert.equal(f.calls[1].options.pendingClarification.question,analysis().clarification.question);
  assert.equal(f.calls[2].options.pendingClarification,null);
  const events=f.store.statement("SELECT body FROM events WHERE type LIKE 'interaction.%'").all();
  assert(events.length>0);assert(!JSON.stringify(events).includes('SYNTHETIC_PRIVATE_QUESTION'));
});

test('pending question is scoped to actor and room',async t=>{
  const f=await fixture(t);f.config.discord.operators.push(other);
  await ingest(f,source('first'));
  await ingest(f,source('someone-else',{actorId:other,readers:[other]}));
  await ingest(f,source('other-room',{channelId:'100000000000000005'}));
  assert.equal(f.replies.length,3);
  assert.equal(f.calls[1].options.pendingClarification,null);assert.equal(f.calls[2].options.pendingClarification,null);
});

test('a complete explicit answer uses current grants and retains existing Task admission',async t=>{
  const f=await fixture(t,{analyze:s=>analysis(s.sourceId==='answer')});
  await ingest(f,source('first'));const receipt=await ingest(f,source('answer'));await f.pipeline.tail;
  assert.equal(receipt.tasks.length,1);assert.equal(f.runs.length,1);assert.equal(f.replies.length,1);
  assert.equal(f.calls[1].options.pendingClarification.sourceKey,f.calls[0].source.key);
});

test('answer is not permission after the action grant is revoked',async t=>{
  const f=await fixture(t,{analyze:s=>analysis(s.sourceId==='answer')});
  await ingest(f,source('first'));f.config.worker.actions=[];
  await assert.rejects(ingest(f,source('answer')),/ACTION_NOT_ALLOWED/);assert.equal(f.runs.length,0);
});

test('ambiguous reply text cannot bypass the one-question field',async t=>{
  const f=await fixture(t,{analyze:()=>({...analysis(),clarification:null,replyRequested:true,reply:'もう一度質問しますか？'})});
  await ingest(f,source('first'));assert.equal(f.replies.length,0);assert.equal(f.runs.length,0);
});

test('a mixed utterance starts its complete Task without opening a redundant question',async t=>{
  const f=await fixture(t,{analyze:()=>({...analysis(),intents:[intent(true),intent(false)],clarification:{intentIndex:1,question:'対象は？'}})});
  const receipt=await ingest(f,source('mixed'));await f.pipeline.tail;
  assert.equal(receipt.tasks.length,1);assert.equal(f.replies.length,0);
});

test('no question without an identified operator, reply route, action or enabled policy',async t=>{
  const f=await fixture(t);
  await ingest(f,source('unknown',{actorId:null,metadata:{kind:'voice',attribution:'unknown_speaker'}}));
  await f.pipeline.ingest(source('not-addressed'),{execute:false,reply:true});
  await f.pipeline.ingest(source('no-reply'),{execute:true,reply:false});
  f.config.interaction.clarification='off';await ingest(f,source('off'));
  f.config.interaction.clarification='once';f.config.worker.actions=[];await ingest(f,source('forbidden'));
  assert.equal(f.replies.length,0);assert.equal(f.runs.length,0);
});

test('native conversation, minutes and stop actions cannot produce a clarification',async t=>{
  let value=analysis();const f=await fixture(t,{analyze:()=>value});
  const voice=id=>source(id,{metadata:{kind:'voice',sessionId:id}});
  f.config.voice.naturalConversation=true;await ingest(f,voice('natural'));
  f.config.voice.naturalConversation=false;f.config.voice.mode='minutes';await ingest(f,voice('minutes'));
  f.config.voice.mode='assist';value={...analysis(),voiceAction:'stop_speech'};await ingest(f,voice('stop'));
  assert.equal(f.replies.length,0);
});

test('concurrent utterances claim at most one send before yielding to the provider',async t=>{
  const f=await fixture(t,{send:()=>new Promise(resolve=>setTimeout(resolve,20))});
  await Promise.all([ingest(f,source('first')),ingest(f,source('concurrent'))]);
  assert.equal(f.replies.length,1);
});

test('unknown delivery stays reserved across restart and cannot be retried as a new question',async t=>{
  const f=await fixture(t,{send:()=>{throw Error('DELIVERY_UNKNOWN');}});
  await assert.rejects(ingest(f,source('first')),/DELIVERY_UNKNOWN/);
  await f.pipeline.close();f.store.close();f.closed=true;
  const reopened=new Store(f.root);
  try{const state=new InteractionState(reopened);assert.equal(state.snapshot(source('second')).phase,'pending');assert.equal(state.claim({...source('second'),key:'unused'},'intent'),false);}finally{reopened.close();}
});

test('window expiry and policy shortening release the old question; future timestamps remain held',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));const ledger=f.pipeline.interactions,state=ledger.last(source('first'));
  assert.equal(ledger.snapshot(source('later'),600,state.asked_at+599999).phase,'pending');
  assert.equal(ledger.snapshot(source('later'),600,state.asked_at+600000),null);
  assert.equal(ledger.snapshot(source('later'),60,state.asked_at+60000),null);
  assert.equal(ledger.snapshot(source('later'),600,state.asked_at-1).phase,'held');
});

test('a withdrawn original is never passed back in pending context',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));
  f.store.ingest(source('first',{revision:2,withdrawn:true,text:''}));
  await ingest(f,source('answer'));assert.equal(f.calls[1].options.pendingClarification,null);assert.equal(f.replies.length,1);
});

test('Voice endSession closes the room actor question and ignores late input from that session',async t=>{
  const f=await fixture(t);f.config.discord.voiceChannelId=f.config.discord.textChannelIds[0];
  await ingest(f,source('first',{metadata:{kind:'voice',sessionId:'session-a'}}));
  const session={id:'session-a',actor,started:Date.now(),provider:{active:false,abort(){}},turns:{close:async()=>{}},chain:Promise.resolve()};
  const room={config:f.config,pipeline:f.pipeline,diagnose(){},sessions:new Map([[actor,session]]),draining:new Set()};
  await VoiceRoom.prototype.endSession.call(room,session,{reason:'voice_command'});
  await ingest(f,source('late',{metadata:{kind:'voice',sessionId:'session-a'}}));assert.equal(f.replies.length,1);
  await ingest(f,source('next',{metadata:{kind:'voice',sessionId:'session-b'}}));assert.equal(f.replies.length,2);
});

test('text question stays a DM and tells the user exactly where replies are accepted',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));const reply=f.replies[0],sent=[];
  const adapter={store:f.store,policy:()=>f.config,client:{user:{id:'100000000000000006'},channels:{fetch:async()=>({})},users:{fetch:async()=>({send:async value=>sent.push(value)})}},member:async()=>{},canRead:async()=>true};
  await DiscordAdapter.prototype.reply.call(adapter,reply);
  assert.equal(sent.length,1);assert(sent[0].content.includes('<#'+reply.source.channelId+'>'));assert(sent[0].content.includes('このDMへの返信は受信しません'));
  assert.deepEqual(sent[0].allowedMentions,{parse:[]});
});

for(const change of ['operator','source'])test('question delivery rechecks '+change+' after asynchronous recipient lookup',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));let sends=0;
  const adapter={store:f.store,policy:()=>f.config,client:{user:{id:'100000000000000006'},channels:{fetch:async()=>({})},users:{fetch:async()=>{
    if(change==='operator')f.config.discord.operators=[];
    else f.store.ingest(source('first',{revision:2,withdrawn:true,text:''}));
    return {send:async()=>{sends++;}};
  }}},member:async()=>{},canRead:async()=>true};
  await assert.rejects(DiscordAdapter.prototype.reply.call(adapter,f.replies[0]),/CLARIFICATION_SCOPE_CHANGED|SOURCE_ACCESS_DENIED/);
  assert.equal(sends,0);
});

for(const change of ['operator','source'])test('voice clarification rechecks '+change+' after audience access awaits',async t=>{
  const f=await fixture(t);await ingest(f,source('first',{metadata:{kind:'voice',sessionId:'voice-a'}}));let responses=0;
  const adapter={store:f.store,policy:()=>f.config,client:{channels:{fetch:async()=>{
    if(change==='operator')f.config.discord.operators=[];
    else f.store.ingest(source('first',{revision:2,withdrawn:true,text:'',metadata:{kind:'voice',sessionId:'voice-a'}}));
    return {};
  }}},canRead:async()=>true,voice:{speak:async(text,options)=>{await options.authorizeAudience([actor]);responses++;}}};
  await assert.rejects(DiscordAdapter.prototype.reply.call(adapter,f.replies[0]),/CLARIFICATION_SCOPE_CHANGED|SOURCE_ACCESS_DENIED/);
  assert.equal(responses,0);
});

test('unaddressed channel chatter does not consume the requested reply route',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));
  await f.pipeline.ingest(source('chatter'),{execute:false,reply:false});
  await ingest(f,source('addressed-answer'));
  assert.equal(f.calls[1].options.pendingClarification,null);
  assert.equal(f.calls[2].options.pendingClarification.sourceKey,f.calls[0].source.key);
});

test('the verified original request survives a full recent-context window',async t=>{
  const f=await fixture(t);f.config.analyzer.maxContextSources=1;f.config.discord.operators.push(other);
  await ingest(f,source('first',{text:'SYNTHETIC_ORIGINAL_REQUEST: 対象を指定したら調査してください'}));
  for(let n=0;n<3;n++)await f.pipeline.ingest(source('chatter-'+n,{actorId:other,readers:[actor,other],text:'unrelated'}),{execute:false,reply:false});
  await ingest(f,source('answer',{text:'対象は合成資料Aです'}));
  assert(f.calls.at(-1).context.some(item=>item.key===f.calls[0].source.key&&item.text.includes('SYNTHETIC_ORIGINAL_REQUEST')));
  assert.equal(f.calls.at(-1).context.length,1);
});

for(const failure of ['timeout','invalid','changed'])test('failed answer analysis can retry with pending context: '+failure,async t=>{
  let f;f=await fixture(t,{analyze:s=>{
    if(s.sourceId==='bad-answer'){
      if(failure==='timeout')throw Error('SYNTHETIC_TIMEOUT');
      if(failure==='invalid')return {};
      f.store.ingest({...s,revision:2,text:'synthetic correction'});
    }
    return analysis();
  }});
  await ingest(f,source('first'));await assert.rejects(ingest(f,source('bad-answer')));
  await ingest(f,source('retry-answer'));
  assert.equal(f.calls.at(-1).options.pendingClarification.sourceKey,f.calls[0].source.key);
  assert.equal(f.replies.length,1);
});

test('current Discord channel access is checked after recipient lookup',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));let readable=true,sends=0;
  const adapter={store:f.store,policy:()=>f.config,client:{user:{id:'100000000000000006'},channels:{fetch:async()=>({})},users:{fetch:async()=>{readable=false;return {send:async()=>sends++};}}},member:async()=>{},canRead:async()=>readable};
  await assert.rejects(DiscordAdapter.prototype.reply.call(adapter,f.replies[0]),/SOURCE_ACCESS_DENIED/);
  assert.equal(sends,0);
});

test('only one concurrent successful answer consumes the same pending request',async t=>{
  let release;const ready=new Promise(resolve=>{release=resolve;});
  const f=await fixture(t,{analyze:async s=>{if(s.sourceId.startsWith('answer')){await ready;return analysis(true);}return analysis();}});
  await ingest(f,source('first'));
  const first=ingest(f,source('answer-one')),second=ingest(f,source('answer-two'));
  await new Promise(resolve=>setImmediate(resolve));release();
  const outcomes=await Promise.allSettled([first,second]);await f.pipeline.tail;
  assert.equal(outcomes.filter(item=>item.status==='fulfilled').length,1);
  assert.equal(f.runs.length,1);
});

test('failure after successful analysis releases only that consumed answer',async t=>{
  const f=await fixture(t);await ingest(f,source('first'));let changed=false;
  f.pipeline.readPolicy=async()=>{if(!changed){changed=true;f.store.ingest(source('bad-answer',{revision:2,text:'changed while admitting'}));}return f.config;};
  await assert.rejects(ingest(f,source('bad-answer')),/CONTEXT_CHANGED/);
  await ingest(f,source('retry-answer'));
  assert.equal(f.calls.at(-1).options.pendingClarification.sourceKey,f.calls[0].source.key);
  assert.equal(f.replies.length,1);
});

test('an original request is refused rather than truncated when it cannot fit context',async t=>{
  const f=await fixture(t);f.config.analyzer.maxContextChars=1000;
  const text='SYNTHETIC_COMPLETE_ORIGINAL_'+ 'あ'.repeat(1500);
  await ingest(f,source('first',{text}));
  await assert.rejects(ingest(f,source('answer')),/CLARIFICATION_CONTEXT_BUDGET/);
  assert.equal(f.calls.length,1);assert.equal(f.replies.length,1);
  f.config.analyzer.maxContextChars=2000;await ingest(f,source('retry'));
  assert.equal(f.calls.at(-1).context[0].text,text);
});
