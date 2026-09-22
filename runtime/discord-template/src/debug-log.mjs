import {openSync,fstatSync,fchmodSync,writeSync,closeSync,renameSync,mkdirSync,constants} from 'node:fs';
import path from 'node:path';
import {redact,setErrorHook} from './common.mjs';

// Opt-in local diagnostics. Discord replies and the normal log keep only the
// classified code; this file keeps the redacted name, message, stack and the
// place where an unexpected error was classified as OPERATION_FAILED.
export const debugRequested=({verbose=false,env=process.env}={})=>verbose===true||/^(1|true|yes|on)$/i.test(env.KOTODAMA_DEBUG??'');

// Error text can come from network peers. Besides redaction and JSON escaping,
// drop characters that change how a log line is displayed (C1 controls,
// zero-width and bidirectional formatting marks).
const invisible=/[\u0080-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
const text=(value,max)=>redact(String(value)).replace(invisible,'\ufffd').slice(0,max);
export function describeError(error,where=null){
  const entry={at:new Date().toISOString(),where:where?text(where,500):null,name:typeof error?.name==='string'?error.name.slice(0,100):typeof error};
  if(typeof error?.code==='string'||Number.isInteger(error?.code))entry.code=typeof error.code==='string'?error.code.slice(0,100):error.code;
  if(error?.name==='ZodError'&&Array.isArray(error.issues)){
    // Paths and schema expectations only: configured values are never copied.
    entry.issues=error.issues.slice(0,50).map(issue=>({path:(issue.path??[]).map(String).join('.')||'(root)',code:String(issue.code??'invalid'),...(typeof issue.expected==='string'?{expected:issue.expected}:{}),...(Array.isArray(issue.keys)?{keys:issue.keys.slice(0,20).map(String)}:{})}));
    return entry;
  }
  entry.message=text(error?.message??error,2000);
  if(typeof error?.stack==='string')entry.stack=text(error.stack.split('\n').slice(0,20).join('\n'),6000);
  if(error?.cause)entry.cause={name:typeof error.cause?.name==='string'?error.cause.name.slice(0,100):typeof error.cause,message:text(error.cause?.message??error.cause,500)};
  return entry;
}

export class DebugLog{
  constructor(dir,{maxBytes=1048576}={}){this.file=path.join(dir,'debug.log');this.maxBytes=maxBytes;this.seen=new WeakSet();}
  record(error,where){
    if(error&&typeof error==='object'){if(this.seen.has(error))return false;this.seen.add(error);}
    try{
      const line=JSON.stringify(describeError(error,where))+'\n';
      mkdirSync(path.dirname(this.file),{recursive:true,mode:0o700});
      // Open first and inspect the descriptor; never follow a link or write
      // into a file that has another name.
      const append=()=>openSync(this.file,constants.O_WRONLY|constants.O_APPEND|constants.O_CREAT|(constants.O_NOFOLLOW??0),0o600);
      let fd=append();
      try{
        let opened=fstatSync(fd);if(!opened.isFile()||opened.nlink!==1)return false;
        if(opened.size>0&&opened.size+Buffer.byteLength(line)>this.maxBytes){closeSync(fd);fd=null;renameSync(this.file,this.file+'.1');fd=append();opened=fstatSync(fd);if(!opened.isFile()||opened.nlink!==1)return false;}
        if(process.platform!=='win32'&&(opened.mode&0o077))fchmodSync(fd,0o600);
        writeSync(fd,line);return true;
      }finally{if(fd!==null)closeSync(fd);}
    }catch{return false;}
  }
}

export function enableDebugLog(dir,options){const log=new DebugLog(dir,options);setErrorHook((error,where)=>log.record(error,where));return log;}
export function disableDebugLog(){setErrorHook(null);}
