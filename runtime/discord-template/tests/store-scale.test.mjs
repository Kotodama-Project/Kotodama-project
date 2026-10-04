import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {exampleConfig} from '../src/config.mjs';
import {sourceIdentity,sourceFingerprint} from '../src/common.mjs';

const actor='100000000000000002',other='100000000000000009';
const source=(id,extra={})=>({provider:'discord',guildId:'g',channelId:'c',sourceId:id,actorId:actor,revision:1,readers:[actor],text:id,final:true,...extra});
const intent=(extra={})=>({title:'資料',request:'資料を整理',action:'research',...extra});
async function fixture(t,{legacy=false}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-store-scale-'));
  let store=legacy?null:new Store(root);
  t.after(async()=>{store?.close();await rm(root,{recursive:true,force:true});});
  return {root,get store(){return store;},open(){store=new Store(root);return store;}};
}
function decodeCount(fn){const parse=JSON.parse;let count=0;JSON.parse=(...args)=>{count++;return parse(...args);};try{return {value:fn(),count};}finally{JSON.parse=parse;}}
function latest(sources,limit){return sources.sort((a,b)=>(Date.parse(b.metadata?.createdAt??'')||0)-(Date.parse(a.metadata?.createdAt??'')||0)||b.revision-a.revision||b.key.localeCompare(a.key)).slice(0,limit);}

test('legacy migration preserves original bytes, binds context, and never reparses history on reopening',async t=>{
  const f=await fixture(t,{legacy:true}),db=new DatabaseSync(path.join(f.root,'kotodama.sqlite'));
  db.exec(`CREATE TABLE sources(key TEXT PRIMARY KEY,revision INTEGER NOT NULL,fingerprint TEXT NOT NULL,body TEXT NOT NULL);
    CREATE TABLE source_versions(key TEXT NOT NULL,revision INTEGER NOT NULL,fingerprint TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(key,revision));
    CREATE TABLE tasks(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,source_key TEXT NOT NULL,source_revision INTEGER NOT NULL,room TEXT NOT NULL,actor TEXT NOT NULL,revision INTEGER NOT NULL,state TEXT NOT NULL,body TEXT NOT NULL,result TEXT);
    CREATE TABLE usage(day TEXT PRIMARY KEY,reserved_ms INTEGER NOT NULL);
    CREATE TABLE analysis_usage(day TEXT PRIMARY KEY,reserved INTEGER NOT NULL CHECK(reserved>=0));`);
  const s=source('legacy',{readers:[actor,actor],metadata:{createdAt:'2026-01-01',archiveSessionRefs:['old']}}),key=sourceIdentity(s),body=JSON.stringify({...s,key}),fingerprint=sourceFingerprint(s);
  db.prepare('INSERT INTO sources VALUES(?,?,?,?)').run(key,1,fingerprint,body);
  db.prepare('INSERT INTO source_versions VALUES(?,?,?,?)').run(key,1,fingerprint,body);
  const taskBody=JSON.stringify({id:'legacy-task',source_key:key,source_revision:1,room:'discord:g:c',actor,title:'資料',request:'整理',action:'research',contextSources:[{key,revision:1}]});
  db.prepare('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,NULL)').run('legacy-task','request',key,1,'discord:g:c',actor,1,'running',taskBody);
  db.exec("INSERT INTO usage VALUES('2026-01-01',900); INSERT INTO analysis_usage VALUES('2026-01-01',3);");db.close();
  const store=f.open();
  assert.equal(store.db.prepare('SELECT body FROM sources').get().body,body);
  assert.equal(store.db.prepare('SELECT body FROM source_versions').get().body,body);
  assert.equal(store.db.prepare('SELECT body FROM tasks').get().body,taskBody);
  assert.equal(store.sources(actor).length,1);
  assert.equal(store.db.prepare('SELECT count(*) n FROM source_readers').get().n,1);
  assert.equal(store.db.prepare('SELECT source_key FROM task_source_bindings').get().source_key,key);
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='audio'").get().total,900);
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='analysis'").get().total,3);
  const reopened=decodeCount(()=>new Store(f.root));assert.equal(reopened.count,0);reopened.value.close();
  store.ingest({...s,revision:2,text:'訂正'});
  assert.equal(store.taskInternal('legacy-task').state,'stale');
  assert.equal(store.db.prepare('SELECT body FROM source_versions WHERE revision=1').get().body,body);
});

test('current reader projections follow corrections while duplicate, stale and conflicting revisions do not mutate them',async t=>{
  const {store}=await fixture(t),s=source('audience',{metadata:{archiveSessionRefs:['one']}}),key=store.ingest(s).key;
  const before=JSON.stringify(store.db.prepare('SELECT * FROM source_readers').all());
  assert.equal(store.ingest(s).state,'duplicate');assert.equal(store.ingest({...s,revision:0}).state,'stale');
  assert.throws(()=>store.ingest({...s,readers:[other]}),/SOURCE_REVISION_CONFLICT/);
  assert.equal(JSON.stringify(store.db.prepare('SELECT * FROM source_readers').all()),before);
  store.ingest({...s,revision:2,readers:[other],metadata:{archiveSessionRefs:['two']}});
  assert.equal(store.sources(actor).length,0);assert.deepEqual(store.sources(other).map(s=>s.key),[key]);
  assert.deepEqual(store.db.prepare('SELECT session_id FROM source_archive_refs').all().map(r=>r.session_id),['two']);
  store.ingest({...s,revision:3,readers:[other],withdrawn:true});
  assert.equal(store.sources(other).length,0);assert.equal(store.db.prepare('SELECT count(*) n FROM source_versions').get().n,3);
});

test('re-upgrade rebuilds dirty projections after legacy writes and deletions, then skips clean history',async t=>{
  const f=await fixture(t),store=f.store,make=id=>{const key=store.ingest(source(id)).key;return store.source(key,actor);};
  const request=make('request'),a=make('a'),b=make('b'),removed=make('removed');
  const task=store.createTask(request,intent({contextSources:[{key:a.key,revision:1}]}));
  const deletedTask=store.createTask(request,intent({key:'delete',contextSources:[{key:removed.key,revision:1}]}));
  store.reserveAudio(100,1,'2026-01-01',1);store.close();
  // An older writer knows only the original tables. Its existing triggers mark
  // the projections dirty even if that writer does not enable foreign keys.
  const legacy=new DatabaseSync(path.join(f.root,'kotodama.sqlite'));
  const corrected={...a,revision:2,readers:[other]},body=JSON.stringify(corrected);
  legacy.prepare('UPDATE sources SET revision=?,fingerprint=?,body=? WHERE key=?').run(2,sourceFingerprint(corrected),body,a.key);
  const taskBody=JSON.stringify({...task,contextSources:[{key:b.key,revision:1}]});
  legacy.prepare('UPDATE tasks SET body=? WHERE id=?').run(taskBody,task.id);
  legacy.prepare('DELETE FROM sources WHERE key=?').run(removed.key);legacy.prepare('DELETE FROM tasks WHERE id=?').run(deletedTask.id);
  legacy.exec("INSERT INTO usage VALUES('2026-01-02',100);");
  assert.equal(legacy.prepare('SELECT count(*) n FROM store_migrations').get().n,0);legacy.close();
  const opened=decodeCount(()=>f.open());assert(opened.count>0);
  assert(!f.store.sources(actor).some(s=>[a.key,removed.key].includes(s.key)));
  assert.equal(f.store.sources(other)[0].key,a.key);
  assert.equal(f.store.db.prepare('SELECT source_key FROM task_source_bindings WHERE task_id=?').get(task.id).source_key,b.key);
  assert.equal(f.store.db.prepare('SELECT count(*) n FROM task_source_bindings WHERE task_id=?').get(deletedTask.id).n,0);
  assert.equal(f.store.db.prepare('SELECT body FROM sources WHERE key=?').get(a.key).body,body);
  assert.equal(f.store.db.prepare('SELECT body FROM tasks WHERE id=?').get(task.id).body,taskBody);
  assert.equal(f.store.db.prepare("SELECT total FROM usage_totals WHERE name='audio'").get().total,200);
  const clean=decodeCount(()=>new Store(f.root));assert.equal(clean.count,0);clean.value.close();
});

test('context preserves room, access, ordering and archive replacement before applying the limit',async t=>{
  const {store}=await fixture(t),put=(id,extra)=>{const key=store.ingest(source(id,extra)).key;return store.sourceInternal(key);};
  const fast=put('fast',{metadata:{createdAt:'2026-01-09',archiveSessionRefs:['one']}});
  const partial=put('partial',{metadata:{createdAt:'2026-01-08',archiveSessionRefs:['one','two']}});
  put('hidden-archive',{readers:[other],metadata:{kind:'archived_voice',sessionId:'one',createdAt:'2026-01-01'}});
  const options={guildId:'g',channelId:'c',limit:2};
  assert.deepEqual(store.contextSources(actor,options).map(s=>s.key),[fast.key,partial.key]);
  const archive=put('archive',{provider:'file',metadata:{kind:'archived_voice',sessionId:'one',createdAt:'2026-01-01'}});
  const older=put('older',{metadata:{createdAt:'2026-01-02'}});
  put('unreadable-new',{readers:[other],metadata:{createdAt:'2026-01-12'}});
  put('another-channel',{channelId:'different',metadata:{createdAt:'2026-01-12'}});
  assert.deepEqual(store.contextSources(actor,options).map(s=>s.key),[partial.key,older.key]);
  put('archive-two',{metadata:{kind:'archived_voice',sessionId:'two',createdAt:'2026-01-01'}});
  assert(!store.contextSources(actor,{...options,limit:20}).some(s=>[fast.key,partial.key].includes(s.key)));
  store.ingest({...archive,revision:2,withdrawn:true});
  assert.deepEqual(store.contextSources(actor,options).map(s=>s.key),[fast.key,partial.key]);
  assert.equal(store.db.prepare('SELECT count(*) n FROM sources').get().n,8);
});

test('indexed recent source reads preserve revision ordering and chronological timestamp/key ties',async t=>{
  const {store}=await fixture(t),sources=[];
  for(const [id,revision,createdAt,sourceActor] of [['invalid',8,'invalid',actor],['missing',7,undefined,actor],['date-a',2,'2026-01-01',actor],['date-b',2,'2026-01-01',actor],['newer',1,'2026-01-02',actor],['different-speaker',100,'2026-01-03',other]]){
    const key=store.ingest(source(id,{revision,actorId:sourceActor,metadata:{createdAt}})).key;sources.push(store.sourceInternal(key));
  }
  const options={guildId:'g',channelId:'c',limit:4};
  assert.deepEqual(store.recentSources(actor,options).map(s=>s.key),latest([...sources],4).map(s=>s.key));
  const mine=sources.filter(s=>s.actorId===actor).sort((a,b)=>b.revision-a.revision||b.key.localeCompare(a.key)).slice(0,3);
  assert.deepEqual(store.recentSources(actor,{...options,sourceActor:actor,order:'revision',limit:3}).map(s=>s.key),mine.map(s=>s.key));
  assert.deepEqual(store.recentSources(actor,{...options,limit:0}),[]);
});

test('task bindings change atomically, remove superseded context, and preserve correction invalidation states',async t=>{
  const {store}=await fixture(t),make=id=>{const key=store.ingest(source(id)).key;return store.source(key,actor);},s=make('request'),a=make('a'),b=make('b');
  const task=store.createTask(s,intent({contextSources:[{key:a.key,revision:a.revision}]}));store.claim(task.id,task.revision);
  assert.throws(()=>store.bindContext(task.id,task.revision,[{key:b.key,revision:9}]),/CONTEXT_CHANGED/);
  assert.equal(store.db.prepare('SELECT source_key FROM task_source_bindings WHERE task_id=?').get(task.id).source_key,a.key);
  store.bindContext(task.id,task.revision,[{key:b.key,revision:b.revision}]);
  assert.throws(()=>store.reviseTask(task.id,s,intent({contextSources:[{key:b.key,revision:9}]})),/CONTEXT_CHANGED/);
  assert.equal(store.task(task.id,actor).state,'running');assert.equal(store.task(task.id,actor).revision,task.revision);
  assert.equal(store.db.prepare('SELECT revision FROM task_source_bindings WHERE task_id=?').get(task.id).revision,1);
  const revised=store.reviseTask(task.id,s,intent({contextSources:[{key:b.key,revision:1}]}));
  store.ingest({...a,revision:2,text:'変更'});assert.equal(store.task(task.id,actor).state,'queued');
  store.ingest({...b,revision:2,text:'変更'});assert.equal(store.task(task.id,actor).state,'stale');
  assert.equal(store.task(task.id,actor).revision,revised.revision+1);
  const cancelled=store.createTask(s,intent({key:'cancelled',contextSources:[{key:a.key,revision:2}]}));store.cancel(cancelled.id,actor);
  const uncertain=store.createTask(s,intent({key:'uncertain',contextSources:[{key:a.key,revision:2}]}));store.claim(uncertain.id,1);store.cancel(uncertain.id,actor);store.confirmStop(uncertain.id,actor,false);
  store.ingest({...a,revision:3,text:'さらに変更'});
  assert.equal(store.taskInternal(cancelled.id).state,'cancelled');assert.equal(store.taskInternal(uncertain.id).state,'stale');
});

test('recent task context fills its limit after unreadable sources and superseded context, retaining creation order',async t=>{
  const {store}=await fixture(t),ids=[];
  for(let i=0;i<3;i++){const key=store.ingest(source('visible-'+i)).key;ids.push(store.createTask(store.source(key,actor),intent()).id);}
  for(let i=0;i<35;i++){const s=source('hidden-'+i),key=store.ingest(s).key;store.createTask(store.source(key,actor),intent());store.ingest({...s,revision:2,readers:[other]});}
  const elsewhere=source('other-room',{channelId:'elsewhere'}),key=store.ingest(elsewhere).key;store.createTask(store.source(key,actor),intent());
  assert.deepEqual(store.recentTasks(actor,{room:'discord:g:c',limit:2}).map(t=>t.id),ids.slice(-2).reverse());
  assert.deepEqual(store.recentTasks(actor,{room:'discord:g:c',limit:0}),[]);
  assert.equal(store.db.prepare('SELECT count(*) n FROM tasks').get().n,39);
});

test('cumulative budgets stay exact across rollback, updates, new connections and historical days',async t=>{
  const {store,root}=await fixture(t),limits={maxDailyAnalyses:10,maxTotalAnalyses:30};
  store.reserveAudio(900,1,'2026-01-01',1);store.reserveAnalysis(limits,'2026-01-01');
  assert.throws(()=>store.transaction(()=>{store.reserveAudio(100,1,'2026-01-02',1);store.reserveAnalysis(limits,'2026-01-02');throw Error('rollback');}),/rollback/);
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='audio'").get().total,900);
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='analysis'").get().total,1);
  const reopened=new Store(root);try{assert.throws(()=>reopened.reserveAudio(101,1,'2026-01-03',1),/AUDIO_TOTAL_BUDGET_EXHAUSTED/);reopened.reserveAudio(100,1,'2026-01-03',1);}finally{reopened.close();}
  store.db.exec("UPDATE analysis_usage SET reserved=5; DELETE FROM usage WHERE day='2026-01-01';");
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='analysis'").get().total,5);
  assert.equal(store.db.prepare("SELECT total FROM usage_totals WHERE name='audio'").get().total,100);
});

test('12,000 sources and 2,400 tasks decode only bounded model context and use indexed correction paths',async t=>{
  const {store,root}=await fixture(t),all=[];
  store.transaction(()=>{for(let i=0;i<12000;i++){
    const s=source('scale-'+i,{channelId:i%100===0?'c':'room-'+(i%100),readers:i%7===0?[other]:[actor],revision:i%9+1,text:'x'.repeat(80),metadata:{createdAt:new Date(Date.UTC(2026,0,1,0,0,i)).toISOString()}});
    const key=store.ingest(s).key;if(s.channelId==='c'&&s.readers.includes(actor))all.push({...s,key});
  }});
  const config=exampleConfig({workspace:root});config.analyzer.maxContextSources=12;config.analyzer.maxContextChars=500;
  const p=new Pipeline({store,config,analyzer:{},worker:{}}),current=source('current');current.key=sourceIdentity(current);
  const decoded=decodeCount(()=>p.context(current,actor));assert.equal(decoded.count,12);assert.equal(decoded.value.length,7);assert.equal(decoded.value.map(s=>s.text).join('').length,500);
  assert.deepEqual(decoded.value.map(s=>s.key),latest(all,12).slice(0,7).reverse().map(s=>s.key));
  const contextSql=[...store.statements.keys()].find(sql=>sql.startsWith('SELECT s.body FROM source_readers r')&&sql.includes('LIMIT ?'));
  const plan=store.db.prepare('EXPLAIN QUERY PLAN '+contextSql).all(actor,'g','c',current.key,current.key,12).map(r=>r.detail).join('\n');
  assert.match(plan,/SEARCH r USING (?:COVERING )?INDEX source_reader_history/);assert(!plan.includes('USE TEMP B-TREE FOR ORDER BY'));assert(!plan.includes('SCAN sources'));
  store.transaction(()=>{for(const row of store.db.prepare('SELECT key FROM source_readers WHERE actor=? LIMIT 2400').all(actor))store.createTask(store.source(row.key,actor),intent());});
  const s=store.source(all[0].key,actor);store.createTask(s,intent());
  const taskDecoded=decodeCount(()=>store.recentTasks(actor,{room:'discord:g:c',limit:1}));assert.equal(taskDecoded.value.length,1);assert.equal(taskDecoded.count,2);
  const taskSql=[...store.statements.keys()].find(sql=>sql.startsWith('SELECT t.id FROM tasks t')&&sql.includes('LIMIT ?'));
  const taskPlan=store.db.prepare('EXPLAIN QUERY PLAN '+taskSql).all(actor,'discord:g:c',1).map(r=>r.detail).join('\n');
  assert.match(taskPlan,/SEARCH t USING (?:COVERING )?INDEX tasks_actor_room/);assert(!taskPlan.includes('USE TEMP B-TREE FOR ORDER BY'));
  store.ingest({...s,revision:s.revision+1,text:'correction'});
  const invalidateSql=[...store.statements.keys()].find(sql=>sql.startsWith("UPDATE tasks SET state='stale'"));
  const correctionPlan=store.db.prepare('EXPLAIN QUERY PLAN '+invalidateSql).all(s.key,s.key).map(r=>r.detail).join('\n');
  assert.match(correctionPlan,/tasks_source/);assert.match(correctionPlan,/task_binding_source/);assert(!correctionPlan.includes('json_each'));
  assert.equal(store.db.prepare('SELECT count(*) n FROM sources').get().n,12000);
});
