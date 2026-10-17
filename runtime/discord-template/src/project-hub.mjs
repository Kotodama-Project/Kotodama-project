import path from 'node:path';
import {realpath} from 'node:fs/promises';
import {readArtifact} from './artifact.mjs';
import {resultFiles} from './result-files.mjs';
import {verifyArtifacts} from './worker.mjs';
import {check,digest,uid,safePath} from './common.mjs';
import {shape,text,reference,revision,validateBrief,validateProject,validateSource,validateTaskId,sourceReference,inspectChange} from './project-contract.mjs';

const MAX_VERSIONS=32;
const fields={read:['actor','operation','project_id'],create:['actor','operation','request_id','name','source','brief'],
  inspect:['actor','operation','project_id','expected_revision','base_digest','source','reason','brief'],
  correct:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','brief'],
  link_task:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','task_id','expected_task_revision'],
  unlink_task:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','task_id'],
  run_task:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','task'],
  resume_task:['actor','operation','request_id','project_id','expected_revision','base_digest','source','reason','task_id','expected_task_revision'],
  read_result:['actor','operation','project_id','task_id'],
  read_task:['actor','operation','project_id','task_id']};
const writes=new Set(['create','correct','link_task','unlink_task','run_task','resume_task']);
const taskStates=new Set(['queued','running','needs_review','failed','paused','stopping','cancelled','stale','uncertain']);
const room=source=>`${source.provider}:${source.guildId}:${source.channelId}`;
const unique=refs=>[...new Map(refs.map(ref=>[sourceReference(ref),ref])).values()];
const binding=config=>digest({installation:config.installation,dataDir:config.dataDir,owner:config.owner,
  guild:config.discord.guildId,application:config.discord.applicationId??null,workspace:config.worker.workspace});

export function validateProjectRequest(input){
  check(input&&Object.hasOwn(fields,input.operation),'PROJECT_OPERATION_INVALID');shape(input,fields[input.operation],'PROJECT_REQUEST_INVALID');
  check(typeof input.actor==='string'&&/^\d{5,24}$/.test(input.actor),'OPERATOR_REQUIRED');
  if(input.operation!=='create')reference(input.project_id);
  if(!['read','read_task','read_result'].includes(input.operation)){
    if(['create','correct','inspect'].includes(input.operation))validateBrief(input.brief);validateSource(input.source);
    if(input.operation==='create')text(input.name,200,'PROJECT_NAME_INVALID');
    else{revision(input.expected_revision);check(typeof input.base_digest==='string'&&/^[a-f0-9]{64}$/.test(input.base_digest),'PROJECT_BASE_INVALID');text(input.reason,1000,'PROJECT_CHANGE_REASON_INVALID');}
  }
  if(writes.has(input.operation))check(typeof input.request_id==='string'&&/^[A-Za-z0-9._:-]{1,128}$/.test(input.request_id),'PROJECT_REQUEST_ID_INVALID');
  if(['read_task','read_result','link_task','unlink_task','resume_task'].includes(input.operation))validateTaskId(input.task_id);
  if(input.operation==='run_task'){
    shape(input.task,['title','request','action','acceptance'],'PROJECT_TASK_INPUT_INVALID');
    text(input.task.title,120,'PROJECT_TASK_INPUT_INVALID');text(input.task.request,4000,'PROJECT_TASK_INPUT_INVALID');
    check(['research','summarize','develop','write_file'].includes(input.task.action),'PROJECT_TASK_ACTION_INVALID');
    check(Array.isArray(input.task.acceptance)&&input.task.acceptance.length<=20,'PROJECT_TASK_INPUT_INVALID');
    for(const item of input.task.acceptance)text(item,1000,'PROJECT_TASK_INPUT_INVALID');
  }
  if(['link_task','resume_task'].includes(input.operation))revision(input.expected_task_revision);
  return structuredClone(input);
}

/** Actor-owned Project metadata in the installation's existing SQLite Store.
 * Explicit run_task reuses the same Task owner and Pipeline admission. */
export class ProjectHub{
  constructor({store,config,policy=()=>config,readConfig=async()=>policy(),authorizeSource,assertActive=()=>{},accessEpoch=()=>null,dispatchTask=null}){
    check(typeof authorizeSource==='function'&&typeof readConfig==='function','PROJECT_AUTHORIZATION_REQUIRED');
    Object.assign(this,{store,config,policy,readConfig,authorizeSource,assertActive,accessEpoch,dispatchTask});this.binding=binding(config);
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
    const project=validateProject(JSON.parse(row.body));check(project.project_id===id&&project.revision===row.revision&&project.owner_ref===`ref/project-owner/${this.config.installation}`&&project.task_refs.every(ref=>project.version===2&&ref.adapter==='discord_local_task_v1'),'PROJECT_RECORD_INVALID');
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
      this.sourceConsent(original);this.sourceConsent(current);
      check(original.key===ref.key&&original.revision===ref.revision&&original.final&&!original.withdrawn&&original.readers?.includes(actor),'SOURCE_ACCESS_DENIED');
      check(original.actorId===actor&&current.actorId===actor,'PROJECT_SOURCE_ACTOR_MISMATCH');
      check(original.provider==='discord'&&original.guildId===this.config.discord.guildId&&room(original)===room(current)&&(!expectedRoom||room(original)===expectedRoom),'PROJECT_SOURCE_SCOPE_MISMATCH');
      return {ref,current,original};
    });
  }
  sourceConsent(source){
    if(source.metadata?.kind==='voice'){
      const speaker=source.metadata.inputAccountId??source.actorId;
      check(typeof speaker==='string'&&!this.store.voiceOptedOut(source.guildId,source.channelId,speaker),'PROJECT_VOICE_SCOPE_REVOKED');
    }
  }
  sourceScope(sources,policy){
    const allowed=config=>new Set([...config.discord.textChannelIds,config.discord.resultChannelId,config.discord.voiceChannelId,...(config.voicePool?.rooms??[]).map(room=>room.channelId)].filter(Boolean));
    for(const {current} of sources)check(allowed(this.config).has(current.channelId)&&allowed(policy).has(current.channelId),'PROJECT_SOURCE_SCOPE_MISMATCH');
  }
  taskSnapshot(id,actor,expectedRoom){
    const size=this.store.statement('SELECT length(CAST(body AS BLOB))+COALESCE(length(CAST(result AS BLOB)),0) AS bytes FROM tasks WHERE id=? AND actor=?').get(id,actor);
    check(size,'PROJECT_TASK_UNAVAILABLE');check(size.bytes<=262144,'PROJECT_TASK_SIZE_LIMIT');
    const task=this.store.taskInternal(id);validateTaskId(task.id);revision(task.revision);
    check(task.id===id&&task.actor===actor&&task.room===expectedRoom&&taskStates.has(task.state),'PROJECT_TASK_SCOPE_MISMATCH');
    check(Array.isArray(task.contextSources??[])&&(task.contextSources??[]).length<=32,'PROJECT_TASK_SOURCE_LIMIT');
    const refs=unique([{key:task.source_key,revision:task.source_revision},...(task.contextSources??[])]);check(refs.length<=32,'PROJECT_TASK_SOURCE_LIMIT');let bytes=0;
    const sources=refs.map(ref=>{
      validateSource(ref);
      const size=this.store.statement('SELECT length(CAST(s.body AS BLOB))+length(CAST(v.body AS BLOB)) AS bytes FROM sources s JOIN source_versions v ON v.key=s.key WHERE s.key=? AND v.revision=?').get(ref.key,ref.revision);
      check(size,'PROJECT_TASK_SOURCE_UNAVAILABLE');bytes+=size.bytes;check(bytes<=4194304,'PROJECT_TASK_SOURCE_SIZE_LIMIT');
      const current=this.store.source(ref.key,actor),original=JSON.parse(this.store.statement('SELECT body FROM source_versions WHERE key=? AND revision=?').get(ref.key,ref.revision).body);
      this.sourceConsent(original);this.sourceConsent(current);
      check(original.key===ref.key&&original.revision===ref.revision&&original.final&&!original.withdrawn&&original.readers?.includes(actor),'SOURCE_ACCESS_DENIED');
      check(room(current)===expectedRoom&&room(original)===expectedRoom,'PROJECT_TASK_SCOPE_MISMATCH');
      return {ref,current,original};
    });
    return {task,sources};
  }
  taskView(current,link,snapshot){
    const {task,sources}=snapshot,matching=task.revision===link.revision,sourceMatching=sources.every(s=>s.current.revision===s.ref.revision);
    const result=matching&&sourceMatching&&task.state==='needs_review'?task.result:null;
    if(result){check(result&&typeof result==='object'&&!Array.isArray(result)&&result.state==='needs_review','PROJECT_TASK_RESULT_INVALID');
      check((result.taskRevision===undefined||result.taskRevision===task.revision)&&(result.sourceRevision===undefined||result.sourceRevision===task.source_revision),'PROJECT_TASK_RESULT_INVALID');
      check(Array.isArray(result.artifacts??[])&&(result.artifacts??[]).length<=32&&Array.isArray(result.validations??[])&&(result.validations??[]).length<=32,'PROJECT_TASK_RESULT_LIMIT');}
    const checks=result?.validations??[];
    return {kind:'kotodama.project-task-observation',version:1,project_id:current.id,project_revision:current.revision,project_digest:digest(current.project),
      task_ref:link,current_task_revision:task.revision,owner_state:task.state,resolution:!matching?'revision_changed':!sourceMatching?'source_changed':'observed',
      source_refs:sources.map(s=>({...s.ref,current_revision:s.current.revision,freshness:s.current.revision===s.ref.revision?'current':'superseded'})),
      result_metadata:{availability:result?'reported':'unavailable',artifact_count:result?(result.artifacts??[]).length:null,
        checks:checks.length?checks.every(c=>c&&typeof c==='object'&&(c.status===undefined||c.status==='passed')&&(c.exitCode===undefined||c.exitCode===0)&&(c.status==='passed'||c.exitCode===0))?'reported_pass':'reported_failure':'unobserved',
        execution:result?.verifiedExecution===true?'reported':'unobserved',independent_review:result?.independentReview===true?'reported_pass':'unobserved',artifact_readback:'not_run'},
      completion:'not_observed',task_state_changed:false,execution_authorized:false};
  }
  assertTaskCurrent(task,policy=this.policy()){
    if(!task.projectBinding)return;
    check(binding(policy)===this.binding&&policy.owner.kind==='local','PROJECT_INSTALLATION_CHANGED');
    const b=task.projectBinding,current=this.current(b.project_id,task.actor);
    check(digest({brief:current.project.brief,original_ref:current.project.original_ref})===b.contract_digest,'PROJECT_TASK_CONTRACT_CHANGED');
    check(current.project.task_refs.some(ref=>ref.task_id===task.id&&ref.revision===task.revision),'PROJECT_TASK_NOT_LINKED');
    const history=this.sources(b.source_history??b.sources,task.actor,current.room);this.sourceScope(history,policy);
    const sources=this.sources(b.sources,task.actor,current.room);
    check(sources.every(s=>s.current.revision===s.ref.revision),'PROJECT_SOURCE_CHANGED');
  }
  async readResult(task){
    check(task.state==='needs_review'&&task.result?.state==='needs_review','RESULT_NOT_AVAILABLE');
    const result=task.result;
    await verifyArtifacts(task);
    check(result.taskRevision===task.revision&&result.sourceRevision===task.source_revision,'PROJECT_TASK_RESULT_INVALID');
    check(typeof result.summary==='string'&&Buffer.byteLength(result.summary)<=65536,'PROJECT_RESULT_SIZE_LIMIT');
    // CLI summaries have a saved artifact. Existing built-in adapters instead
    // record an owner summary alongside separately verified deliverables.
    const summary=(result.artifacts??[]).filter(a=>a.relative==='result.md'&&!a.deleted);
    const reported=task.action==='create_company_pack'&&result.adapter==='company_pack_builtin_v1'||task.action==='swarm_research'&&result.adapter==='task_swarm_v1';
    let summarySha=null;
    if(reported)check(summary.length===0,'PROJECT_TASK_RESULT_INVALID');
    else{
      check(summary.length===1,'PROJECT_RESULT_SUMMARY_REQUIRED');
      const base=path.join(this.config.dataDir,'artifacts',`${task.id}-r${task.revision}`);
      const file=await safePath(base,'result.md'),a=summary[0];
      // Match the actual file, as resultFiles does: Windows short names and
      // configured directory aliases can differ from safePath's canonical root.
      check(path.relative(await realpath(a.path),file)===''&&a.bytes===Buffer.byteLength(result.summary),'PROJECT_TASK_RESULT_INVALID');
      const bytes=await readArtifact(file,65536);
      check(bytes.length===a.bytes&&digest(bytes)===a.sha256&&bytes.toString('utf8')===result.summary,'ARTIFACT_CHANGED');summarySha=digest(bytes);
    }
    const files=await resultFiles(result,{artifactRoot:path.join(this.config.dataDir,'worktrees')});
    if(reported)check(files.length>0,'PROJECT_RESULT_DELIVERABLE_REQUIRED');
    check(files.reduce((n,f)=>n+f.attachment.length,0)<=512000,'PROJECT_RESULT_SIZE_LIMIT');
    return {summary:result.summary,summary_evidence:reported?'owner_report':'artifact_verified',summary_sha256:summarySha,files:files.map(f=>({name:f.name,encoding:'base64',data:f.attachment.toString('base64'),sha256:digest(f.attachment),bytes:f.attachment.length})),acceptance:'not_evaluated'};
  }
  response(version,current,sources,{replay=false,write=false}={}){
    return {kind:'kotodama.project-owner-view',version:1,authority:'selected_local_project_owner',project:version.project,project_digest:digest(version.project),
      snapshot:replay?'saved_revision':'current',current_revision:current.project.revision,
      source_refs:version.sources.map(ref=>{const observed=sources.find(s=>sourceReference(s.ref)===sourceReference(ref));return {...ref,current_revision:observed.current.revision,freshness:observed.current.revision===ref.revision?'current':'superseded'};}),
      ...(write?{replay,saved_revision:version.project.revision}:{}),task_state_changed:false,execution_authorized:false};
  }
  async handle(raw,{signal,assertScope=()=>{}}={}){
    check(typeof assertScope==='function','PROJECT_SCOPE_GUARD_REQUIRED');
    const input=validateProjectRequest(raw);
    const result=await this.#handle(input,signal,true,assertScope);
    if(['run_task','resume_task'].includes(input.operation)&&!result.replay){
      try{await this.dispatchTask(result.task_ref.task_id,input.actor,{signal,assertCurrent:()=>{this.guard(input,signal);assertScope(this.policy());}});}
      catch(error){return {...result,dispatch:{state:'refused',reason:error.code??'TASK_DISPATCH_FAILED'},owner_state:this.store.taskInternal(result.task_ref.task_id).state};}
      return {...result,execution_authorized:true,dispatch:{state:'admitted'},owner_state:this.store.taskInternal(result.task_ref.task_id).state};
    }
    return result;
  }
  async #handle(input,signal,replayRetry,assertScope){
    // The caller supplies this synchronous surface guard, never request JSON.
    // Keep it scoped to this invocation, including the one bounded replay.
    const guard=(policy=this.policy())=>{this.guard(input,signal,policy);assertScope(policy);signal?.throwIfAborted();};
    guard();
    const policy=await this.readConfig();guard(policy);
    const write=writes.has(input.operation),requestDigest=write?digest(input):null;
    const prior=write?this.store.statement('SELECT * FROM project_requests WHERE actor=? AND request_id=?').get(input.actor,input.request_id):null;
    if(prior)check(prior.request_digest===requestDigest,'PROJECT_REQUEST_CONFLICT');
    const current=prior?this.current(prior.project_id,input.actor):input.operation==='create'?null:this.current(input.project_id,input.actor);
    const saved=prior?this.version(prior.project_id,prior.revision):null;
    let candidate;
    if(!prior&&['inspect','correct'].includes(input.operation))candidate=inspectChange(current.project,{version:1,project_id:input.project_id,
      expected_revision:input.expected_revision,base_digest:input.base_digest,reason:input.reason,source_ref:sourceReference(input.source),brief:input.brief});
    let taskSnapshot,taskLink;
    if(!prior&&['link_task','unlink_task','run_task','resume_task'].includes(input.operation)){
      check(input.expected_revision===current.revision,'PROJECT_REVISION_STALE');check(input.base_digest===digest(current.project),'PROJECT_BASE_MISMATCH');
    }
    if(!prior&&['read_task','read_result','link_task','unlink_task','resume_task'].includes(input.operation)){
      taskLink=current.project.task_refs.find(ref=>ref.task_id===input.task_id);
      if(input.operation!=='link_task')check(taskLink?.adapter==='discord_local_task_v1','PROJECT_TASK_NOT_LINKED');
      if(input.operation==='link_task'){
        check(taskLink||current.project.task_refs.length<50,'PROJECT_TASK_LIMIT');
      }
      if(input.operation!=='unlink_task'){
        taskSnapshot=this.taskSnapshot(input.task_id,input.actor,current.room);
        if(input.operation==='link_task'){check(taskSnapshot.task.revision===input.expected_task_revision,'PROJECT_TASK_REVISION_STALE');check(!taskLink||taskLink.revision!==input.expected_task_revision,'PROJECT_CHANGE_EMPTY');check(taskSnapshot.sources.every(s=>s.current.revision===s.ref.revision),'PROJECT_TASK_SOURCE_CHANGED');}
      }
    }
    if(['run_task','resume_task'].includes(input.operation)){
      check(typeof this.dispatchTask==='function','PROJECT_EXECUTOR_UNAVAILABLE');
      if(!prior)check(this.config.worker.actions.includes(input.task?.action??taskSnapshot.task.action)&&policy.worker.actions.includes(input.task?.action??taskSnapshot.task.action),'ACTION_NOT_ALLOWED');
      if(!prior&&input.operation==='run_task')check(current.project.task_refs.length<50,'PROJECT_TASK_LIMIT');
    }
    const refs=unique([...(current?.sources??[]),...(saved?.sources??[]),...(input.source?[input.source]:[])]);
    const observed=this.sources(refs,input.actor,current?.room),epoch=this.accessEpoch();this.sourceScope(observed,policy);
    if(input.source&&!prior)check(observed.find(s=>sourceReference(s.ref)===sourceReference(input.source)).current.revision===input.source.revision,'SOURCE_CHANGED');
    const allObserved=[...observed,...(taskSnapshot?.sources??[])];this.sourceScope(allObserved,policy);
    for(const {current:source} of [...new Map(allObserved.map(s=>[room(s.current),s])).values()]){
      guard();await this.authorizeSource(source,input.actor,{signal});guard();
    }
    let content;
    if(input.operation==='read_result'){
      check(this.taskView(current,taskLink,taskSnapshot).resolution==='observed','PROJECT_TASK_CHANGED');
      this.assertTaskCurrent(taskSnapshot.task,policy);content=await this.readResult(taskSnapshot.task);guard();
    }
    const final=await this.readConfig();guard(final);
    if(['run_task','resume_task'].includes(input.operation)&&!prior)check(final.worker.actions.includes(input.task?.action??taskSnapshot.task.action),'ACTION_NOT_ALLOWED');this.sourceScope(allObserved,final);check(this.accessEpoch()===epoch,'PROJECT_ACCESS_CHANGED');
    // No await between these final checks and the same-Store transaction.
    try{return this.store.transaction(()=>{
      guard(final);check(this.accessEpoch()===epoch,'PROJECT_ACCESS_CHANGED');
      check(digest(this.sources(refs,input.actor,current?.room))===digest(observed),'PROJECT_SOURCE_CHANGED');
      if(current)check(digest(this.current(current.id,input.actor))===digest(current),'PROJECT_CHANGED');
      if(input.operation==='read_result')this.assertTaskCurrent(taskSnapshot.task,final);
      if(taskSnapshot)check(digest(this.taskSnapshot(input.task_id,input.actor,current.room))===digest(taskSnapshot),'PROJECT_TASK_CHANGED');
      if(prior){const response=this.response(saved,current,observed,{replay:true,write:true});
        return ['run_task','resume_task'].includes(input.operation)?{...response,task_ref:input.operation==='resume_task'?saved.project.task_refs.find(ref=>ref.task_id===input.task_id):saved.project.task_refs.find(ref=>!this.version(prior.project_id,prior.revision-1).project.task_refs.some(old=>old.task_id===ref.task_id)),dispatch:{state:'not_repeated'}}:response;}
      if(input.operation==='read')return this.response({project:current.project,sources:current.sources},current,observed);
      if(input.operation==='read_task')return this.taskView(current,taskLink,taskSnapshot);
      if(input.operation==='read_result'){
        const response={...this.taskView(current,taskLink,taskSnapshot),result:content,result_metadata:{...this.taskView(current,taskLink,taskSnapshot).result_metadata,artifact_readback:'verified'}};
        check(Buffer.byteLength(JSON.stringify(response))<=900000,'PROJECT_RESULT_SIZE_LIMIT');return response;
      }
      if(input.operation==='inspect')return {...candidate,source_refs:refs,task_state_changed:false,execution_authorized:false};
      // A concurrent first delivery may have committed while authorization awaited.
      check(!this.store.statement('SELECT request_digest FROM project_requests WHERE actor=? AND request_id=?').get(input.actor,input.request_id),'PROJECT_CHANGED');
      check(!current||current.project.revision<MAX_VERSIONS,'PROJECT_VERSION_LIMIT');
      const previousTaskLink=taskLink;
      let taskRefs=current?.project.task_refs;
      if(input.operation==='resume_task'){
        check(taskSnapshot.task.revision===input.expected_task_revision,'PROJECT_TASK_REVISION_STALE');
        const b=taskSnapshot.task.projectBinding;
        check(b?.project_id===current.id&&b.contract_digest===digest({brief:current.project.brief,original_ref:current.project.original_ref}),'PROJECT_TASK_CONTRACT_CHANGED');
        check(taskSnapshot.sources.every(s=>s.current.revision===s.ref.revision),'PROJECT_SOURCE_CHANGED');
        const task=this.store.resume(input.task_id,input.actor);
        taskLink={adapter:'discord_local_task_v1',task_id:task.id,revision:task.revision};taskRefs=[...taskRefs.filter(ref=>ref.task_id!==task.id),taskLink];
      }
      if(input.operation==='run_task'){
        // Project history retains original and correction versions. Bind work
        // to the latest explicitly accepted version of each Source, while
        // keeping older text and access dependencies as provenance.
        const latest=new Map();for(const entry of observed){const previous=latest.get(entry.ref.key);if(!previous||previous.ref.revision<entry.ref.revision)latest.set(entry.ref.key,entry);}
        const executionSources=[...latest.values()];
        check(executionSources.every(s=>s.current.revision===s.ref.revision),'PROJECT_SOURCE_CHANGED');
        const sourceHistory=observed.filter(s=>s.ref.revision!==s.current.revision).map(s=>({key:s.ref.key,revision:s.ref.revision,text:s.original.text}));
        const request=input.task.request+'\n\nPROJECT_CONTRACT\n'+JSON.stringify({project_id:current.id,revision:current.revision,brief:current.project.brief,original_ref:current.project.original_ref,source_refs:refs,source_history:sourceHistory});
        text(request,16000,'PROJECT_TASK_INPUT_LIMIT');
        const acceptance=[...new Set([...current.project.brief.acceptance,...input.task.acceptance])];
        check(acceptance.length<=40,'PROJECT_TASK_INPUT_LIMIT');
        const executionRefs=executionSources.map(s=>s.ref);
        const task=this.store.createTask(observed.find(s=>sourceReference(s.ref)===sourceReference(input.source)).current,{...input.task,request,acceptance,
          key:'project:'+input.request_id,contextSources:executionRefs,projectBinding:{project_id:current.id,contract_digest:digest({brief:current.project.brief,original_ref:current.project.original_ref}),sources:executionRefs,source_history:refs}});
        taskLink={adapter:'discord_local_task_v1',task_id:task.id,revision:task.revision};taskRefs=[...taskRefs,taskLink];
      }
      if(input.operation==='link_task')taskRefs=[...taskRefs.filter(ref=>ref.task_id!==input.task_id),{adapter:'discord_local_task_v1',task_id:input.task_id,revision:input.expected_task_revision}];
      if(input.operation==='unlink_task')taskRefs=taskRefs.filter(ref=>ref.task_id!==input.task_id);
      const project=validateProject(current?{...current.project,version:['link_task','run_task','resume_task'].includes(input.operation)?2:current.project.version,revision:current.project.revision+1,
        brief:input.operation==='correct'?input.brief:current.project.brief,task_refs:taskRefs}:{version:1,project_id:`ref/project/${uid('project').slice(8)}`,
        revision:1,owner_ref:`ref/project-owner/${this.config.installation}`,name:input.name,original_ref:sourceReference(input.source),brief:input.brief,task_refs:[]});
      const selectedRoom=current?.room??room(observed[0].original),body=JSON.stringify(project);
      if(current){const changed=this.store.statement('UPDATE projects SET revision=?,body=? WHERE id=? AND revision=?').run(project.revision,body,current.id,current.revision);check(changed.changes===1,'PROJECT_CHANGED');}
      else this.store.statement('INSERT INTO projects VALUES(?,?,?,?,?,?)').run(project.project_id,input.actor,selectedRoom,this.binding,project.revision,body);
      this.store.statement('INSERT INTO project_versions VALUES(?,?,?,?,?)').run(project.project_id,project.revision,body,JSON.stringify(refs),current?digest(current.project):null);
      this.store.statement('INSERT INTO project_requests VALUES(?,?,?,?,?)').run(input.actor,input.request_id,requestDigest,project.project_id,project.revision);
      const eventType={create:'project.created',correct:'project.corrected',link_task:'project.task_linked',unlink_task:'project.task_unlinked',run_task:'project.task_created',resume_task:'project.task_resumed'}[input.operation];
      this.store.event(eventType,{project_id:project.project_id,revision:project.revision,actor:input.actor,request_id:input.request_id,
        source:input.source,original_ref:project.original_ref,previous_digest:current?digest(current.project):null,project_digest:digest(project),
        ...(candidate?{reason:input.reason,changed_fields:candidate.changed_fields,removed_requirements:candidate.removed_requirements,impact_task_refs:candidate.impact_task_refs}:{}),
        ...(input.operation.endsWith('_task')?{reason:input.reason,previous_task_ref:previousTaskLink??null,task_ref:['run_task','resume_task'].includes(input.operation)?taskLink:taskRefs.find(ref=>ref.task_id===input.task_id)??null}:{})});
      const response=this.response({project,sources:refs},{project},observed,{write:true});
      return ['run_task','resume_task'].includes(input.operation)?{...response,task_ref:taskLink,task_state_changed:true}:response;
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
