import {check,digest,uid} from './common.mjs';
import {shape,text,reference,revision,validateBrief,validateProject,validateSource,sourceReference,inspectChange} from './project-contract.mjs';

const MAX_VERSIONS=32;
const fields={read:['actor','operation','project_id'],create:['actor','operation','request_id','name','source','brief'],
  inspect:['actor','operation','project_id','expected_revision','base_digest','source','reason','brief'],
  correct:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','brief']};
const room=source=>`${source.provider}:${source.guildId}:${source.channelId}`;
const unique=refs=>[...new Map(refs.map(ref=>[sourceReference(ref),ref])).values()];
const binding=config=>digest({installation:config.installation,dataDir:config.dataDir,owner:config.owner,
  guild:config.discord.guildId,application:config.discord.applicationId??null,workspace:config.worker.workspace});

function request(input){
  check(input&&Object.hasOwn(fields,input.operation),'PROJECT_OPERATION_INVALID');shape(input,fields[input.operation],'PROJECT_REQUEST_INVALID');
  check(typeof input.actor==='string'&&/^\d{5,24}$/.test(input.actor),'OPERATOR_REQUIRED');
  if(input.operation!=='create')reference(input.project_id);
  if(input.operation!=='read'){
    validateBrief(input.brief);validateSource(input.source);
    if(input.operation==='create')text(input.name,200,'PROJECT_NAME_INVALID');
    else{revision(input.expected_revision);check(typeof input.base_digest==='string'&&/^[a-f0-9]{64}$/.test(input.base_digest),'PROJECT_BASE_INVALID');text(input.reason,1000,'PROJECT_CHANGE_REASON_INVALID');}
  }
  if(['create','correct'].includes(input.operation))check(typeof input.request_id==='string'&&/^[A-Za-z0-9._:-]{1,128}$/.test(input.request_id),'PROJECT_REQUEST_ID_INVALID');
  return structuredClone(input);
}

/** Actor-owned Project metadata in the installation's existing SQLite Store.
 * This adapter never creates Source/Task records or dispatches work. */
export class ProjectHub{
  constructor({store,config,policy=()=>config,readConfig=async()=>policy(),authorizeSource,assertActive=()=>{},accessEpoch=()=>null}){
    check(typeof authorizeSource==='function'&&typeof readConfig==='function','PROJECT_AUTHORIZATION_REQUIRED');
    Object.assign(this,{store,config,policy,readConfig,authorizeSource,assertActive,accessEpoch});this.binding=binding(config);
    store.db.exec(`
      CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,actor TEXT NOT NULL,room TEXT NOT NULL,binding TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS project_versions(project_id TEXT NOT NULL REFERENCES projects(id),revision INTEGER NOT NULL,body TEXT NOT NULL,sources TEXT NOT NULL,previous_digest TEXT,PRIMARY KEY(project_id,revision));
      CREATE TABLE IF NOT EXISTS project_requests(actor TEXT NOT NULL,request_id TEXT NOT NULL,request_digest TEXT NOT NULL,project_id TEXT NOT NULL REFERENCES projects(id),revision INTEGER NOT NULL,PRIMARY KEY(actor,request_id));
    `);
  }
  guard(input,signal,policy=this.policy()){
    signal?.throwIfAborted();this.assertActive();
    check(this.config.owner.kind==='local'&&policy.owner.kind==='local','PROJECT_LOCAL_OWNER_REQUIRED');
    check(binding(policy)===this.binding,'PROJECT_INSTALLATION_CHANGED');
    check(this.config.discord.operators.includes(input.actor)&&policy.discord.operators.includes(input.actor),'OPERATOR_REQUIRED');
    check(this.config.projects?.operations.includes(input.operation)&&policy.projects?.operations.includes(input.operation),'PROJECT_OPERATION_NOT_ALLOWED');
  }
  current(id,actor){
    const row=this.store.statement('SELECT * FROM projects WHERE id=?').get(id);check(row&&row.actor===actor,'PROJECT_NOT_FOUND');
    check(row.binding===this.binding,'PROJECT_INSTALLATION_CHANGED');
    const project=validateProject(JSON.parse(row.body));check(project.project_id===id&&project.revision===row.revision&&project.owner_ref===`ref/project-owner/${this.config.installation}`&&project.task_refs.length===0,'PROJECT_RECORD_INVALID');
    const version=this.version(id,row.revision);check(digest(version.project)===digest(project),'PROJECT_RECORD_INVALID');
    return {...row,project,sources:version.sources};
  }
  version(id,revision){
    const row=this.store.statement('SELECT body,sources FROM project_versions WHERE project_id=? AND revision=?').get(id,revision);check(row,'PROJECT_RECORD_INVALID');
    const project=validateProject(JSON.parse(row.body)),sources=JSON.parse(row.sources);
    check(project.project_id===id&&project.revision===revision&&Array.isArray(sources)&&sources.length>0&&sources.length<=MAX_VERSIONS,'PROJECT_RECORD_INVALID');
    for(const source of sources)validateSource(source);
    check(unique(sources).length===sources.length&&sourceReference(sources[0])===project.original_ref,'PROJECT_RECORD_INVALID');return {project,sources};
  }
  sources(refs,actor,expectedRoom=null){
    check(refs.length>0&&refs.length<=MAX_VERSIONS,'PROJECT_SOURCE_LIMIT');
    return refs.map(ref=>{
      validateSource(ref);const current=this.store.source(ref.key,actor);
      const row=this.store.statement('SELECT body FROM source_versions WHERE key=? AND revision=?').get(ref.key,ref.revision);check(row,'PROJECT_SOURCE_VERSION_UNAVAILABLE');
      const original=JSON.parse(row.body);
      check(original.key===ref.key&&original.revision===ref.revision&&original.final&&!original.withdrawn&&original.readers?.includes(actor),'SOURCE_ACCESS_DENIED');
      check(original.actorId===actor&&current.actorId===actor,'PROJECT_SOURCE_ACTOR_MISMATCH');
      check(original.provider==='discord'&&original.guildId===this.config.discord.guildId&&room(original)===room(current)&&(!expectedRoom||room(original)===expectedRoom),'PROJECT_SOURCE_SCOPE_MISMATCH');
      return {ref,current,original};
    });
  }
  sourceScope(sources,policy){
    const allowed=config=>new Set([...config.discord.textChannelIds,config.discord.resultChannelId]);
    for(const {current} of sources)check(allowed(this.config).has(current.channelId)&&allowed(policy).has(current.channelId),'PROJECT_SOURCE_SCOPE_MISMATCH');
  }
  response(version,current,sources,{replay=false,write=false}={}){
    return {kind:'kotodama.project-owner-view',version:1,authority:'selected_local_project_owner',project:version.project,project_digest:digest(version.project),
      snapshot:replay?'saved_revision':'current',current_revision:current.project.revision,
      source_refs:version.sources.map(ref=>{const observed=sources.find(s=>sourceReference(s.ref)===sourceReference(ref));return {...ref,current_revision:observed.current.revision,freshness:observed.current.revision===ref.revision?'current':'superseded'};}),
      ...(write?{replay,saved_revision:version.project.revision}:{}),task_state_changed:false,execution_authorized:false};
  }
  async handle(raw,{signal,assertScope=()=>{}}={}){
    check(typeof assertScope==='function','PROJECT_SCOPE_GUARD_REQUIRED');
    return this.#handle(request(raw),signal,true,assertScope);
  }
  async #handle(input,signal,replayRetry,assertScope){
    // The caller supplies this synchronous surface guard, never request JSON.
    // Keep it scoped to this invocation, including the one bounded replay.
    const guard=(policy=this.policy())=>{this.guard(input,signal,policy);assertScope(policy);signal?.throwIfAborted();};
    guard();
    const policy=await this.readConfig();guard(policy);
    const write=['create','correct'].includes(input.operation),requestDigest=write?digest(input):null;
    const prior=write?this.store.statement('SELECT * FROM project_requests WHERE actor=? AND request_id=?').get(input.actor,input.request_id):null;
    if(prior)check(prior.request_digest===requestDigest,'PROJECT_REQUEST_CONFLICT');
    const current=prior?this.current(prior.project_id,input.actor):input.operation==='create'?null:this.current(input.project_id,input.actor);
    const saved=prior?this.version(prior.project_id,prior.revision):null;
    let candidate;
    if(!prior&&['inspect','correct'].includes(input.operation))candidate=inspectChange(current.project,{version:1,project_id:input.project_id,
      expected_revision:input.expected_revision,base_digest:input.base_digest,reason:input.reason,source_ref:sourceReference(input.source),brief:input.brief});
    const refs=unique([...(current?.sources??[]),...(saved?.sources??[]),...(input.source?[input.source]:[])]);
    const observed=this.sources(refs,input.actor,current?.room),epoch=this.accessEpoch();this.sourceScope(observed,policy);
    if(input.source&&!prior)check(observed.find(s=>sourceReference(s.ref)===sourceReference(input.source)).current.revision===input.source.revision,'SOURCE_CHANGED');
    for(const {current:source} of [...new Map(observed.map(s=>[s.ref.key,s])).values()]){
      guard();await this.authorizeSource(source,input.actor,{signal});guard();
    }
    const final=await this.readConfig();guard(final);this.sourceScope(observed,final);check(this.accessEpoch()===epoch,'PROJECT_ACCESS_CHANGED');
    // No await between these final checks and the same-Store transaction.
    try{return this.store.transaction(()=>{
      guard(final);check(this.accessEpoch()===epoch,'PROJECT_ACCESS_CHANGED');
      check(digest(this.sources(refs,input.actor,current?.room))===digest(observed),'PROJECT_SOURCE_CHANGED');
      if(current)check(digest(this.current(current.id,input.actor))===digest(current),'PROJECT_CHANGED');
      if(prior)return this.response(saved,current,observed,{replay:true,write:true});
      if(input.operation==='read')return this.response({project:current.project,sources:current.sources},current,observed);
      if(input.operation==='inspect')return {...candidate,source_refs:refs,task_state_changed:false,execution_authorized:false};
      // A concurrent first delivery may have committed while authorization awaited.
      check(!this.store.statement('SELECT request_digest FROM project_requests WHERE actor=? AND request_id=?').get(input.actor,input.request_id),'PROJECT_CHANGED');
      check(!current||current.project.revision<MAX_VERSIONS,'PROJECT_VERSION_LIMIT');
      const project=validateProject(current?{...current.project,revision:current.project.revision+1,brief:input.brief}:{version:1,project_id:`ref/project/${uid('project').slice(8)}`,
        revision:1,owner_ref:`ref/project-owner/${this.config.installation}`,name:input.name,original_ref:sourceReference(input.source),brief:input.brief,task_refs:[]});
      const selectedRoom=current?.room??room(observed[0].original),body=JSON.stringify(project);
      if(current){const changed=this.store.statement('UPDATE projects SET revision=?,body=? WHERE id=? AND revision=?').run(project.revision,body,current.id,current.revision);check(changed.changes===1,'PROJECT_CHANGED');}
      else this.store.statement('INSERT INTO projects VALUES(?,?,?,?,?,?)').run(project.project_id,input.actor,selectedRoom,this.binding,project.revision,body);
      this.store.statement('INSERT INTO project_versions VALUES(?,?,?,?,?)').run(project.project_id,project.revision,body,JSON.stringify(refs),current?digest(current.project):null);
      this.store.statement('INSERT INTO project_requests VALUES(?,?,?,?,?)').run(input.actor,input.request_id,requestDigest,project.project_id,project.revision);
      this.store.event(current?'project.corrected':'project.created',{project_id:project.project_id,revision:project.revision,actor:input.actor,request_id:input.request_id,
        source:input.source,original_ref:project.original_ref,previous_digest:current?digest(current.project):null,project_digest:digest(project),
        ...(candidate?{reason:input.reason,changed_fields:candidate.changed_fields,removed_requirements:candidate.removed_requirements,impact_task_refs:[]}:{})});
      return this.response({project,sources:refs},{project},observed,{write:true});
    });}catch(error){
      // Retry only an identical request which another caller just committed.
      // The complete access/lineage checks run again; unrelated stale writes
      // are never replayed or rebased onto a newer Project automatically.
      if(replayRetry&&write&&!prior&&error.code==='PROJECT_CHANGED'){
        const completed=this.store.statement('SELECT request_digest FROM project_requests WHERE actor=? AND request_id=?').get(input.actor,input.request_id);
        if(completed?.request_digest===requestDigest)return this.#handle(input,signal,false,assertScope);
      }
      throw error;
    }
  }
}
