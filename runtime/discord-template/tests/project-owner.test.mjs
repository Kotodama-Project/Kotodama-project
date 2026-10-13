import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {ProjectHub} from '../src/project-hub.mjs';
import {validateProject,validateBrief,inspectChange,sourceReference} from '../src/project-contract.mjs';
import {digest} from '../src/common.mjs';

const actor='100000000000000002',other='100000000000000009';
const brief=(extra={})=>({outcome:'原意を失わず仕事を進める 🧵',in_scope:['原文と訂正'],out_of_scope:['自動公開'],constraints:['原文を保持する'],acceptance:['訂正理由を辿れる'],unknowns:[],...extra});
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-'));let store=new Store(root);
  const config={installation:'fixture',dataDir:root,owner:{kind:'local'},worker:{workspace:root},
    discord:{guildId:'guild',operators:[actor,other],textChannelIds:['channel','other-channel'],resultChannelId:'channel'},projects:{operations:['read','create','inspect','correct']}};
  let policy=structuredClone(config),authorize=async()=>{},active=true,epoch=0,reader=async()=>policy;
  const build=()=>new ProjectHub({store,config,policy:()=>policy,readConfig:()=>reader(),authorizeSource:(...args)=>authorize(...args),assertActive:()=>assert.equal(active,true,'RUNTIME_STOPPING'),accessEpoch:()=>epoch});let hub=build();
  const ingest=(id,extra={})=>{const value={provider:'discord',guildId:'guild',channelId:'channel',sourceId:id,actorId:actor,revision:1,readers:[actor],text:`依頼 ${id}`,final:true,...extra};const result=store.ingest(value);return {key:result.key,revision:value.revision};};
  const source=ingest('original');
  t.after(async()=>{store.close();await rm(root,{recursive:true,force:true});});
  return {root,config,source,ingest,get store(){return store;},get hub(){return hub;},get policy(){return policy;},set policy(value){policy=value;},set authorize(value){authorize=value;},set readConfig(value){reader=value;},bumpAccess(){epoch++;},
    restart(){store.close();store=new Store(root);hub=build();},stop(){active=false;},
    create:(extra={})=>hub.handle({actor,operation:'create',request_id:'create-1',name:'言霊 Project',source,brief:brief(),...extra})};
}
const read=project=>({actor,operation:'read',project_id:project.project_id});
const change=(view,source,extra={})=>({actor,operation:'correct',request_id:'correct-1',project_id:view.project.project_id,expected_revision:view.project.revision,
  base_digest:view.project_digest,source,reason:'利用者による要件の訂正',brief:brief({outcome:'訂正済みの成果',constraints:[]}),...extra});
const count=(store,table)=>store.statement(`SELECT COUNT(*) AS n FROM ${table}`).get().n;

test('create persists immutable origin, version and event in existing Store without a Source or Task write',async t=>{
  const f=await fixture(t),sources=count(f.store,'source_versions'),view=await f.create();
  assert.equal(view.project.original_ref,sourceReference(f.source));assert.equal(view.project.owner_ref,'ref/project-owner/fixture');
  assert.match(view.project.project_id,/^ref\/project\/[0-9a-f-]{36}$/);assert.equal(view.project.revision,1);assert.deepEqual(view.project.task_refs,[]);
  assert.equal(view.project_digest,digest(view.project));assert.equal(view.snapshot,'current');assert.equal(view.execution_authorized,false);assert.equal(view.task_state_changed,false);
  assert.equal(count(f.store,'tasks'),0);assert.equal(count(f.store,'source_versions'),sources);assert.equal(count(f.store,'project_versions'),1);
  const event=f.store.statement("SELECT body FROM events WHERE type='project.created'").get();assert.equal(JSON.parse(event.body).project_digest,view.project_digest);
  f.restart();const {replay,saved_revision,...expectedRead}=view;
  assert.deepEqual(await f.hub.handle(read(view.project)),expectedRead);
});

test('inspection is read-only and correction freezes original plus every prior version',async t=>{
  const f=await fixture(t),initial=await f.create(),source=f.ingest('correction'),input=change(initial,source),before=f.store.statement('SELECT * FROM project_versions').all();
  const {request_id,...inspection}=input,preview=await f.hub.handle({...inspection,operation:'inspect'});
  assert.equal(preview.applied,false);assert.deepEqual(preview.removed_requirements,{constraints:['原文を保持する'],acceptance:[]});
  assert.deepEqual(f.store.statement('SELECT * FROM project_versions').all(),before);
  const corrected=await f.hub.handle(input);assert.equal(corrected.project.revision,2);assert.equal(corrected.project.original_ref,initial.project.original_ref);
  assert.deepEqual(JSON.parse(f.store.statement('SELECT body FROM project_versions WHERE revision=1').get().body),initial.project);
  assert.equal(f.store.statement('SELECT previous_digest FROM project_versions WHERE revision=2').get().previous_digest,initial.project_digest);
  assert.equal(count(f.store,'tasks'),0);assert.equal(count(f.store,'project_versions'),2);
  const event=JSON.parse(f.store.statement("SELECT body FROM events WHERE type='project.corrected'").get().body);
  assert.deepEqual(event.removed_requirements,preview.removed_requirements);assert.equal(event.reason,input.reason);
});

test('replay survives restart and identifies the saved revision rather than claiming latest',async t=>{
  const f=await fixture(t),initial=await f.create(),input=change(initial,f.ingest('correction'));
  const corrected=await f.hub.handle(input);f.restart();const createReplay=await f.create(),correctReplay=await f.hub.handle(input);
  assert.equal(createReplay.replay,true);assert.equal(createReplay.snapshot,'saved_revision');assert.equal(createReplay.saved_revision,1);assert.equal(createReplay.current_revision,2);
  assert.equal(correctReplay.project_digest,corrected.project_digest);assert.equal(correctReplay.replay,true);assert.equal(count(f.store,'project_versions'),2);
  await assert.rejects(f.create({name:'同じkeyで違う要求'}),/PROJECT_REQUEST_CONFLICT/);
  await assert.rejects(f.hub.handle({...input,request_id:'create-1'}),/PROJECT_REQUEST_CONFLICT/);
});

test('stale revision, equal-revision altered digest, and empty change never mutate',async t=>{
  const f=await fixture(t),initial=await f.create(),input=change(initial,f.ingest('correction'));
  await assert.rejects(f.hub.handle({...input,base_digest:'0'.repeat(64)}),/PROJECT_BASE_MISMATCH/);
  await assert.rejects(f.hub.handle({...input,brief:initial.project.brief}),/PROJECT_CHANGE_EMPTY/);
  await f.hub.handle(input);await assert.rejects(f.hub.handle({...input,request_id:'stale-request'}),/PROJECT_REVISION_STALE/);
  assert.equal(count(f.store,'project_versions'),2);
});

test('actor isolation and original access revocation apply to read and cached replay',async t=>{
  const f=await fixture(t),initial=await f.create();await assert.rejects(f.hub.handle({...read(initial.project),actor:other}),/PROJECT_NOT_FOUND/);
  const original=f.store.source(f.source.key,actor);f.store.ingest({...original,revision:2,readers:[other]});
  await assert.rejects(f.hub.handle(read(initial.project)),/SOURCE_ACCESS_DENIED/);await assert.rejects(f.create(),/SOURCE_ACCESS_DENIED/);
});

test('source corrections preserve historical origin, report freshness, and reject stale new commands',async t=>{
  const f=await fixture(t),initial=await f.create(),original=f.store.source(f.source.key,actor);f.store.ingest({...original,revision:2,text:'出典の訂正'});
  const observed=await f.hub.handle(read(initial.project));assert.equal(observed.project.original_ref,initial.project.original_ref);
  assert.deepEqual(observed.source_refs,[{...f.source,current_revision:2,freshness:'superseded'}]);
  await assert.rejects(f.create({request_id:'new-stale-create'}),/SOURCE_CHANGED/);assert.equal((await f.create()).replay,true);
  const updated=await f.hub.handle(change(initial,{key:f.source.key,revision:2}));assert.equal(updated.project.original_ref,initial.project.original_ref);assert.equal(updated.source_refs.length,2);
});

test('current access cannot grant access to a historical source revision',async t=>{
  const f=await fixture(t),hidden=f.ingest('hidden',{readers:[other]}),source=f.store.sourceInternal(hidden.key);f.store.ingest({...source,revision:2,readers:[actor]});
  await assert.rejects(f.create({source:hidden}),/SOURCE_ACCESS_DENIED/);assert.equal(count(f.store,'projects'),0);
});

test('voice and pooled rooms remain scoped and explicit opt-out blocks every Project operation',async t=>{
  for(const pooled of [false,true]){
    const f=await fixture(t),channelId=pooled?'pool-room':'voice-room';
    if(pooled)f.config.voicePool={rooms:[{channelId}]};else f.config.discord.voiceChannelId=channelId;
    f.policy=structuredClone(f.config);
    const source=f.ingest('spoken',{channelId,metadata:{kind:'voice',inputAccountId:other}}),created=await f.create({source});
    const input=change(created,source),{request_id,...inspection}=input;
    // A current text revision must not bypass the original voice dependency.
    f.store.ingest({...f.store.source(source.key,actor),revision:2,metadata:{kind:'text'}});
    f.store.recordConsent({guild:'guild',channel:channelId,actor:other,notice:'fixture',granted:false,interactionId:'100000000000000101'});
    for(const command of [read(created.project),{...inspection,operation:'inspect'},input])await assert.rejects(f.hub.handle(command),/PROJECT_VOICE_SCOPE_REVOKED/);
    await assert.rejects(f.create({source}),/PROJECT_VOICE_SCOPE_REVOKED/);
    assert.equal(count(f.store,'project_versions'),1);
  }
});

test('voice opt-out during authorization and removal of a configured room prevent saving',async t=>{
  const f=await fixture(t);f.config.discord.voiceChannelId='voice-room';f.policy=structuredClone(f.config);
  const source=f.ingest('spoken',{channelId:'voice-room',metadata:{kind:'voice'}});
  f.authorize=async()=>{f.store.recordConsent({guild:'guild',channel:'voice-room',actor,notice:'fixture',granted:false,interactionId:'100000000000000102'});};
  await assert.rejects(f.create({source}),/PROJECT_VOICE_SCOPE_REVOKED/);assert.equal(count(f.store,'projects'),0);
  f.store.recordConsent({guild:'guild',channel:'voice-room',actor,notice:'fixture',granted:true,interactionId:'100000000000000103'});
  f.authorize=async()=>{delete f.policy.discord.voiceChannelId;};
  await assert.rejects(f.create({source}),/PROJECT_SOURCE_SCOPE_MISMATCH/);assert.equal(count(f.store,'projects'),0);
});

test('a Project with 32 source dependencies authorizes its actor and room only once per operation',async t=>{
  const f=await fixture(t);let calls=0;f.authorize=async()=>{calls++;};let current=await f.create();
  for(let i=1;i<32;i++){
    calls=0;current=await f.hub.handle(change(current,f.ingest(`correction-${i}`),{request_id:`correct-${i}`,brief:brief({outcome:`成果 ${i}`})}));
    assert.equal(calls,1);
  }
  calls=0;assert.equal((await f.hub.handle(read(current.project))).source_refs.length,32);assert.equal(calls,1);
  f.store.ingest({...f.store.source(f.source.key,actor),revision:2,withdrawn:true});
  await assert.rejects(f.hub.handle(read(current.project)),/SOURCE_ACCESS_DENIED/);
});

test('original and every inherited correction remain access dependencies',async t=>{
  const f=await fixture(t),initial=await f.create(),source=f.ingest('correction'),corrected=await f.hub.handle(change(initial,source));
  const newer=await f.hub.handle(change(corrected,f.ingest('later'),{request_id:'correct-2',brief:brief({outcome:'後の成果'})}));
  f.store.ingest({...f.store.source(source.key,actor),revision:2,withdrawn:true});
  await assert.rejects(f.hub.handle(read(newer.project)),/SOURCE_ACCESS_DENIED/);await assert.rejects(f.create(),/SOURCE_ACCESS_DENIED/);
});

test('correction cannot cross room, change owner, attach Tasks, or import a foreign actor source',async t=>{
  const f=await fixture(t),initial=await f.create();
  await assert.rejects(f.hub.handle(change(initial,f.ingest('other-room',{channelId:'other-channel'}))),/PROJECT_SOURCE_SCOPE_MISMATCH/);
  await assert.rejects(f.create({source:f.ingest('other-actor',{actorId:other,readers:[actor,other]}),request_id:'other-source'}),/PROJECT_SOURCE_ACTOR_MISMATCH/);
  await assert.rejects(f.create({owner_ref:'chosen-owner'}),/PROJECT_REQUEST_INVALID/);await assert.rejects(f.create({task_refs:[]}),/PROJECT_REQUEST_INVALID/);
});

test('operation grants, operator and installation/remote selection are rechecked before commit',async t=>{
  const f=await fixture(t);f.policy.projects.operations=[];await assert.rejects(f.create(),/PROJECT_OPERATION_NOT_ALLOWED/);
  f.policy=structuredClone(f.config);f.authorize=async()=>{f.policy.owner={kind:'remote',url:'https://invalid.example',tokenEnv:'FIXTURE'};};
  await assert.rejects(f.create(),/PROJECT_LOCAL_OWNER_REQUIRED/);assert.equal(count(f.store,'projects'),0);
  f.policy=structuredClone(f.config);f.authorize=async()=>{f.policy.dataDir+='-changed';};await assert.rejects(f.create(),/PROJECT_INSTALLATION_CHANGED/);
  f.policy=structuredClone(f.config);f.authorize=async()=>{f.policy.discord.operators=[other];};await assert.rejects(f.create(),/OPERATOR_REQUIRED/);
  assert.equal(count(f.store,'projects'),0);
});

test('late authorization after cancellation or source change cannot commit',async t=>{
  const f=await fixture(t),controller=new AbortController();f.authorize=async()=>controller.abort(new Error('FIXTURE_TIMEOUT'));
  await assert.rejects(f.hub.handle({actor,operation:'create',request_id:'cancelled',name:'候補',source:f.source,brief:brief()},{signal:controller.signal}),/FIXTURE_TIMEOUT/);
  f.authorize=async()=>{const original=f.store.source(f.source.key,actor);f.store.ingest({...original,revision:original.revision+1,text:'同時訂正'});};
  await assert.rejects(f.create(),/PROJECT_SOURCE_CHANGED/);assert.equal(count(f.store,'projects'),0);
});

test('Discord access changes during the final policy read refuse the stale observation',async t=>{
  const f=await fixture(t);let reads=0;f.readConfig=async()=>{if(++reads===2)f.bumpAccess();return f.policy;};
  await assert.rejects(f.create(),/PROJECT_ACCESS_CHANGED/);assert.equal(count(f.store,'projects'),0);
});

test('two asynchronous corrections to one base cannot overwrite each other',async t=>{
  const f=await fixture(t),initial=await f.create(),input=change(initial,f.ingest('correction'));
  let release;const held=new Promise(resolve=>{release=resolve;}),started=[];f.authorize=async()=>{started.push(true);await held;};
  const first=f.hub.handle(input),second=f.hub.handle({...input,request_id:'competing',brief:brief({outcome:'別の訂正'})});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(started.length,2);release();
  const outcomes=await Promise.allSettled([first,second]);assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);
  assert.match(outcomes.find(o=>o.status==='rejected').reason.message,/PROJECT_CHANGED/);assert.equal(count(f.store,'project_versions'),2);
});

test('simultaneous identical delivery returns one stable Project and one creation event',async t=>{
  const f=await fixture(t),views=await Promise.all([f.create(),f.create()]);
  assert.equal(views[0].project.project_id,views[1].project.project_id);assert.deepEqual(views.map(v=>v.replay).sort(),[false,true]);
  assert.equal(count(f.store,'projects'),1);assert.equal(count(f.store,'project_versions'),1);
  assert.equal(f.store.statement("SELECT COUNT(*) AS n FROM events WHERE type='project.created'").get().n,1);
});

test('event failure rolls back project, version, and idempotency receipt together',async t=>{
  const f=await fixture(t),event=f.store.event;f.store.event=()=>{throw new Error('FIXTURE_EVENT_FAILED');};
  await assert.rejects(f.create(),/FIXTURE_EVENT_FAILED/);assert.equal(count(f.store,'projects'),0);assert.equal(count(f.store,'project_versions'),0);assert.equal(count(f.store,'project_requests'),0);
  f.store.event=event;assert.equal((await f.create()).saved_revision,1);
});

test('bounded history stops without erasing originals and receipts',async t=>{
  const f=await fixture(t);let latest=await f.create();
  for(let i=2;i<=32;i++)latest=await f.hub.handle(change(latest,f.source,{request_id:`revision-${i}`,brief:brief({outcome:`成果 ${i}`})}));
  await assert.rejects(f.hub.handle(change(latest,f.source,{request_id:'overflow'})),/PROJECT_VERSION_LIMIT/);
  assert.equal(count(f.store,'project_versions'),32);assert.equal((await f.create()).saved_revision,1);
});

test('v1 snapshots preserve Unicode codepoint limits and match the repository Python contract',async t=>{
  const f=await fixture(t),view=await f.create({name:'🧵'.repeat(200),brief:brief({outcome:'🧵'.repeat(4000),unknowns:['改行\nタブ\tは保持']})});
  assert.deepEqual(validateProject(view.project),view.project);assert.throws(()=>validateBrief(brief({outcome:'🧵'.repeat(4001)})),/PROJECT_OUTCOME_INVALID/);
  for(const invalid of ['\ud800','\0','\u0085\u001c'])assert.throws(()=>validateBrief(brief({outcome:invalid})),/PROJECT_OUTCOME_INVALID/);
  const proposal={version:1,project_id:view.project.project_id,expected_revision:1,base_digest:view.project_digest,reason:'訂正 🧵',source_ref:sourceReference(f.source),brief:brief()};
  const repo=fileURLToPath(new URL('../../..',import.meta.url)),python=process.env.KOTODAMA_TEST_PYTHON??(process.platform==='win32'?'python':'python3');
  // A copied standalone template has no repository Python tools. In the full
  // repository this always runs; an unavailable/broken Python command fails.
  await t.test('Python v1 golden parity',{skip:!existsSync(path.join(repo,'tools/project_hub.py'))},()=>{
    const result=spawnSync(python,['-B','-c','import json,sys; sys.path.insert(0,"tools"); import project_hub as p; v=json.load(sys.stdin); print(json.dumps({"project":p.validate_project(v["project"]),"digest":p.digest(v["project"]),"candidate":p.inspect_change(v["project"],v["proposal"])},ensure_ascii=False))'],{cwd:repo,input:JSON.stringify({project:view.project,proposal}),encoding:'utf8',timeout:10000,env:{...process.env,PYTHONUTF8:'1'}});
    assert.equal(result.status,0,result.stderr);const expected=JSON.parse(result.stdout);assert.equal(expected.digest,view.project_digest);assert.deepEqual(expected.project,view.project);assert.deepEqual(expected.candidate,inspectChange(view.project,proposal));
  });
});
