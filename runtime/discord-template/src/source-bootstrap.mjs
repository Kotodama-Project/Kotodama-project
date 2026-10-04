// Trusted minimal bootstrap: builtins only, before any application src import.
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {lstat,open,opendir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const SOURCE_SET='kotodama.discord-runtime.source-set.v1';
const packageRoot=fileURLToPath(new URL('..',import.meta.url));
const MAX_FILES=5000,MAX_FILE_BYTES=2000000,MAX_ENTRIES=10000,MAX_DEPTH=64,MAX_TOTAL_BYTES=64000000,MAX_BINDING_BYTES=750000,MAX_METADATA_BYTES=1500000;
const refuse=code=>{throw Object.assign(new Error(code),{code});};
const check=(value,code)=>{if(!value)refuse(code);};
const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'?'{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
const digest=value=>createHash('sha256').update(Buffer.isBuffer(value)?value:canonical(value)).digest('hex');
const signature=stat=>[stat.dev,stat.ino,stat.size,stat.mtimeNs,stat.ctimeNs].map(String).join(':');
const identity=stat=>[stat.dev,stat.ino,stat.size,stat.mtimeNs].map(String).join(':');
const regular=stat=>stat.isFile()&&stat.nlink===1n&&stat.size<=BigInt(MAX_FILE_BYTES);
async function entryStat(file){try{return await lstat(file,{bigint:true});}catch(error){if(['ENOENT','ENOTDIR'].includes(error?.code))refuse('SOURCE_FILE_MISSING');throw error;}}
async function hashFile(file,entry){
  let handle;
  try{handle=await open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));}
  catch(error){if(['ELOOP','EMLINK','EFTYPE','EISDIR','ENXIO'].includes(error?.code))refuse('SOURCE_FILE_REFUSED');throw error;}
  try{
    const before=await handle.stat({bigint:true});check(regular(before),'SOURCE_FILE_REFUSED');
    // Path/FD ctime have different meanings on some platforms; compare it
    // within each source, and portable identity across path and descriptor.
    check(identity(entry)===identity(before),'SOURCE_CHANGED_DURING_READ');
    const size=Number(before.size),bytes=Buffer.alloc(size+1);let total=0;
    while(total<bytes.length){const read=await handle.read(bytes,total,bytes.length-total,total);if(!read.bytesRead)break;total+=read.bytesRead;}
    const after=await handle.stat({bigint:true}),current=await entryStat(file);
    check(total===size&&regular(after)&&regular(current)&&signature(before)===signature(after)&&identity(after)===identity(current)&&signature(entry)===signature(current),'SOURCE_CHANGED_DURING_READ');
    return {sha256:digest(bytes.subarray(0,total)),size};
  }finally{await handle.close();}
}
async function collect(root,relative,state,depth=0){
  check(++state.entries<=MAX_ENTRIES&&depth<=MAX_DEPTH,'SOURCE_SET_LIMIT');
  const absolute=path.join(root,...relative.split('/')),stat=await entryStat(absolute);
  check(!stat.isSymbolicLink(),'SOURCE_LINK_REFUSED');const metadata=[relative,signature(stat)];
  state.metadataBytes+=Buffer.byteLength(JSON.stringify(metadata))+1;check(state.metadataBytes<=MAX_METADATA_BYTES,'SOURCE_SET_LIMIT');state.metadata.push(metadata);
  if(stat.isDirectory()){for await(const entry of await opendir(absolute))await collect(root,relative+'/'+entry.name,state,depth+1);return;}
  check(stat.isFile()&&stat.nlink===1n&&stat.size<=BigInt(MAX_FILE_BYTES),'SOURCE_FILE_REFUSED');
  check(state.files.length<MAX_FILES&&state.bytes+Number(stat.size)<=MAX_TOTAL_BYTES,'SOURCE_SET_LIMIT');
  const hashed=await hashFile(absolute,stat),file={path:relative,sha256:hashed.sha256};
  check(state.bytes+hashed.size<=MAX_TOTAL_BYTES,'SOURCE_SET_LIMIT');
  state.bytes+=hashed.size;state.bindingBytes+=Buffer.byteLength(JSON.stringify(file))+1;
  check(state.bindingBytes<=MAX_BINDING_BYTES,'SOURCE_SET_LIMIT');state.files.push(file);
}
export async function sourceSnapshot(root){
  check(typeof root==='string'&&root.length>0,'SOURCE_ROOT_REQUIRED');
  const base=path.resolve(root),stat=await entryStat(base);check(stat.isDirectory(),'SOURCE_ROOT_REQUIRED');
  const files=[],state={files,entries:0,bytes:0,bindingBytes:512,metadataBytes:128,metadata:[['.',signature(stat)]]};
  for(const name of ['bin','src']){check((await entryStat(path.join(base,name))).isDirectory(),'SOURCE_FILE_MISSING');await collect(base,name,state);}
  for(const name of ['package.json','pnpm-lock.yaml']){check((await entryStat(path.join(base,name))).isFile(),'SOURCE_FILE_REFUSED');await collect(base,name,state);}
  files.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);state.metadata.sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0);
  const find=name=>files.find(file=>file.path===name).sha256;
  const binding=Object.freeze({set:SOURCE_SET,setDigest:digest({set:SOURCE_SET,files}),packageDigest:find('package.json'),lockDigest:find('pnpm-lock.yaml'),fileCount:files.length,files:Object.freeze(files.map(file=>Object.freeze(file)))});
  return {binding,metadataDigest:digest(state.metadata)};
}

const bindings=new WeakMap();let runtimeModule,loading;
const unverified=error=>Object.freeze({set:SOURCE_SET,error});
// Called at actual runtime module evaluation, never by a caller-supplied record.
export function registerRuntimeModule(start,url){
  if(url!==new URL('./runtime.mjs',import.meta.url).href||runtimeModule)return;
  runtimeModule=start;if(loading)loading.runtime=start;
}
export function consumeBootstrapBinding(token,start){
  const record=token&&typeof token==='object'?bindings.get(token):undefined;
  if(!record||record.start!==start)return unverified('SOURCE_BOOTSTRAP_REQUIRED');
  bindings.delete(token);return record.source;
}
export async function bootstrapCLI(load){
  // A fresh, directly launched CLI is the trust boundary. Preloads and cached
  // application imports cannot establish the order of acquisition and loading.
  const official=process.argv[1]&&path.resolve(process.argv[1])===path.join(packageRoot,'bin','kotodama.mjs')&&process.execArgv.length===0&&!process.env.NODE_OPTIONS?.trim();
  let source=unverified('SOURCE_BOOTSTRAP_REQUIRED'),before;
  if(official&&process.platform==='win32')source=unverified('SOURCE_BOOTSTRAP_UNSUPPORTED');
  else if(official&&!runtimeModule){
    try{before=await sourceSnapshot(packageRoot);}catch(error){source=unverified(/^SOURCE_[A-Z_]+$/.test(error?.code??'')?error.code:'SOURCE_BINDING_FAILED');}
  }
  const attempt={};loading=before?attempt:undefined;
  let modules;try{modules=await load();}finally{loading=undefined;}
  if(before&&attempt.runtime===modules.startRuntime){
    try{
      const after=await sourceSnapshot(packageRoot);
      source=before.binding.setDigest===after.binding.setDigest&&before.metadataDigest===after.metadataDigest?Object.freeze({...before.binding,boundAt:new Date().toISOString()}):unverified('SOURCE_CHANGED_DURING_STARTUP');
    }catch{source=unverified('SOURCE_CHANGED_DURING_STARTUP');}
  }
  const token=Object.freeze({});bindings.set(token,{start:modules.startRuntime,source});
  return {...modules,sourceBootstrap:token};
}
