import {TextDecoder} from 'node:util';
import {readArtifact} from './artifact.mjs';
import {runWorkspaceGit} from './workspace-git.mjs';
import {check,digest,safePath,Refused} from './common.mjs';

export const PROJECT_SKILL_ACTIONS=Object.freeze(['research','summarize','develop','write_file']);
export const PROJECT_SKILL_NAME=/^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const MAX_PROJECT_SKILLS=4;
export const MAX_PROJECT_SKILL_BYTES=65536;
export const MAX_PROJECT_SKILL_TOTAL_BYTES=131072;
const MAX_RENDERED_BYTES=262144;
const utf8=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true});

// Operator configuration selects methods. Neither Task text nor a retrieved
// document can add names or grant an action. Empty and absent maps are equivalent.
export function normalizeProjectSkills(value){
  const map=value===undefined?{}:value;
  check(map&&typeof map==='object'&&!Array.isArray(map)&&Object.keys(map).every(key=>PROJECT_SKILL_ACTIONS.includes(key)),'PROJECT_SKILL_CONFIG_INVALID');
  return Object.fromEntries(PROJECT_SKILL_ACTIONS.map(action=>{
    const names=Object.hasOwn(map,action)?map[action]:[];
    check(Array.isArray(names)&&names.length<=MAX_PROJECT_SKILLS&&names.every(name=>typeof name==='string'&&name.length<=64&&PROJECT_SKILL_NAME.test(name)),'PROJECT_SKILL_CONFIG_INVALID');
    check(new Set(names).size===names.length,'PROJECT_SKILL_DUPLICATE');
    return [action,[...names]];
  }));
}
export const projectSkillsDigest=value=>digest(normalizeProjectSkills(value));

export function projectSkillActions(action,requiredActions){
  check(PROJECT_SKILL_ACTIONS.includes(action),'PROJECT_SKILL_ACTION_INVALID');
  const required=requiredActions===undefined?[]:requiredActions;
  check(Array.isArray(required)&&required.length<=PROJECT_SKILL_ACTIONS.length&&required.every(value=>PROJECT_SKILL_ACTIONS.includes(value)),'PROJECT_SKILL_REQUIRED_ACTIONS_INVALID');
  return [...new Set([action,...required])];
}

async function git(workspace,args,signal,input=''){
  const result=await runWorkspaceGit(args,{cwd:workspace,signal,input,timeoutMs:15000,maxBytes:4096});
  check(result.code===0,'PROJECT_SKILL_GIT_REQUIRED');return result.stdout;
}
async function head(workspace,signal){
  check((await git(workspace,['rev-parse','--show-prefix'],signal)).trim()==='','PROJECT_SKILL_REPOSITORY_ROOT_REQUIRED');
  const revision=(await git(workspace,['rev-parse','--verify','HEAD'],signal)).trim();
  check(/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(revision),'PROJECT_SKILL_REVISION_INVALID');return revision;
}
function nonemptyDescription(raw){
  const scalar=raw.trim();let value;
  if(scalar.startsWith('"')){
    const match=/^("(?:[^"\\]|\\.)*")(?:[ \t]+#.*)?$/.exec(scalar);if(!match)return false;
    try{value=JSON.parse(match[1]);}catch{return false;}
  }else if(scalar.startsWith("'")){
    const match=/^'((?:[^']|'')*)'(?:[ \t]+#.*)?$/.exec(scalar);if(!match)return false;
    value=match[1].replaceAll("''","'");
  }else{
    value=scalar.replace(/[ \t]+#.*$/,'').trim();
    // Support ordinary single-line strings, not YAML collections, tags,
    // aliases, block scalars, or implicit null/boolean/number values.
    if(/^[#\[\]{}&*!|>@%`]/.test(value)||/^[-?:](?:[ \t]|$)/.test(value)||/:(?:[ \t]|$)/.test(value))return false;
    if(/^(?:~|null|true|false|yes|no|on|off)$/i.test(value))return false;
    if(/^[+-]?(?:\d[\d_]*(?:\.[\d_]*)?(?:e[+-]?[\d_]+)?|\.[\d_]+(?:e[+-]?[\d_]+)?|0[xob][a-f0-9_]+|\.inf|\.nan)$/i.test(value))return false;
  }
  return typeof value==='string'&&value.isWellFormed()&&value.trim().length>0;
}
function manifest(text,name){
  const match=/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text);
  check(match&&!text.includes('\0'),'PROJECT_SKILL_MANIFEST_INVALID');
  const lines=match[1].split(/\r?\n/),names=lines.filter(line=>/^name\s*:/.test(line)),descriptions=lines.filter(line=>/^description\s*:/.test(line));
  check(names.length===1&&descriptions.length===1,'PROJECT_SKILL_MANIFEST_INVALID');
  const declared=/^name:[ \t]*(?:'([^']+)'|"([^"]+)"|([^ \t]+))[ \t]*$/.exec(names[0]);
  check(declared&&(declared[1]??declared[2]??declared[3])===name&&/^description:[ \t]*\S/.test(descriptions[0]),'PROJECT_SKILL_MANIFEST_INVALID');
  check(nonemptyDescription(descriptions[0].slice('description:'.length)),'PROJECT_SKILL_MANIFEST_INVALID');
}
async function committedSkill(workspace,revision,name,signal){
  const relative=`.agents/skills/${name}/SKILL.md`;
  // Only the declared ASCII path is looked up; no catalog enumeration or
  // Markdown link/dependency traversal occurs.
  const entry=await git(workspace,['ls-tree','-z',revision,'--',relative],signal);
  const match=/^(100644|100755) blob ([a-f0-9]{40}|[a-f0-9]{64})\t([^\0]+)\0$/.exec(entry);
  check(match&&match[3]===relative,'PROJECT_SKILL_NOT_COMMITTED');
  let bytes;
  try{
    const file=await safePath(workspace,relative);bytes=await readArtifact(file,MAX_PROJECT_SKILL_BYTES);
    check(file===await safePath(workspace,relative),'PROJECT_SKILL_CHANGED');
  }catch(error){
    if(error?.code==='CANCELLED')throw error;
    throw new Refused('PROJECT_SKILL_FILE_REFUSED');
  }
  check(bytes.length>0,'PROJECT_SKILL_MANIFEST_INVALID');
  const blob=(await git(workspace,['hash-object','--no-filters','--stdin'],signal,bytes)).trim();
  check(blob===match[2],'PROJECT_SKILL_UNCOMMITTED');
  let text;try{text=utf8.decode(bytes);}catch{throw new Refused('PROJECT_SKILL_UTF8_INVALID');}
  check(Buffer.from(text,'utf8').equals(bytes),'PROJECT_SKILL_UTF8_INVALID');manifest(text,name);
  return {name,sha256:digest(bytes),bytes:bytes.length,text};
}

export async function loadProjectSkillInput({workspace,projectSkills,action,requiredActions,signal,expectedRevision=null}){
  const selectedActions=projectSkillActions(action,requiredActions),selected=normalizeProjectSkills(projectSkills);
  const names=[...new Set(selectedActions.flatMap(selectedAction=>selected[selectedAction]))];
  const configSha256=digest(selected);
  if(!names.length)return {receipt:{version:1,selection:'operator_action_config',action,selectedActions,configSha256,sourceRevision:null,skills:[],totalBytes:0},section:''};
  const sourceRevision=await head(workspace,signal);
  check(expectedRevision===null||sourceRevision===expectedRevision,'PROJECT_SKILL_REVISION_CHANGED');
  const skills=[];let totalBytes=0;
  for(const name of names){
    check(!signal?.aborted,'CANCELLED');const skill=await committedSkill(workspace,sourceRevision,name,signal);
    totalBytes+=skill.bytes;check(totalBytes<=MAX_PROJECT_SKILL_TOTAL_BYTES,'PROJECT_SKILL_TOTAL_LIMIT');skills.push(skill);
  }
  check(await head(workspace,signal)===sourceRevision,'PROJECT_SKILL_REVISION_CHANGED');
  const packet={selection:'operator_action_config',authority:'method_only',action,selectedActions,sourceRevision,skills};
  const section='\nPROJECT_SKILLS\n'+JSON.stringify(packet);
  check(Buffer.byteLength(section,'utf8')<=MAX_RENDERED_BYTES,'PROJECT_SKILL_INPUT_LIMIT');
  const receipt={version:1,selection:packet.selection,action,selectedActions,configSha256,sourceRevision,skills:skills.map(({name,sha256,bytes})=>({name,sha256,bytes})),totalBytes};
  return {receipt,section};
}

export async function assertProjectSkillInputCurrent(input,options){
  check(projectSkillsDigest(options.projectSkills)===input.receipt.configSha256,'PROJECT_SKILL_CONFIG_CHANGED');
  const current=await loadProjectSkillInput({...options,expectedRevision:input.receipt.sourceRevision});
  check(digest(current.receipt)===digest(input.receipt),'PROJECT_SKILL_CHANGED');
}
