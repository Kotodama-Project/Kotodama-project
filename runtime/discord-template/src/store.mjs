import {DatabaseSync} from 'node:sqlite';
import {mkdirSync} from 'node:fs';
import path from 'node:path';
import {check,digest,sourceIdentity,sourceFingerprint,uid} from './common.mjs';

export class Store {
  constructor(dataDir) {
    mkdirSync(dataDir,{recursive:true,mode:0o700});
    this.db=new DatabaseSync(path.join(dataDir,'kotodama.sqlite'));
    this.statements=new Map();
    try{
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS sources(key TEXT PRIMARY KEY, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS source_versions(key TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(key,revision));
      CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY, source_key TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS intent_versions(id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(id,revision));
      CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, source_key TEXT NOT NULL, source_revision INTEGER NOT NULL, room TEXT NOT NULL, actor TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL, result TEXT);
      CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, type TEXT NOT NULL, at TEXT NOT NULL, body TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS interaction_event_scope ON events(json_extract(body,'$.room'),json_extract(body,'$.actor'),seq DESC) WHERE type IN ('interaction.clarification_asked','interaction.clarification_closed');
      CREATE TABLE IF NOT EXISTS deliveries(key TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, message_id TEXT);
      CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, reserved_ms INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS analysis_usage(day TEXT PRIMARY KEY, reserved INTEGER NOT NULL CHECK(reserved>=0));
      CREATE TABLE IF NOT EXISTS voice_controls(guild TEXT NOT NULL,channel TEXT NOT NULL,suspension TEXT,PRIMARY KEY(guild,channel));
      CREATE TABLE IF NOT EXISTS voice_consents(guild TEXT NOT NULL,channel TEXT NOT NULL,actor TEXT NOT NULL,notice TEXT NOT NULL,granted INTEGER NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(guild,channel,actor));
      CREATE TABLE IF NOT EXISTS host_lock(name TEXT PRIMARY KEY, owner TEXT NOT NULL, pid INTEGER NOT NULL, created TEXT NOT NULL, domain TEXT);
    `);
    if(!this.statement('PRAGMA table_info(voice_consents)').all().some(c=>c.name==='interaction_id'))this.db.exec("ALTER TABLE voice_consents ADD COLUMN interaction_id TEXT NOT NULL DEFAULT '0'");
    if(!this.statement('PRAGMA table_info(host_lock)').all().some(c=>c.name==='domain'))this.db.exec('ALTER TABLE host_lock ADD COLUMN domain TEXT');
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS store_migrations(name TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS source_readers(actor TEXT NOT NULL,key TEXT NOT NULL REFERENCES sources(key) ON DELETE CASCADE,guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,room TEXT NOT NULL,source_actor TEXT,created_ms REAL NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(actor,key));
      CREATE INDEX IF NOT EXISTS source_reader_history ON source_readers(actor,guild_id,channel_id,created_ms DESC,revision DESC,key DESC);
      CREATE INDEX IF NOT EXISTS source_reader_actor_history ON source_readers(actor,guild_id,channel_id,source_actor,revision DESC,key DESC);
      CREATE INDEX IF NOT EXISTS source_reader_room_revision ON source_readers(actor,guild_id,channel_id,revision DESC,key DESC);
      CREATE INDEX IF NOT EXISTS source_reader_revision ON source_readers(actor,revision,key);
      CREATE INDEX IF NOT EXISTS source_reader_room ON source_readers(actor,room,revision,key);
      CREATE INDEX IF NOT EXISTS source_readers_key ON source_readers(key);
      CREATE TABLE IF NOT EXISTS source_archive_sessions(key TEXT NOT NULL REFERENCES sources(key) ON DELETE CASCADE,session_id TEXT NOT NULL,PRIMARY KEY(key,session_id));
      CREATE INDEX IF NOT EXISTS source_archive_session ON source_archive_sessions(session_id,key);
      CREATE TABLE IF NOT EXISTS source_archive_refs(key TEXT NOT NULL REFERENCES sources(key) ON DELETE CASCADE,session_id TEXT NOT NULL,PRIMARY KEY(key,session_id));
      CREATE TABLE IF NOT EXISTS task_source_bindings(task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,source_key TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(task_id,source_key));
      CREATE INDEX IF NOT EXISTS task_binding_source ON task_source_bindings(source_key,task_id);
      CREATE INDEX IF NOT EXISTS tasks_source ON tasks(source_key);
      CREATE INDEX IF NOT EXISTS tasks_actor ON tasks(actor);
      CREATE INDEX IF NOT EXISTS tasks_actor_room ON tasks(actor,room);
      CREATE INDEX IF NOT EXISTS tasks_state ON tasks(state);
      CREATE INDEX IF NOT EXISTS intents_source ON intents(source_key);
      CREATE TABLE IF NOT EXISTS usage_totals(name TEXT PRIMARY KEY,total INTEGER NOT NULL CHECK(total>=0));
    `);
    this.transaction(()=>{
      if(!this.statement('SELECT name FROM store_migrations WHERE name=?').get('indexed_history_v1')){
        // Only the current projections are backfilled; immutable history is untouched.
        this.db.exec('DELETE FROM source_readers; DELETE FROM source_archive_sessions; DELETE FROM source_archive_refs; DELETE FROM task_source_bindings;');
        for(const row of this.statement('SELECT key,body FROM sources').iterate())this.indexSource(JSON.parse(row.body),row.key);
        for(const row of this.statement('SELECT id,body FROM tasks').iterate())this.indexTaskBindings(row.id,JSON.parse(row.body).contextSources??[]);
        this.statement("INSERT INTO usage_totals VALUES('audio',(SELECT COALESCE(SUM(reserved_ms),0) FROM usage)) ON CONFLICT(name) DO UPDATE SET total=excluded.total").run();
        this.statement("INSERT INTO usage_totals VALUES('analysis',(SELECT COALESCE(SUM(reserved),0) FROM analysis_usage)) ON CONFLICT(name) DO UPDATE SET total=excluded.total").run();
        this.statement('INSERT INTO store_migrations VALUES(?)').run('indexed_history_v1');
      }
      this.db.exec(`
        CREATE TRIGGER IF NOT EXISTS usage_total_insert AFTER INSERT ON usage BEGIN UPDATE usage_totals SET total=total+NEW.reserved_ms WHERE name='audio'; END;
        CREATE TRIGGER IF NOT EXISTS usage_total_update AFTER UPDATE OF reserved_ms ON usage BEGIN UPDATE usage_totals SET total=total+NEW.reserved_ms-OLD.reserved_ms WHERE name='audio'; END;
        CREATE TRIGGER IF NOT EXISTS usage_total_delete AFTER DELETE ON usage BEGIN UPDATE usage_totals SET total=total-OLD.reserved_ms WHERE name='audio'; END;
        CREATE TRIGGER IF NOT EXISTS analysis_total_insert AFTER INSERT ON analysis_usage BEGIN UPDATE usage_totals SET total=total+NEW.reserved WHERE name='analysis'; END;
        CREATE TRIGGER IF NOT EXISTS analysis_total_update AFTER UPDATE OF reserved ON analysis_usage BEGIN UPDATE usage_totals SET total=total+NEW.reserved-OLD.reserved WHERE name='analysis'; END;
        CREATE TRIGGER IF NOT EXISTS analysis_total_delete AFTER DELETE ON analysis_usage BEGIN UPDATE usage_totals SET total=total-OLD.reserved WHERE name='analysis'; END;
        CREATE TRIGGER IF NOT EXISTS source_projection_insert AFTER INSERT ON sources BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
        CREATE TRIGGER IF NOT EXISTS source_projection_update AFTER UPDATE ON sources BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
        CREATE TRIGGER IF NOT EXISTS source_projection_delete AFTER DELETE ON sources BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
        CREATE TRIGGER IF NOT EXISTS task_projection_insert AFTER INSERT ON tasks BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
        CREATE TRIGGER IF NOT EXISTS task_projection_update AFTER UPDATE OF body ON tasks BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
        CREATE TRIGGER IF NOT EXISTS task_projection_delete AFTER DELETE ON tasks BEGIN DELETE FROM store_migrations WHERE name='indexed_history_v1'; END;
      `);
    });
    }catch(error){this.db.close();throw error;}
  }
  statement(sql){let statement=this.statements.get(sql);if(!statement){statement=this.db.prepare(sql);this.statements.set(sql,statement);}return statement;}
  transaction(fn) {if(this.db.isTransaction)return fn();this.db.exec('BEGIN IMMEDIATE');try{const v=fn();this.db.exec('COMMIT');return v;}catch(e){this.db.exec('ROLLBACK');throw e;}}
  indexSource(source,key){
    this.statement('DELETE FROM source_readers WHERE key=?').run(key);
    this.statement('DELETE FROM source_archive_sessions WHERE key=?').run(key);
    this.statement('DELETE FROM source_archive_refs WHERE key=?').run(key);
    if(!source.withdrawn)for(const actor of new Set(source.readers))this.statement('INSERT INTO source_readers VALUES(?,?,?,?,?,?,?,?)').run(actor,key,source.guildId,source.channelId,`${source.provider}:${source.guildId}:${source.channelId}`,source.actorId??null,Date.parse(source.metadata?.createdAt??'')||0,source.revision);
    if(source.metadata?.kind==='archived_voice'&&typeof source.metadata.sessionId==='string')this.statement('INSERT INTO source_archive_sessions VALUES(?,?)').run(key,source.metadata.sessionId);
    for(const sessionId of new Set(Array.isArray(source.metadata?.archiveSessionRefs)?source.metadata.archiveSessionRefs:[]))if(typeof sessionId==='string')this.statement('INSERT INTO source_archive_refs VALUES(?,?)').run(key,sessionId);
  }
  indexTaskBindings(id,bindings){this.statement('DELETE FROM task_source_bindings WHERE task_id=?').run(id);for(const binding of bindings)this.statement('INSERT INTO task_source_bindings VALUES(?,?,?) ON CONFLICT(task_id,source_key) DO UPDATE SET revision=excluded.revision').run(id,binding.key,binding.revision);}
  indexesCurrent(){this.statement('INSERT INTO store_migrations VALUES(?) ON CONFLICT(name) DO NOTHING').run('indexed_history_v1');}
  event(type,body,taskId=null){this.statement('INSERT INTO events(task_id,type,at,body) VALUES(?,?,?,?)').run(taskId,type,new Date().toISOString(),JSON.stringify(body));}
  claimHost(owner,pid,created,domain=null){this.statement('INSERT INTO host_lock(name,owner,pid,created,domain) VALUES(?,?,?,?,?)').run('runtime',owner,pid,created,domain);}
  replaceStaleHost(stale,owner,pid,created,domain){return this.transaction(()=>{const removed=this.statement('DELETE FROM host_lock WHERE name=? AND owner=? AND pid=? AND created=? AND domain IS ?').run('runtime',stale.owner,stale.pid,stale.created,stale.domain??null);check(removed.changes===1,'RUNTIME_LOCK_CHANGED');this.claimHost(owner,pid,created,domain);});}
  releaseHost(owner){this.statement('DELETE FROM host_lock WHERE name=? AND owner=?').run('runtime',owner);}
  lock(){return this.statement('SELECT * FROM host_lock WHERE name=?').get('runtime');}
  consent(guild,channel,actor,notice){const row=this.statement('SELECT * FROM voice_consents WHERE guild=? AND channel=? AND actor=?').get(guild,channel,actor);return Boolean(row?.granted===1&&row.notice===notice);}
  voiceOptedOut(guild,channel,actor){const row=this.statement('SELECT granted FROM voice_consents WHERE guild=? AND channel=? AND actor=?').get(guild,channel,actor);return row?.granted===0;}
  voiceSuspension(guild,channel){return this.statement('SELECT suspension FROM voice_controls WHERE guild=? AND channel=?').get(guild,channel)?.suspension??null;}
  setVoiceSuspension(guild,channel,suspension){check([null,'pause','leave','budget','provider_credit'].includes(suspension),'VOICE_CONTROL_INVALID');this.statement('INSERT INTO voice_controls VALUES(?,?,?) ON CONFLICT(guild,channel) DO UPDATE SET suspension=excluded.suspension').run(guild,channel,suspension);}
  assertAudioAvailable(capSeconds,totalCapSeconds,day=new Date().toISOString().slice(0,10)){
    check(capSeconds>0,'AUDIO_BUDGET_REQUIRED');
    check((this.statement('SELECT reserved_ms FROM usage WHERE day=?').get(day)?.reserved_ms??0)+1000<=capSeconds*1000,'AUDIO_BUDGET_EXHAUSTED');
    if(totalCapSeconds!==undefined)check(this.statement("SELECT total FROM usage_totals WHERE name='audio'").get().total+1000<=totalCapSeconds*1000,'AUDIO_TOTAL_BUDGET_EXHAUSTED');
  }
  recordConsent({guild,channel,actor,notice,granted,interactionId}){check(guild&&channel&&actor&&notice&&/^\d{5,24}$/.test(interactionId)&&typeof granted==='boolean','CONSENT_EVIDENCE_REQUIRED');return this.transaction(()=>{const old=this.statement('SELECT * FROM voice_consents WHERE guild=? AND channel=? AND actor=?').get(guild,channel,actor);if(old&&BigInt(old.interaction_id)>=BigInt(interactionId)){if(old.interaction_id===interactionId)check(old.notice===notice&&old.granted===Number(granted),'CONSENT_REPLAY_CONFLICT');return {granted:Boolean(old.granted),state:old.interaction_id===interactionId?'duplicate':'stale'};}this.statement('INSERT INTO voice_consents(guild,channel,actor,notice,granted,updated,interaction_id) VALUES(?,?,?,?,?,?,?) ON CONFLICT(guild,channel,actor) DO UPDATE SET notice=excluded.notice,granted=excluded.granted,updated=excluded.updated,interaction_id=excluded.interaction_id').run(guild,channel,actor,notice,Number(granted),new Date().toISOString(),interactionId);this.event('voice.consent',{guild,channel,actor,notice,granted,interactionId});return {granted,state:'updated'};});}
  ingest(source) {
    check(source&&['discord','luma','file'].includes(source.provider),'INVALID_SOURCE');
    for(const k of ['guildId','channelId','sourceId'])check(typeof source[k]==='string'&&source[k].length>0,'SOURCE_ID_REQUIRED');
    check(Number.isSafeInteger(source.revision)&&source.revision>=0,'SOURCE_REVISION_REQUIRED');
    check(typeof source.text==='string'&&Buffer.byteLength(source.text)<=2000000,'SOURCE_SIZE_LIMIT');
    check(Array.isArray(source.readers)&&source.readers.every(v=>typeof v==='string'),'SOURCE_READERS_REQUIRED');
    check(typeof source.final==='boolean','SOURCE_FINALITY_REQUIRED');
    const key=sourceIdentity(source),fingerprint=sourceFingerprint(source);
    return this.transaction(()=>{
      const old=this.statement('SELECT * FROM sources WHERE key=?').get(key);
      if(old){
        if(source.revision<old.revision)return {key,state:'stale',revision:old.revision};
        if(source.revision===old.revision){check(old.fingerprint===fingerprint,'SOURCE_REVISION_CONFLICT');return {key,state:'duplicate',revision:old.revision};}
        this.statement("UPDATE tasks SET state='stale',revision=revision+1,result=NULL WHERE id IN (SELECT id FROM tasks WHERE source_key=? UNION SELECT task_id FROM task_source_bindings WHERE source_key=?) AND state NOT IN ('stale','cancelled')").run(key,key);
        this.statement('DELETE FROM intents WHERE source_key=?').run(key);
      }
      this.statement('INSERT INTO source_versions VALUES(?,?,?,?)').run(key,source.revision,fingerprint,JSON.stringify({...source,key}));
      this.statement('INSERT INTO sources VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET revision=excluded.revision,fingerprint=excluded.fingerprint,body=excluded.body').run(key,source.revision,fingerprint,JSON.stringify({...source,key}));
      this.indexSource(source,key);
      this.indexesCurrent();
      this.event(old?'source.corrected':'source.created',{source_key:key,revision:source.revision});
      return {key,state:old?'corrected':'created',revision:source.revision};
    });
  }
  source(key,actor){const row=this.statement('SELECT * FROM sources WHERE key=?').get(key);check(row,'SOURCE_NOT_FOUND');const s=JSON.parse(row.body);check(!s.withdrawn&&s.readers.includes(actor),'SOURCE_ACCESS_DENIED');return s;}
  sourceInternal(key){const row=this.statement('SELECT body FROM sources WHERE key=?').get(key);return row?JSON.parse(row.body):null;}
  sources(actor,room=null){const sql=`SELECT s.body FROM source_readers r JOIN sources s ON s.key=r.key WHERE r.actor=?${room?' AND r.room=?':''} ORDER BY r.revision,r.key`;return this.statement(sql).all(...(room?[actor,room]:[actor])).map(r=>JSON.parse(r.body)).filter(s=>!s.withdrawn&&s.readers.includes(actor)&&(!room||room===`${s.provider}:${s.guildId}:${s.channelId}`));}
  recentSources(actor,{guildId,channelId,sourceActor=null,limit=12,order='created',excludeKey=null,replaceArchived=false}={}){
    check(typeof guildId==='string'&&typeof channelId==='string','SOURCE_ROOM_REQUIRED');
    check(Number.isSafeInteger(limit)&&limit>=0&&limit<=1000,'SOURCE_LIMIT_INVALID');check(['created','revision'].includes(order),'SOURCE_ORDER_INVALID');
    if(limit===0)return [];
    const args=[actor,guildId,channelId],where=['r.actor=?','r.guild_id=?','r.channel_id=?'];
    if(sourceActor!==null){where.push('r.source_actor=?');args.push(sourceActor);}
    if(excludeKey!==null){where.push('r.key<>?');args.push(excludeKey);}
    if(replaceArchived){
      // A fast transcript is replaced only when every referenced session has a
      // current archive readable by the same principal in this guild/channel.
      where.push(`(NOT EXISTS(SELECT 1 FROM source_archive_refs f WHERE f.key=r.key) OR EXISTS(
        SELECT 1 FROM source_archive_refs f WHERE f.key=r.key AND NOT EXISTS(
          SELECT 1 FROM source_archive_sessions a INDEXED BY source_archive_session CROSS JOIN source_readers ar
          WHERE a.session_id=f.session_id AND ar.key=a.key AND ar.actor=r.actor AND ar.guild_id=r.guild_id AND ar.channel_id=r.channel_id${excludeKey!==null?' AND ar.key<>?':''})))`);
      if(excludeKey!==null)args.push(excludeKey);
    }
    const sql=`SELECT s.body FROM source_readers r JOIN sources s ON s.key=r.key WHERE ${where.join(' AND ')} ORDER BY ${order==='created'?'r.created_ms DESC,':''}r.revision DESC,r.key DESC LIMIT ?`;
    return this.statement(sql).all(...args,limit).map(r=>JSON.parse(r.body)).filter(s=>!s.withdrawn&&s.readers.includes(actor)&&s.guildId===guildId&&s.channelId===channelId&&(sourceActor===null||s.actorId===sourceActor)&&s.key!==excludeKey);
  }
  contextSources(actor,options){return this.recentSources(actor,{...options,replaceArchived:true});}
  saveIntents(source,items,principal=source.actorId){return this.transaction(()=>{
    const current=this.source(source.key,principal);check(current.revision===source.revision,'SOURCE_CHANGED');
    return items.map((item,index)=>{const id=digest([source.key,index]);const body=JSON.stringify({...item,id,source_key:source.key,source_revision:source.revision});this.statement('INSERT INTO intent_versions VALUES(?,?,?) ON CONFLICT(id,revision) DO NOTHING').run(id,source.revision,body);this.statement('INSERT INTO intents VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body').run(id,source.key,source.revision,body);return id;});
  });}
  listIntents(actor){return this.statement('SELECT i.* FROM source_readers r JOIN intents i ON i.source_key=r.key WHERE r.actor=? ORDER BY i.rowid').all(actor).flatMap(row=>{try{this.source(row.source_key,actor);const i=JSON.parse(row.body);for(const b of i.contextSources??[]){const s=this.source(b.key,actor);check(s.revision===b.revision,'CONTEXT_CHANGED');}return [i];}catch{return [];}});}
  createTask(source,intent){
    check(source.actorId&&source.final&&!source.withdrawn,'FINAL_AUTHENTICATED_SOURCE_REQUIRED');
    const requestKey=digest([source.key,intent.key??intent.id??digest(intent)]);
    return this.transaction(()=>{
      const current=this.source(source.key,source.actorId);check(current.revision===source.revision,'SOURCE_CHANGED');
      const old=this.statement('SELECT id FROM tasks WHERE request_key=?').get(requestKey);if(old){const task=this.task(old.id,source.actorId);if(task.source_revision!==source.revision)return this.reviseTask(old.id,source,intent);return task;}
      const id=uid('task');const task={id,source_key:source.key,source_revision:source.revision,room:`${source.provider}:${source.guildId}:${source.channelId}`,actor:source.actorId,title:intent.title,request:intent.request,action:intent.action,intentIds:intent.intentIds??[],requiredActions:intent.requiredActions??[intent.action],acceptance:intent.acceptance??[],contextSources:intent.contextSources??[],createdAt:new Date().toISOString()};
      this.statement('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,NULL)').run(id,requestKey,source.key,source.revision,task.room,source.actorId,1,'queued',JSON.stringify(task));this.indexTaskBindings(id,task.contextSources);this.indexesCurrent();this.event('task.created',{source_key:source.key,action:task.action},id);return this.task(id,source.actorId);
    });
  }
  taskInternal(id){const row=this.statement('SELECT * FROM tasks WHERE id=?').get(id);check(row,'TASK_NOT_FOUND');return {...JSON.parse(row.body),revision:row.revision,state:row.state,result:row.result?JSON.parse(row.result):null};}
  bindContext(id,revision,bindings){return this.transaction(()=>{const t=this.taskInternal(id);check(t.revision===revision&&t.state==='running','TASK_CHANGED');for(const b of bindings){const s=this.source(b.key,t.actor);check(s.revision===b.revision,'CONTEXT_CHANGED');}const body={...t,contextSources:bindings};delete body.result;delete body.state;delete body.revision;const r=this.statement("UPDATE tasks SET body=? WHERE id=? AND revision=? AND state='running'").run(JSON.stringify(body),id,revision);check(r.changes===1,'TASK_CHANGED');this.indexTaskBindings(id,bindings);this.indexesCurrent();this.event('task.context_bound',{bindings},id);});}
  assertContext(id,actor){const t=this.taskInternal(id);check(t.actor===actor,'TASK_ACCESS_DENIED');for(const b of t.contextSources??[]){const s=this.source(b.key,actor);check(s.revision===b.revision,'CONTEXT_CHANGED');}return true;}
  reviseTask(id,source,intent){return this.transaction(()=>{const old=this.task(id,source.actorId);check(old.room===`${source.provider}:${source.guildId}:${source.channelId}`,'TASK_ROOM_MISMATCH');const updated={...old,source_key:source.key,source_revision:source.revision,request:intent.request,title:intent.title,action:intent.action,intentIds:intent.intentIds??[],requiredActions:intent.requiredActions??[intent.action],acceptance:intent.acceptance??old.acceptance,contextSources:intent.contextSources??[]};delete updated.result;delete updated.state;delete updated.revision;const r=this.statement("UPDATE tasks SET source_key=?,source_revision=?,revision=revision+1,state='queued',body=?,result=NULL WHERE id=? AND revision=?").run(source.key,source.revision,JSON.stringify(updated),id,old.revision);check(r.changes===1,'TASK_CHANGED');this.indexTaskBindings(id,updated.contextSources);this.indexesCurrent();this.event('task.corrected',{previousSource:old.source_key,source:source.key,sourceRevision:source.revision,previousIntentIds:old.intentIds??[],intentIds:updated.intentIds},id);return this.task(id,source.actorId);});}
  task(id,actor){const t=this.taskInternal(id);check(t.actor===actor,'TASK_ACCESS_DENIED');this.source(t.source_key,actor);for(const b of t.contextSources??[]){const s=this.source(b.key,actor);if(t.state!=='stale')check(s.revision===b.revision,'CONTEXT_CHANGED');}return t;}
  tasks(actor,{room=null,limit=null}={}){
    check(limit===null||(Number.isSafeInteger(limit)&&limit>=0&&limit<=1000),'TASK_LIMIT_INVALID');if(limit===0)return [];
    const sql=`SELECT t.id FROM tasks t INDEXED BY ${room?'tasks_actor_room':'tasks_actor'} JOIN source_readers r ON r.key=t.source_key AND r.actor=t.actor
      WHERE t.actor=?${room?' AND t.room=?':''} AND NOT EXISTS(
        SELECT 1 FROM task_source_bindings b LEFT JOIN source_readers cr ON cr.key=b.source_key AND cr.actor=t.actor LEFT JOIN sources cs ON cs.key=b.source_key
        WHERE b.task_id=t.id AND (cr.key IS NULL OR (t.state<>'stale' AND cs.revision<>b.revision)))
      ORDER BY t.rowid DESC${limit!==null?' LIMIT ?':''}`;
    const args=room?[actor,room]:[actor];if(limit!==null)args.push(limit);
    return this.statement(sql).all(...args).flatMap(row=>{try{return [this.task(row.id,actor)];}catch{return [];}});
  }
  recentTasks(actor,options){return this.tasks(actor,options);}
  claim(id,revision){const r=this.statement("UPDATE tasks SET state='running' WHERE id=? AND revision=? AND state='queued'").run(id,revision);check(r.changes===1,'TASK_NOT_QUEUED');this.event('task.started',{revision},id);}
  finish(id,revision,result){check(['needs_review','failed','uncertain'].includes(result.state),'INVALID_RESULT_STATE');const t=this.taskInternal(id);const s=this.sourceInternal(t.source_key);check(s&&!s.withdrawn&&s.revision===t.source_revision,'SOURCE_CHANGED');this.assertContext(id,t.actor);const r=this.statement("UPDATE tasks SET state=?,result=? WHERE id=? AND revision=? AND state='running'").run(result.state,JSON.stringify(result),id,revision);check(r.changes===1,'TASK_CHANGED');this.event('task.result',{state:result.state,artifact_count:result.artifacts?.length??0},id);}
  cancel(id,actor){const t=this.task(id,actor);if(['stopping','cancelled','uncertain'].includes(t.state))return t;this.statement('UPDATE tasks SET state=?,revision=revision+1,result=NULL WHERE id=?').run(t.state==='running'?'stopping':'cancelled',id);this.event('task.stop_requested',{},id);return t;}
  cancelQueued(id,actor,revision){return this.transaction(()=>{const t=this.taskInternal(id);check(t.actor===actor,'TASK_ACCESS_DENIED');check(t.revision===revision&&t.state==='queued','TASK_CHANGED');const r=this.statement("UPDATE tasks SET state='cancelled',revision=revision+1,result=NULL WHERE id=? AND actor=? AND revision=? AND state='queued'").run(id,actor,revision);check(r.changes===1,'TASK_CHANGED');this.event('task.admission_cancelled',{revision},id);return this.taskInternal(id);});}
  confirmStop(id,actor,confirmed){const t=this.task(id,actor);check(t.state==='stopping','TASK_NOT_STOPPING');this.statement('UPDATE tasks SET state=? WHERE id=?').run(confirmed?'cancelled':'uncertain',id);this.event('task.stop_observed',{confirmed},id);}
  resume(id,actor){return this.transaction(()=>{const t=this.task(id,actor);check(['cancelled','failed','paused'].includes(t.state),'TASK_CANNOT_RESUME');const s=this.source(t.source_key,actor);check(s.revision===t.source_revision,'SOURCE_CHANGED');const changed=this.statement("UPDATE tasks SET state='queued',revision=revision+1,result=NULL WHERE id=? AND revision=? AND state=?").run(id,t.revision,t.state);check(changed.changes===1,'TASK_CHANGED');this.event('task.resumed',{previousState:t.state,revision:t.revision+1},id);return this.task(id,actor);});}
  reconcileInterrupted(){return this.transaction(()=>{
    const affected=this.statement("SELECT id,state,revision FROM tasks WHERE state IN ('queued','running','stopping') ORDER BY rowid").all();
    for(const task of affected){const state=task.state==='queued'?'paused':'uncertain',reason=state==='paused'?'RUNTIME_RESTART_BEFORE_EXECUTION':'RUNTIME_RESTART_DURING_EXECUTION';
      this.statement('UPDATE tasks SET state=?,result=? WHERE id=? AND revision=? AND state=?').run(state,JSON.stringify({state,summary:reason,artifacts:[],recoveryRequired:true}),task.id,task.revision,task.state);
      this.event('task.recovery_required',{previousState:task.state,state,reason,revision:task.revision},task.id);
    }
    return affected.length;
  });}
  claimDelivery(key,body){return this.transaction(()=>{const hash=digest(body),old=this.statement('SELECT * FROM deliveries WHERE key=?').get(key);if(old){check(old.digest===hash,'DELIVERY_CONFLICT');return false;}this.statement('INSERT INTO deliveries VALUES(?,?,?,NULL)').run(key,hash,'unknown');return true;});}
  delivered(key,messageId){this.statement("UPDATE deliveries SET state='sent',message_id=? WHERE key=?").run(messageId,key);}
  deliveryState(key){return this.statement('SELECT state FROM deliveries WHERE key=?').get(key)?.state??null;}
  reserveAudio(milliseconds,capSeconds,day=new Date().toISOString().slice(0,10),totalCapSeconds){return this.transaction(()=>{check(Number.isSafeInteger(milliseconds)&&milliseconds>0&&capSeconds>0,'AUDIO_BUDGET_REQUIRED');const old=this.statement('SELECT reserved_ms FROM usage WHERE day=?').get(day)?.reserved_ms??0;check(old+milliseconds<=capSeconds*1000,'AUDIO_BUDGET_EXHAUSTED');if(totalCapSeconds!==undefined){const total=this.statement("SELECT total FROM usage_totals WHERE name='audio'").get().total;check(total+milliseconds<=totalCapSeconds*1000,'AUDIO_TOTAL_BUDGET_EXHAUSTED');}this.statement('INSERT INTO usage VALUES(?,?) ON CONFLICT(day) DO UPDATE SET reserved_ms=excluded.reserved_ms').run(day,old+milliseconds);return old+milliseconds;});}
  reserveAnalysis(limits,day=new Date().toISOString().slice(0,10)){
    check(/^\d{4}-\d{2}-\d{2}$/.test(day),'ANALYSIS_DAY_INVALID');
    for(const key of ['maxDailyAnalyses','maxTotalAnalyses'])check(Number.isSafeInteger(limits[key])&&limits[key]>=0,'ANALYSIS_LIMIT_INVALID');
    return this.transaction(()=>{
      const used=this.statement('SELECT reserved FROM analysis_usage WHERE day=?').get(day)?.reserved??0;
      const total=this.statement("SELECT total FROM usage_totals WHERE name='analysis'").get().total;
      check(used<limits.maxDailyAnalyses,'ANALYSIS_BUDGET_EXHAUSTED');check(total<limits.maxTotalAnalyses,'ANALYSIS_TOTAL_BUDGET_EXHAUSTED');
      this.statement('INSERT INTO analysis_usage VALUES(?,?) ON CONFLICT(day) DO UPDATE SET reserved=excluded.reserved').run(day,used+1);
      return {day,reserved:used+1,total:total+1};
    });
  }
  close(){this.db.close();}
}
