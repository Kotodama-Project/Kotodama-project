import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {ModalBuilder,ActionRowBuilder,MessageFlags} from 'discord.js';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {exampleConfig} from '../src/config.mjs';
import {correctionId,correctionModal,parseCorrectionId} from '../src/native-corrections.mjs';
const a='100000000000000002',b='100000000000000004',stranger='100000000000000009';
async function fixture(t,kind='text'){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-correction-')),config=exampleConfig({workspace:root}),store=new Store(root),executions=[];
  config.discord.operators=[a,b];
  const pipeline=new Pipeline({store,config,analyzer:{analyze:async()=>assert.fail('native correction does not ask the model for authority')},worker:{run:async task=>{executions.push(task);return {state:'needs_review',summary:'synthetic result',artifacts:[],taskRevision:task.revision};}}});
  const original={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'original-source',actorId:a,revision:100,final:true,text:'原文の依頼',readers:[a,b],metadata:{kind,...(kind==='voice'?{sessionId:'synthetic-voice',transcriptOrigin:'local_asr',voiceEpoch:0,transcriptCorrection:{text:'old sidecar',uncertain:true}}:{})}};
  const created=await pipeline.request(original,{title:'元の件名',request:original.text,action:'research',acceptance:['元の条件']});await pipeline.tail;
  const adapter=new DiscordAdapter({config,store,pipeline});adapter.verifiedInstallation=true;adapter.member=async actor=>{assert([a,b].includes(actor));return {id:actor};};
  t.after(async()=>{await pipeline.close();adapter.client.destroy();store.close();assert(path.dirname(root)===os.tmpdir());await rm(root,{recursive:true,force:true});});
  const target=()=>store.correctionTarget(created.id,a);
  const input=()=>{const {task,source}=target();return {taskRevision:task.revision,sourceRevision:source.revision,title:'新しい件名',request:'訂正した依頼',acceptance:['新しい条件'],interactionId:'900000000000000001',at:200};};
  const interaction=(kind,customId,{actor=a,values=[],fields={title:'新しい件名',request:'訂正した依頼',acceptance:'条件一\n条件二'}}={})=>({
    id:'900000000000000001',createdTimestamp:200,guildId:config.discord.guildId,user:{id:actor},customId,values,deferred:false,replied:false,
    isButton:()=>kind==='button',isStringSelectMenu:()=>kind==='select',isModalSubmit:()=>kind==='modal',isChatInputCommand:()=>false,
    fields:{getTextInputValue:name=>fields[name]},deferReply:async function(value){this.deferred=true;this.defer=value;},editReply:async function(value){this.response=value;},reply:async function(value){this.replied=true;this.response=value;},showModal:async function(value){this.replied=true;this.modal=new ModalBuilder(value).toJSON();}
  });
  return {config,store,pipeline,adapter,original,created,executions,target,input,interaction};
}

for(const kind of ['text','voice'])test(`${kind} native correction keeps one Source key and Task ID through artifact readback`,async t=>{
  const f=await fixture(t,kind),before=f.target(),corrected=await f.pipeline.correctTask(f.created.id,a,f.input());await f.pipeline.tail;
  assert.equal(corrected.id,before.task.id);assert.equal(corrected.source_key,before.source.key);assert(corrected.revision>before.task.revision);assert.equal(corrected.source_revision,200);
  const source=f.store.source(corrected.source_key,a);assert.equal(source.text,'訂正した依頼');assert.equal(source.metadata.kind,kind);assert.equal(source.metadata.transcriptCorrection,null);assert.equal(source.metadata.manualCorrection.previousSourceRevision,100);assert.equal(source.metadata.manualCorrection.actor,a);
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,1);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM sources').get().n,1);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM source_versions').get().n,2);
  assert.equal((await f.pipeline.result(corrected.id,a)).summary,'synthetic result');assert.deepEqual(f.executions.map(row=>row.id),[corrected.id,corrected.id]);
});

test('spoken correction and a following modal correction remain in the same Task history',async t=>{
  const f=await fixture(t,'voice'),first=f.target();
  f.pipeline.analyzer.analyze=async source=>({summary:'音声の訂正',intents:[{kind:'request',title:'音声の訂正',request:source.text,action:'research',targetTaskId:f.created.id,explicit:true,complete:true,acceptance:['音声の条件']}],replyRequested:false,reply:'',voiceAction:'none',clarification:null});
  await f.pipeline.ingest({...f.original,sourceId:'spoken-correction',revision:150,text:'先ほどの仕事をこの条件に訂正して',metadata:{...f.original.metadata,conversationActive:true}},{execute:true,reply:false});await f.pipeline.tail;
  const spoken=f.target();assert.equal(spoken.task.id,first.task.id);assert.notEqual(spoken.source.key,first.source.key);
  const updated=await f.pipeline.correctTask(f.created.id,a,f.input());await f.pipeline.tail;assert.equal(updated.source_key,spoken.source.key);assert.equal(updated.id,first.task.id);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,1);
  const events=f.store.db.prepare("SELECT body FROM events WHERE type='task.corrected' ORDER BY seq").all().map(row=>JSON.parse(row.body));assert.equal(events[0].previousSource,first.source.key);assert.equal(events[0].source,spoken.source.key);assert.equal(events[1].previousSource,spoken.source.key);assert.equal(events[1].source,spoken.source.key);
});

test('button, select and Label modal use validated Discord payloads and submit through the same pipeline',async t=>{
  const f=await fixture(t),target=f.target(),button=(await f.adapter.corrections.buttons(target.task.id,a,target.task.revision))[0];assert(new ActionRowBuilder(button).toJSON());
  const open=f.interaction('button',button.components[0].custom_id);await f.adapter.interaction(open);assert.equal(open.modal.title,'依頼を訂正して実行');assert(open.modal.components.every(c=>c.type===18));assert.equal(f.executions.length,1);
  const menu=await f.adapter.corrections.menu([target.task],a);assert(new ActionRowBuilder(menu[0]).toJSON());
  const select=f.interaction('select','kc:select',{values:[menu[0].components[0].options[0].value]});await f.adapter.interaction(select);assert.deepEqual(select.modal,open.modal);
  const submit=f.interaction('modal',open.modal.custom_id);await f.adapter.interaction(submit);await f.pipeline.tail;
  assert.equal(submit.defer.flags,MessageFlags.Ephemeral);assert.match(submit.response.content,/同じ仕事/);assert(submit.response.content.includes(target.task.id));assert.deepEqual(f.store.task(target.task.id,a).acceptance,['条件一','条件二']);assert.equal(f.executions.length,2);
});

test('stale modal and duplicate submission do not add Source versions or executions',async t=>{
  const f=await fixture(t),id=correctionId(f.target(),'submit');await f.adapter.interaction(f.interaction('modal',id));await f.pipeline.tail;
  const replay=f.interaction('modal',id);await f.adapter.interaction(replay);assert.match(replay.response.content,/更新されています/);assert.equal(f.executions.length,2);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM source_versions').get().n,2);
});

test('a freeform edit wins CAS over an older UI and both later edits share the original history',async t=>{
  const f=await fixture(t),input=f.input(),key=f.target().source.key;
  await f.pipeline.ingest({...f.store.source(key,a),revision:150,text:'自由文の編集'},{analyze:false});
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),error=>['TASK_CHANGED','SOURCE_CHANGED'].includes(error.code));
  const changed=await f.pipeline.correctTask(f.created.id,a,f.input());await f.pipeline.tail;assert.equal(changed.source_key,key);assert.equal(changed.id,f.created.id);
  const texts=f.store.db.prepare('SELECT body FROM source_versions WHERE key=? ORDER BY revision').all(key).map(row=>JSON.parse(row.body).text);assert.deepEqual(texts,['原文の依頼','自由文の編集','訂正した依頼']);
});

for(const actor of [b,stranger])test(`a different actor cannot use another owner's modal (${actor})`,async t=>{
  const f=await fixture(t),i=f.interaction('modal',correctionId(f.target(),'submit'),{actor});await f.adapter.interaction(i);assert.match(i.response.content,/訂正できません/);assert.equal(f.executions.length,1);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM source_versions').get().n,1);
});

test('revoked grant and wrong guild are refused without changing Source or Task',async t=>{
  const f=await fixture(t),input=f.input();f.config.worker.actions=[];await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),{code:'ACTION_NOT_ALLOWED'});
  const i=f.interaction('modal',correctionId(f.target(),'submit'));i.guildId='100000000000000099';await f.adapter.interaction(i);assert.match(i.response.content,/SOURCE_ACCESS_DENIED/);assert.equal(f.store.source(f.created.source_key,a).revision,100);
});

for(const state of ['running','stopping','uncertain'])test(`a related ${state} operation blocks correction and remains unchanged`,async t=>{
  const f=await fixture(t),source=f.target().source,input=f.input();const other=f.store.createTask(source,{key:'other-operation',title:'別の処理',request:'別の依頼',action:'research'});f.store.claim(other.id,other.revision);
  if(state==='stopping')f.store.cancel(other.id,a);if(state==='uncertain')f.store.finish(other.id,other.revision,{state:'uncertain',summary:'unknown process',artifacts:[]});
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),{code:'TASK_CORRECTION_BUSY'});assert.equal(f.store.taskInternal(other.id).state,state);assert.equal(f.store.source(source.key,a).revision,100);
});

test('authorization races preserve the winning source and reject the older UI atomically',async t=>{
  const f=await fixture(t),input=f.input(),key=f.created.source_key;let once=false;
  f.pipeline.authorize=async()=>{if(!once){once=true;f.store.ingest({...f.store.source(key,a),revision:180,text:'認可中の編集'});}};
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),error=>['TASK_CHANGED','SOURCE_CHANGED'].includes(error.code));assert.equal(f.store.source(key,a).text,'認可中の編集');assert.equal(f.executions.length,1);
});

test('remote mode refuses before calling an owner or writing a local Task projection',async t=>{
  const f=await fixture(t),input=f.input();let called=0;f.pipeline.owner={kind:'remote',correctTask:async()=>called++};f.config.owner={kind:'remote',url:'https://example.invalid',tokenEnv:'SYNTHETIC_TOKEN'};
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),{code:'TASK_CORRECTION_REQUIRES_LOCAL_OWNER'});assert.equal(called,0);assert.equal(f.store.source(f.created.source_key,a).revision,100);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,1);
});

test('invalid correction fields roll back without changing the Source history',async t=>{
  const f=await fixture(t);for(const change of [{request:''},{request:'x'.repeat(4001)},{title:'x'.repeat(121)},{acceptance:Array(21).fill('x')},{acceptance:['']},{interactionId:'bad'},{at:Infinity}])assert.throws(()=>f.store.correctTask(f.created.id,a,{...f.input(),...change}));
  assert.equal(f.store.source(f.created.source_key,a).revision,100);assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM source_versions').get().n,1);
});

test('malformed IDs are refused and forms never copy private prefills',async t=>{
  const f=await fixture(t);for(const value of ['kc:submit:task-x:NaN:1','kc:edit:task-x:zzzzzzzzzzzzzz:1','kc:edit:task-x:0:1'])assert.throws(()=>parseCorrectionId(value,'edit'));
  const target=f.target();target.source.text='x'.repeat(4001);assert(correctionModal(target).components.every(c=>!('value' in c.component)));
  assert.deepEqual(await f.adapter.corrections.buttons(f.created.id,a,undefined),[]);
});

for(const viaContext of [false,true])test(`shared Source correction preserves another completed Task (${viaContext?'context':'primary'})`,async t=>{
  const f=await fixture(t),input=f.input(),source=f.target().source;
  const siblingSource=viaContext?{...source,sourceId:'sibling-source',key:undefined}:source;
  if(viaContext)siblingSource.key=f.store.ingest(siblingSource).key;
  const sibling=f.store.createTask(siblingSource,{key:'sibling',title:'保持する別の仕事',request:'別の依頼',action:'research',contextSources:viaContext?[{key:source.key,revision:source.revision}]:[]});
  f.store.claim(sibling.id,sibling.revision);f.store.finish(sibling.id,sibling.revision,{state:'needs_review',summary:'保持する成果',artifacts:[]});const before=f.store.taskInternal(sibling.id);
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,input),{code:'TASK_CORRECTION_SHARED_SOURCE'});assert.deepEqual(f.store.taskInternal(sibling.id),before);assert.equal(f.store.source(source.key,a).revision,100);
});

test('blank modal opens immediately without waiting for network authorization',async t=>{
  const f=await fixture(t),i=f.interaction('button',correctionId(f.target()));let release;const wait=new Promise(resolve=>{release=resolve;});f.adapter.member=()=>wait;
  const running=f.adapter.interaction(i);try{assert(i.modal);assert(i.modal.components.every(c=>!('value' in c.component)));}finally{release();await running;}
});

test('modal submission defers its response before slow membership authorization',async t=>{
  const f=await fixture(t),i=f.interaction('modal',correctionId(f.target(),'submit'));let release;const wait=new Promise(resolve=>{release=resolve;});f.adapter.member=()=>wait;
  const running=f.adapter.interaction(i);try{assert.equal(i.deferred,true);}finally{release();await running;await f.pipeline.tail;}
});

test('manual correction stays distinct from ASR and is not replaced by an archive projection',async t=>{
  const f=await fixture(t,'voice'),original=f.target().source;
  await f.pipeline.ingest({...original,revision:150,metadata:{...original.metadata,archiveSessionRefs:['synthetic-archive']}},{analyze:false});
  const updated=await f.pipeline.correctTask(f.created.id,a,f.input());await f.pipeline.tail;
  const current=f.store.source(updated.source_key,a);assert.equal(current.metadata.transcriptOrigin,'manual_correction');assert.equal(current.metadata.finality,'manual_correction');
  f.store.ingest({...original,sourceId:'archive-projection',revision:151,text:'archive transcript',metadata:{kind:'archived_voice',sessionId:'synthetic-archive'}});
  assert(f.store.contextSources(a,{guildId:f.config.discord.guildId,channelId:f.config.discord.resultChannelId}).some(source=>source.key===updated.source_key));
});

test('a grant revoked after atomic correction cancels the new queued revision before execution',async t=>{
  const f=await fixture(t);let calls=0;f.pipeline.authorize=async()=>{if(++calls===2)f.config.worker.actions=[];};
  await assert.rejects(f.pipeline.correctTask(f.created.id,a,f.input()),{code:'ACTION_NOT_ALLOWED'});await f.pipeline.tail;assert.equal(f.store.taskInternal(f.created.id).state,'cancelled');assert.equal(f.executions.length,1);assert.equal(f.store.source(f.created.source_key,a).text,'訂正した依頼');
});

test('opening a static modal does not request a private Source snapshot',async t=>{
  const f=await fixture(t),id=correctionId(f.target());f.pipeline.correctionTarget=async()=>assert.fail('no Source fetch before modal');f.adapter.member=async()=>assert.fail('no network before modal');
  const i=f.interaction('button',id);await f.adapter.interaction(i);assert(i.modal);assert(!JSON.stringify(i.modal).includes('原文の依頼'));
});

for(const kind of ['modal'])test(`Discord access events during authorization block ${kind} without disclosure or mutation`,async t=>{
  const f=await fixture(t),id=correctionId(f.target(),kind==='modal'?'submit':'edit'),read=f.pipeline.correctionTarget.bind(f.pipeline);
  f.pipeline.correctionTarget=async(...args)=>{const target=await read(...args);queueMicrotask(()=>f.adapter.client.emit('channelUpdate',{},{ }));return target;};
  const i=f.interaction(kind,id);await f.adapter.interaction(i);await f.pipeline.tail;assert.equal(i.modal,undefined);assert.match(i.response.content,/SOURCE_ACCESS_DENIED/);assert.equal(f.store.source(f.created.source_key,a).revision,100);assert.equal(f.executions.length,1);
});
