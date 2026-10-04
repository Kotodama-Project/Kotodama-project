import {lstat,opendir} from 'node:fs/promises';
import path from 'node:path';
import {readArtifact} from './artifact.mjs';
import {check,digest,Refused} from './common.mjs';

// The source set is the bytes the runtime loads: every regular file below bin/
// and src/, plus package.json and pnpm-lock.yaml. node_modules is bound only
// through the lock digest. Paths are POSIX-style and relative to the root, so a
// binding never carries an absolute path.
export const SOURCE_SET='kotodama.discord-runtime.source-set.v1';
export const DEFAULT_MAX_AGE_MS=60000;
const DIRECTORIES=['bin','src'],FILES=['package.json','pnpm-lock.yaml'];
const MAX_FILES=5000,MAX_FILE_BYTES=2000000,MAX_LISTED_PATHS=200;
// Keep the new status field below the existing 1 MB control response limit.
const MAX_ENTRIES=10000,MAX_DEPTH=64,MAX_TOTAL_BYTES=64000000,MAX_BINDING_BYTES=750000;
const HEX=/^[a-f0-9]{64}$/,RELATIVE=/^(?:bin|src)\/[^\0\\]+$|^package\.json$|^pnpm-lock\.yaml$/;
const setDigest=files=>digest({set:SOURCE_SET,files});

async function entryStat(file){
  try{return await lstat(file);}catch(error){if(error?.code==='ENOENT'||error?.code==='ENOTDIR')throw new Refused('SOURCE_FILE_MISSING');throw error;}
}
async function hashFile(file){
  try{const bytes=await readArtifact(file,MAX_FILE_BYTES);return {sha256:digest(bytes),size:bytes.length};}
  catch(error){if(error?.code==='ENOENT')throw new Refused('SOURCE_FILE_MISSING');if(error instanceof Refused)throw new Refused(error.code==='ARTIFACT_CHANGED'?'SOURCE_CHANGED_DURING_READ':'SOURCE_FILE_REFUSED');throw error;}
}
async function collect(root,relative,state,depth=0){
  check(++state.entries<=MAX_ENTRIES&&depth<=MAX_DEPTH,'SOURCE_SET_LIMIT');
  const absolute=path.join(root,...relative.split('/')),stat=await entryStat(absolute);
  check(!stat.isSymbolicLink(),'SOURCE_LINK_REFUSED');
  if(stat.isDirectory()){for await(const entry of await opendir(absolute))await collect(root,relative+'/'+entry.name,state,depth+1);return;}
  check(stat.isFile(),'SOURCE_FILE_REFUSED');check(state.files.length<MAX_FILES,'SOURCE_SET_LIMIT');
  check(stat.size<=MAX_FILE_BYTES,'SOURCE_FILE_REFUSED');
  check(state.bytes+stat.size<=MAX_TOTAL_BYTES,'SOURCE_SET_LIMIT');
  const hashed=await hashFile(absolute),file={path:relative,sha256:hashed.sha256};
  check(state.bytes+hashed.size<=MAX_TOTAL_BYTES,'SOURCE_SET_LIMIT');
  state.bytes+=hashed.size;state.bindingBytes+=Buffer.byteLength(JSON.stringify(file))+1;
  check(state.bindingBytes<=MAX_BINDING_BYTES,'SOURCE_SET_LIMIT');state.files.push(file);
}

// Hash the source set below root. Links, non-regular files, hard-linked files
// and oversized files are refused rather than skipped.
export async function computeSourceBinding(root){
  check(typeof root==='string'&&root.length>0,'SOURCE_ROOT_REQUIRED');
  const base=path.resolve(root);check((await entryStat(base)).isDirectory(),'SOURCE_ROOT_REQUIRED');
  const files=[],state={files,entries:0,bytes:0,bindingBytes:512};
  for(const name of DIRECTORIES){check((await entryStat(path.join(base,name))).isDirectory(),'SOURCE_FILE_MISSING');await collect(base,name,state);}
  for(const name of FILES){check((await entryStat(path.join(base,name))).isFile(),'SOURCE_FILE_REFUSED');await collect(base,name,state);}
  files.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
  const find=name=>files.find(file=>file.path===name).sha256;
  return Object.freeze({set:SOURCE_SET,setDigest:setDigest(files),packageDigest:find('package.json'),lockDigest:find('pnpm-lock.yaml'),fileCount:files.length,files:Object.freeze(files.map(file=>Object.freeze(file)))});
}

// Bind the running process once, at start. A binding that cannot be made is
// reported as an error code, so the readback stays unverified instead of
// falling back to the disk.
export async function bindRuntimeSource(root){
  try{return Object.freeze({...await computeSourceBinding(root),boundAt:new Date().toISOString()});}
  catch(error){return Object.freeze({set:SOURCE_SET,error:error instanceof Refused?error.code:'SOURCE_BINDING_FAILED'});}
}

const summary=binding=>binding?{setDigest:binding.setDigest,packageDigest:binding.packageDigest,lockDigest:binding.lockDigest,fileCount:binding.fileCount}:null;
function consistent(binding){
  if(!binding||binding.set!==SOURCE_SET||!Array.isArray(binding.files)||binding.files.length>MAX_FILES||![binding.setDigest,binding.packageDigest,binding.lockDigest].every(value=>typeof value==='string'&&HEX.test(value)))return false;
  let previous='';
  for(const file of binding.files){if(!file||typeof file.path!=='string'||!RELATIVE.test(file.path)||file.path.split('/').some(part=>part===''||part==='.'||part==='..')||!HEX.test(file.sha256??'')||file.path<=previous)return false;previous=file.path;}
  const find=name=>binding.files.find(file=>file.path===name)?.sha256;
  return binding.setDigest===setDigest(binding.files.map(({path,sha256})=>({path,sha256})))&&binding.packageDigest===find('package.json')&&binding.lockDigest===find('pnpm-lock.yaml')&&binding.fileCount===binding.files.length&&typeof binding.boundAt==='string'&&Number.isFinite(Date.parse(binding.boundAt));
}
function differingPaths(a,b){
  const left=new Map(a.files.map(file=>[file.path,file.sha256])),right=new Map(b.files.map(file=>[file.path,file.sha256]));
  return [...new Set([...left.keys(),...right.keys()])].filter(name=>left.get(name)!==right.get(name)).sort().slice(0,MAX_LISTED_PATHS);
}

// Parity is "match" only when the candidate, the disk and a fresh, instance-
// checked live readback all carry the same source set. Any pair that differs is
// a mismatch. Anything missing, stale or inconsistent is "unverified".
export function compareParity({candidate=null,disk=null,instance=null,now=Date.now(),maxAgeMs=DEFAULT_MAX_AGE_MS}={}){
  const reasons=[];let live=null;
  if(!candidate)reasons.push('CANDIDATE_REQUIRED');
  if(!disk)reasons.push('DISK_REQUIRED');
  if(!instance)reasons.push('RUNTIME_NOT_AVAILABLE');
  else if(instance.error)reasons.push(typeof instance.error==='string'&&/^[A-Z_]{1,64}$/.test(instance.error)?instance.error:'RUNTIME_NOT_AVAILABLE');
  else if(!instance.source||instance.source.error||instance.source.set!==SOURCE_SET)reasons.push('INSTANCE_BINDING_MISSING');
  else if(!consistent(instance.source))reasons.push('INSTANCE_BINDING_INVALID');
  else{const at=Date.parse(instance.readAt);if(!Number.isFinite(at)||at>now||now-at>maxAgeMs)reasons.push('STALE_READBACK');else live=instance.source;}
  const paths={};let differs=false;
  for(const [code,key,a,b] of [['INSTANCE_DISK_DIFFERS','instanceDisk',live,disk],['INSTANCE_CANDIDATE_DIFFERS','instanceCandidate',live,candidate],['CANDIDATE_DISK_DIFFERS','candidateDisk',candidate,disk]]){
    if(!a||!b||a.setDigest===b.setDigest)continue;differs=true;reasons.push(code);paths[key]=differingPaths(a,b);
  }
  return {parity:differs?'mismatch':reasons.length?'unverified':'match',reasons,differingPaths:paths,instance:live?{...summary(live),boundAt:live.boundAt}:null};
}

// Compare the candidate directory, the disk and the running instance. The
// instance is read only through readStatus (the authenticated, instance-checked
// local control); saved reports are not accepted. The result carries digests,
// times and relative paths only: no PID, owner id, port, absolute path or
// configuration value.
export async function integrityReport({diskRoot,candidateRoot,revision,readStatus,now=()=>Date.now(),maxAgeMs=DEFAULT_MAX_AGE_MS}){
  if(revision!==undefined)check(typeof revision==='string'&&/^[0-9a-f]{7,64}$/.test(revision),'REVISION_INVALID');
  check(typeof readStatus==='function','RUNTIME_NOT_AVAILABLE');
  const disk=await computeSourceBinding(diskRoot);
  const candidate=candidateRoot===undefined?null:await computeSourceBinding(candidateRoot);
  let instance,readAt=null;
  try{const status=await readStatus();readAt=new Date(now()).toISOString();instance={source:status?.source,readAt};}
  catch(error){instance={error:error instanceof Refused?error.code:'RUNTIME_NOT_AVAILABLE'};}
  const result=compareParity({candidate,disk,instance,now:now(),maxAgeMs});
  return {sourceSet:SOURCE_SET,parity:result.parity,reasons:result.reasons,differingPaths:result.differingPaths,revision:revision===undefined?null:{value:revision,checkedByTool:false},candidate:summary(candidate),disk:summary(disk),instance:result.instance,readAt};
}
