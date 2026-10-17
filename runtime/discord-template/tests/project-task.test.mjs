import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {ProjectHub} from '../src/project-hub.mjs';
import {validateProject} from '../src/project-contract.mjs';
import {digest} from '../src/common.mjs';

const actor='100000000000000002',other='100000000000000009';
const brief={outcome:'依頼を既存の仕事へつなぐ',in_scope:['調査'],out_of_scope:[],constraints:['原文を保持'],acceptance:['状態を辿れる'],unknowns:[]};
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-task-'));let store=new Store(root),authorize=async()=>{},epoch=0;
  const config={installation:'fixture',dataDir:root,owner:{kind:'local'},worker:{workspace:root},discord:{guildId:'guild',operators:[actor,other],textChannelIds:['channel','other-channel'],resultChannelId:'channel'},
    projects:{operations:['read','create','inspect','correct','link_task','unlink_task','read_task']}};
  let policy=structuredClone(config),reader=async()=>policy;
  const build=()=>new ProjectHub({store,config,policy:()=>policy,readConfig:()=>reader(),authorizeSource:(...args)=>authorize(...args),accessEpoch:()=>epoch});let hub=build();
  const source=(id,extra={})=>{const value={provider:'discord',guildId:'guild',channelId:'channel',sourceId:id,actorId:actor,revision:1,readers:[actor],final:true,text:id,...extra};const {key}=store.ingest(value);return store.sourceInternal(key);};
  const origin=source('original'),ref={key:origin.key,revision:origin.revision};
  const task=(id,extra={})=>{const s=source(id,extra);return store.createTask(s,{title:'依頼',request:'調査する',action:'research',acceptance:['出典を示す'],contextSources:[]});};
  const create=()=>hub.handle({actor,operation:'create',request_id:'create',name:'Project',source:ref,brief});
  const link=(view,task,extra={})=>({actor,operation:'link_task',request_id:'link-'+task.id,project_id:view.project.project_id,expected_revision:view.project.revision,base_digest:view.project_digest,
    source:ref,reason:'この仕事を関連付ける',task_id:task.id,expected_task_revision:task.revision,...extra});
  const read=(view,task)=>hub.handle({actor,operation:'read_task',project_id:view.project.project_id,task_id:task.id});
  t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});
  return {root,config,source,origin,ref,task,create,link,read,get store(){return store;},get hub(){return hub;},get policy(){return policy;},set policy(value){policy=value;},set authorize(value){authorize=value;},set reader(value){reader=value;},bumpAccess(){epoch++;},
    restart(){store.close();store=new Store(root);store.reconcileInterrupted();hub=build();}};
}

test('link promotes only that Project to v2 with explicit local Task identity and immutable causal event',async t=>{
  const f=await fixture(t),project=await f.create(),task=f.task('task'),before=f.store.taskInternal(task.id),input=f.link(project,task),linked=await f.hub.handle(input);
  assert.equal(project.project.version,1);assert.equal(linked.project.version,2);assert.equal(linked.project.revision,2);
  assert.deepEqual(linked.project.task_refs,[{adapter:'discord_local_task_v1',task_id:task.id,revision:task.revision}]);
  assert.deepEqual(f.store.taskInternal(task.id),before);assert.equal(linked.project.original_ref,project.project.original_ref);
  const old=JSON.parse(f.store.statement('SELECT body FROM project_versions WHERE revision=1').get().body);assert.deepEqual(old,project.project);
  const event=JSON.parse(f.store.statement("SELECT body FROM events WHERE type='project.task_linked'").get().body);
  assert.equal(event.previous_digest,project.project_digest);assert.deepEqual(event.task_ref,linked.project.task_refs[0]);assert.equal(event.reason,input.reason);
  const replay=await f.hub.handle(input);assert.equal(replay.replay,true);assert.equal(replay.project_digest,linked.project_digest);
  const observation=await f.read(linked,task);assert.equal(observation.owner_state,'queued');assert.equal(observation.resolution,'observed');assert.equal(observation.completion,'not_observed');
});

test('read observes context growth and result metadata within the same revision without exposing content or paths',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.store.claim(task.id,task.revision);const context=f.source('another-speaker',{actorId:other,readers:[actor,other]});
  f.store.bindContext(task.id,task.revision,[{key:task.source_key,revision:task.source_revision},{key:context.key,revision:context.revision}]);
  let observed=await f.read(project,task);assert.equal(observed.owner_state,'running');assert.equal(observed.resolution,'observed');assert.equal(observed.source_refs.length,2);
  f.store.finish(task.id,task.revision,{state:'needs_review',summary:'DO_NOT_RETURN_SUMMARY',workspace:path.join(f.root,'private-workspace'),artifacts:[{path:path.join(f.root,'private-result'),sha256:digest('fixture'),bytes:7}],
    validations:[{status:'passed',command:'DO_NOT_RETURN_COMMAND'}],verifiedExecution:true,independentReview:false,taskRevision:task.revision,sourceRevision:task.source_revision});
  observed=await f.read(project,task);assert.equal(observed.owner_state,'needs_review');assert.deepEqual(observed.result_metadata,{availability:'reported',artifact_count:1,checks:'reported_pass',execution:'reported',independent_review:'unobserved',artifact_readback:'not_run'});
  const output=JSON.stringify(observed);assert.equal(output.includes(f.root),false);assert.equal(output.includes('DO_NOT_RETURN'),false);assert.equal(observed.completion,'not_observed');
  // No artifact file was created: this operation deliberately reports metadata,
  // and never mislabels the existing owner's report as an artifact readback.
});

test('revision changes stay visible without silently adopting corrected Task results',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.store.cancel(task.id,actor);const cancelled=f.store.taskInternal(task.id),observation=await f.read(project,task);
  assert.equal(observation.owner_state,'cancelled');assert.equal(observation.resolution,'revision_changed');assert.equal(observation.current_task_revision,cancelled.revision);assert.equal(observation.result_metadata.availability,'unavailable');
  const rebound=await f.hub.handle(f.link(project,cancelled,{request_id:'rebind'}));assert.equal(rebound.project.task_refs[0].revision,cancelled.revision);
  assert.equal((await f.read(rebound,task)).resolution,'observed');assert.equal(f.store.taskInternal(task.id).state,'cancelled');
  f.store.resume(task.id,actor);assert.equal((await f.read(rebound,task)).resolution,'revision_changed');
});

test('brief correction preserves links and lists actual impacted Tasks',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  const input={actor,operation:'inspect',project_id:project.project.project_id,expected_revision:project.project.revision,base_digest:project.project_digest,source:f.ref,reason:'要件訂正',brief:{...brief,unknowns:['納期']}};
  const candidate=await f.hub.handle(input);assert.deepEqual(candidate.impact_task_refs,project.project.task_refs);
  const corrected=await f.hub.handle({...input,operation:'correct',request_id:'correct'});assert.equal(corrected.project.version,2);assert.deepEqual(corrected.project.task_refs,project.project.task_refs);
  assert.deepEqual(JSON.parse(f.store.statement("SELECT body FROM events WHERE type='project.corrected'").get().body).impact_task_refs,project.project.task_refs);
});

test('unlink changes only Project and remains possible after Task access is revoked',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.store.ingest({...f.store.sourceInternal(task.source_key),revision:2,readers:[other]});const before=f.store.taskInternal(task.id);
  await assert.rejects(f.read(project,task),/SOURCE_ACCESS_DENIED/);
  const {expected_task_revision,...input}=f.link(project,task,{operation:'unlink_task',request_id:'unlink'}),unlinked=await f.hub.handle(input);
  assert.deepEqual(unlinked.project.task_refs,[]);assert.equal(unlinked.project.version,2);assert.deepEqual(f.store.taskInternal(task.id),before);
  assert.equal((await f.hub.handle(input)).replay,true);await assert.rejects(f.read(unlinked,task),/PROJECT_TASK_NOT_LINKED/);
});

test('Task access cannot bypass Project origin access, and Task links cannot bypass Task access',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.store.ingest({...f.origin,revision:2,readers:[other]});await assert.rejects(f.read(project,task),/SOURCE_ACCESS_DENIED/);
  f.store.ingest({...f.origin,revision:3,readers:[actor]});f.store.ingest({...f.store.sourceInternal(task.source_key),revision:2,readers:[other]});await assert.rejects(f.read(project,task),/SOURCE_ACCESS_DENIED/);
});

test('another actor/room Task, an unlinked Task, and a stale Task revision are refused',async t=>{
  const f=await fixture(t),project=await f.create(),task=f.task('task'),foreign=f.task('foreign',{actorId:other,readers:[other]}),room=f.task('room',{channelId:'other-channel'});
  await assert.rejects(f.hub.handle(f.link(project,foreign)),/PROJECT_TASK_UNAVAILABLE/);await assert.rejects(f.hub.handle(f.link(project,room)),/PROJECT_TASK_SCOPE_MISMATCH/);
  await assert.rejects(f.read(project,task),/PROJECT_TASK_NOT_LINKED/);await assert.rejects(f.hub.handle(f.link(project,task,{expected_task_revision:2})),/PROJECT_TASK_REVISION_STALE/);
  assert.equal(f.store.statement('SELECT COUNT(*) AS n FROM project_versions').get().n,1);
});

test('historical context access is required even if its current revision is newly readable',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task)),hidden=f.source('hidden',{readers:[other]});
  f.store.ingest({...hidden,revision:2,readers:[actor]});
  // Simulate retained older binding bytes to exercise the historical access
  // boundary independently of the current reader index.
  const body=JSON.parse(f.store.statement('SELECT body FROM tasks WHERE id=?').get(task.id).body);body.contextSources=[{key:hidden.key,revision:1}];
  f.store.statement('UPDATE tasks SET body=? WHERE id=?').run(JSON.stringify(body),task.id);
  await assert.rejects(f.read(project,task),/SOURCE_ACCESS_DENIED/);
});

test('current context revocation and in-flight Task/context changes refuse stale read metadata',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task)),context=f.source('context',{actorId:other,readers:[actor]});
  f.store.claim(task.id,task.revision);f.store.bindContext(task.id,task.revision,[{key:context.key,revision:1}]);
  f.authorize=async()=>{f.store.cancel(task.id,actor);};await assert.rejects(f.read(project,task),/PROJECT_TASK_CHANGED/);
  f.authorize=async()=>{};f.store.ingest({...context,revision:2,readers:[other]});await assert.rejects(f.read(project,task),/SOURCE_ACCESS_DENIED/);
});

test('Task voice context reuses current and historical speaker opt-out checks',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  const voice=f.source('voice',{metadata:{kind:'voice',inputAccountId:other},readers:[actor,other]});
  f.store.claim(task.id,task.revision);f.store.bindContext(task.id,task.revision,[{key:voice.key,revision:voice.revision}]);
  let authorizations=0;f.authorize=async()=>{authorizations++;};await f.read(project,task);assert.equal(authorizations,1);
  const optOut=()=>f.store.recordConsent({guild:'guild',channel:'channel',actor:other,notice:'fixture',granted:false,interactionId:'100000000000000001'});
  f.authorize=async()=>optOut();await assert.rejects(f.read(project,task),/PROJECT_VOICE_SCOPE_REVOKED/);
  f.authorize=async()=>{};await assert.rejects(f.read(project,task),/PROJECT_VOICE_SCOPE_REVOKED/);
  f.store.ingest({...voice,revision:2,metadata:{kind:'text'}});await assert.rejects(f.read(project,task),/PROJECT_VOICE_SCOPE_REVOKED/);
});

test('access epoch, configured operation and trusted surface remain binding during Task reads',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.authorize=async()=>f.bumpAccess();await assert.rejects(f.read(project,task),/PROJECT_ACCESS_CHANGED/);
  f.authorize=async()=>{};f.policy.projects.operations=f.policy.projects.operations.filter(op=>op!=='read_task');await assert.rejects(f.read(project,task),/PROJECT_OPERATION_NOT_ALLOWED/);
  f.policy=structuredClone(f.config);let allowed=true,reads=0;f.reader=async()=>{if(++reads===2)allowed=false;return f.policy;};
  await assert.rejects(f.hub.handle({actor,operation:'read_task',project_id:project.project.project_id,task_id:task.id},{assertScope:()=>assert.equal(allowed,true,'SURFACE_REVOKED')}),/SURFACE_REVOKED/);
});

test('restart preserves associations while existing owner recovery changes queued/running states',async t=>{
  const f=await fixture(t),queued=f.task('queued'),running=f.task('running');let project=await f.hub.handle(f.link(await f.create(),queued));
  project=await f.hub.handle(f.link(project,running));f.store.claim(running.id,running.revision);f.restart();
  assert.equal((await f.read(project,queued)).owner_state,'paused');const observed=await f.read(project,running);assert.equal(observed.owner_state,'uncertain');assert.equal(observed.resolution,'observed');assert.equal(observed.result_metadata.availability,'unavailable');
  assert.equal(f.store.statement('SELECT COUNT(*) AS n FROM tasks').get().n,2);
});

test('link races and altered idempotency requests cannot overwrite current Project',async t=>{
  const f=await fixture(t),project=await f.create(),task=f.task('task'),input=f.link(project,task);
  const twins=await Promise.all([f.hub.handle(input),f.hub.handle(input)]);assert.equal(twins[0].project_digest,twins[1].project_digest);
  await assert.rejects(f.hub.handle({...input,reason:'異なるpayload'}),/PROJECT_REQUEST_CONFLICT/);
  await assert.rejects(f.hub.handle(f.link(project,f.task('other'))),/PROJECT_REVISION_STALE/);
});

test('Task source/result budgets refuse oversized observations without truncating truth',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  const original=f.store.statement('SELECT body FROM tasks WHERE id=?').get(task.id).body,body=JSON.parse(original);
  body.contextSources=Array.from({length:33},()=>({key:task.source_key,revision:1}));f.store.statement('UPDATE tasks SET body=? WHERE id=?').run(JSON.stringify(body),task.id);await assert.rejects(f.read(project,task),/PROJECT_TASK_SOURCE_LIMIT/);
  body.contextSources=[];body.request='x'.repeat(262144);f.store.statement('UPDATE tasks SET body=? WHERE id=?').run(JSON.stringify(body),task.id);await assert.rejects(f.read(project,task),/PROJECT_TASK_SIZE_LIMIT/);
  f.store.statement('UPDATE tasks SET body=? WHERE id=?').run(original,task.id);
  f.store.claim(task.id,task.revision);f.store.finish(task.id,task.revision,{state:'needs_review',artifacts:Array.from({length:33},()=>({})),validations:[]});await assert.rejects(f.read(project,task),/PROJECT_TASK_RESULT_LIMIT/);
});

test('aggregate current and historical Task Source bytes have a finite read budget',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  const contexts=['large-1','large-2'].map(id=>f.source(id,{text:'あ'.repeat(400000)}));
  f.store.claim(task.id,task.revision);f.store.bindContext(task.id,task.revision,contexts.map(({key,revision})=>({key,revision})));
  await assert.rejects(f.read(project,task),/PROJECT_TASK_SOURCE_SIZE_LIMIT/);
});

test('contradictory check reports are not labeled as a reported pass',async t=>{
  const f=await fixture(t),task=f.task('task'),project=await f.hub.handle(f.link(await f.create(),task));
  f.store.claim(task.id,task.revision);f.store.finish(task.id,task.revision,{state:'needs_review',artifacts:[],validations:[{status:'failed',exitCode:0}]});
  assert.equal((await f.read(project,task)).result_metadata.checks,'reported_failure');
});

test('v2 adapters stay distinct and strictly bounded while v1 remains unchanged',async t=>{
  const f=await fixture(t),project=(await f.create()).project,task=f.task('task'),local={adapter:'discord_local_task_v1',task_id:task.id,revision:1};
  assert.deepEqual(validateProject({...project,version:2,task_refs:[local]}).task_refs,[local]);
  for(const ref of [{...local,context_digest:'0'.repeat(64)},{...local,owner_ref:'arbitrary'},{...local,adapter:'unknown'}])assert.throws(()=>validateProject({...project,version:2,task_refs:[ref]}),/PROJECT_TASK_/);
  assert.throws(()=>validateProject({...project,task_refs:[local]}),/PROJECT_TASK_INVALID/);assert.throws(()=>validateProject({...project,version:2,task_refs:[local,local]}),/PROJECT_TASK_DUPLICATE/);
  assert.throws(()=>validateProject({...project,version:2,task_refs:Array.from({length:51},()=>local)}),/PROJECT_TASK_LIMIT/);
});
