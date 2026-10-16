import {check,digest} from './common.mjs';

export const BRIEF_FIELDS=['outcome','in_scope','out_of_scope','constraints','acceptance','unknowns'];
const PROJECT_FIELDS=['version','project_id','revision','owner_ref','name','original_ref','brief','task_refs'];
const taskId=/^task-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function validateTaskId(value){check(typeof value==='string'&&taskId.test(value),'PROJECT_TASK_INVALID');}
const hash=/^[a-f0-9]{64}$/;
// Match Python str.strip(), including its additional ASCII separators.
const whitespace=/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
export function shape(value,fields,code){check(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===fields.length&&fields.every(k=>Object.hasOwn(value,k)),code);}
export function text(value,limit,code){check(typeof value==='string'&&value.isWellFormed()&&!value.includes('\0')&&!whitespace.test(value)&&Array.from(value).length<=limit,code);}
export function reference(value,code='PROJECT_REFERENCE_INVALID'){check(typeof value==='string'&&value.length>0&&value.isWellFormed()&&Array.from(value).length<=256&&!/[\x00-\x1f]/.test(value),code);}
export function revision(value,minimum=1){check(Number.isSafeInteger(value)&&value>=minimum,'PROJECT_REVISION_INVALID');}
export function validateSource(value){shape(value,['key','revision'],'PROJECT_SOURCE_INVALID');check(typeof value.key==='string'&&hash.test(value.key),'PROJECT_SOURCE_INVALID');revision(value.revision,0);return {...value};}
export const sourceReference=source=>`ref/source/${source.key}/${source.revision}`;
export function validateBrief(brief){
  shape(brief,BRIEF_FIELDS,'PROJECT_BRIEF_INVALID');text(brief.outcome,4000,'PROJECT_OUTCOME_INVALID');
  for(const field of BRIEF_FIELDS.slice(1)){
    check(Array.isArray(brief[field])&&brief[field].length<=20,'PROJECT_BRIEF_INVALID');
    for(const item of brief[field])text(item,1000,'PROJECT_BRIEF_INVALID');
    check(new Set(brief[field]).size===brief[field].length,'PROJECT_BRIEF_DUPLICATE');
  }
  return structuredClone(brief);
}

/** Versioned references distinguish an owner Task from a swarm execution input. */
export function validateProject(project){
  shape(project,PROJECT_FIELDS,'PROJECT_INVALID');check([1,2].includes(project.version),'PROJECT_VERSION_INVALID');
  for(const field of ['project_id','owner_ref','original_ref'])reference(project[field]);
  revision(project.revision);text(project.name,200,'PROJECT_NAME_INVALID');validateBrief(project.brief);
  check(Array.isArray(project.task_refs)&&project.task_refs.length<=50,'PROJECT_TASK_LIMIT');const seen=new Set();
  for(const task of project.task_refs){
    const local=project.version===2&&task?.adapter==='discord_local_task_v1';
    if(project.version===2)check(['discord_local_task_v1','swarm_execution_v1'].includes(task?.adapter),'PROJECT_TASK_ADAPTER_INVALID');
    shape(task,local?['adapter','task_id','revision']:[...(project.version===2?['adapter']:[]),'task_id','owner_ref','revision','context_digest'],'PROJECT_TASK_INVALID');
    validateTaskId(task.task_id);
    check(!seen.has(task.task_id),'PROJECT_TASK_DUPLICATE');seen.add(task.task_id);
    revision(task.revision);if(!local){reference(task.owner_ref);check(typeof task.context_digest==='string'&&hash.test(task.context_digest),'PROJECT_CONTEXT_INVALID');}
  }
  return structuredClone(project);
}

export function inspectChange(project,proposal){
  project=validateProject(project);
  shape(proposal,['version','project_id','expected_revision','base_digest','reason','source_ref','brief'],'PROJECT_CHANGE_INVALID');
  check(proposal.version===1,'PROJECT_CHANGE_INVALID');revision(proposal.expected_revision);
  check(proposal.project_id===project.project_id,'PROJECT_ID_MISMATCH');
  check(proposal.expected_revision===project.revision,'PROJECT_REVISION_STALE');
  check(proposal.base_digest===digest(project),'PROJECT_BASE_MISMATCH');
  text(proposal.reason,1000,'PROJECT_CHANGE_REASON_INVALID');reference(proposal.source_ref);validateBrief(proposal.brief);
  const changed=BRIEF_FIELDS.filter(k=>digest(proposal.brief[k])!==digest(project.brief[k])).sort();
  check(changed.length>0,'PROJECT_CHANGE_EMPTY');
  return {kind:'kotodama.project-change-candidate',version:1,authority:'candidate_only',project_id:project.project_id,
    expected_revision:project.revision,base_digest:digest(project),proposal_digest:digest(proposal),proposal:structuredClone(proposal),
    changed_fields:changed,removed_requirements:Object.fromEntries(['constraints','acceptance'].map(k=>[k,project.brief[k].filter(item=>!proposal.brief[k].includes(item))])),
    impact_task_refs:project.task_refs,applied:false,next_action:'owner_revalidate_authorize_and_record_correction'};
}
