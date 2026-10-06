import {check,digest,Refused} from './common.mjs';
import {awaitWithSignal,deadlineScope} from './http-limits.mjs';

const methods=['ingest','source','createTask','reviseTask','task','taskInternal','tasks','claim','finish','cancel','cancelQueued','resume','confirmStop','bindContext','assertContext'];
const reads=new Set(['source','task','taskInternal','tasks','assertContext']);
const defaults={maxConcurrent:8,maxRequestBytes:4000000,maxResponseBytes:4000000,timeoutMs:15000,drainTimeoutMs:15000};

async function readLimitedText(response,maxBytes,signal){
  check(response.body?.getReader,'OWNER_RESPONSE_INVALID');const reader=response.body.getReader(),chunks=[];let size=0,cancelling;
  const cancel=()=>cancelling??=Promise.resolve().then(()=>reader.cancel()).catch(()=>{});
  const abort=()=>{void cancel();};signal.addEventListener('abort',abort,{once:true});
  try{
    const length=response.headers?.get('content-length');check(length==null||/^\d+$/.test(length)&&Number(length)<=maxBytes,'OWNER_RESPONSE_LIMIT');
    while(true){signal.throwIfAborted();const {value,done}=await reader.read();signal.throwIfAborted();if(done)break;const bytes=Buffer.from(value);size+=bytes.length;check(size<=maxBytes,'OWNER_RESPONSE_LIMIT');chunks.push(bytes);}
    return Buffer.concat(chunks,size).toString('utf8');
  }catch(error){await cancel();throw error;}finally{signal.removeEventListener('abort',abort);reader.releaseLock?.();}
}

/** Private service contract. A remote owner replaces, never mirrors, local Tasks. */
export class RemoteOwner {
  constructor(config,limits={}){
    this.kind='remote';this.url=new URL(config.url);check(this.url.protocol==='https:'||(this.url.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(this.url.hostname)),'OWNER_TRANSPORT_REFUSED');
    this.token=process.env[config.tokenEnv];check(this.token,'OWNER_CREDENTIAL_REQUIRED');this.limits={...defaults,...limits};for(const value of Object.values(this.limits))check(Number.isSafeInteger(value)&&value>0,'OWNER_LIMIT_INVALID');
    this.pending=new Set();this.stopping=false;
  }
  async call(method,args){
    check(!this.stopping,'OWNER_STOPPING');check(methods.includes(method)&&Array.isArray(args),'OWNER_METHOD_INVALID');check(this.pending.size<this.limits.maxConcurrent,'OWNER_BUSY');
    let body;try{body=JSON.stringify({version:1,method,args});}catch{throw new Refused('OWNER_REQUEST_INVALID');}check(Buffer.byteLength(body)<=this.limits.maxRequestBytes,'OWNER_REQUEST_LIMIT');
    const requestDigest=digest(body);check(reads.has(method)||![...this.pending].some(entry=>entry.requestDigest===requestDigest),'OWNER_WRITE_PENDING');
    const deadline=deadlineScope(this.limits.timeoutMs,'OWNER_TIMEOUT'),entry={deadline,requestDigest,dispatched:false,refused:false};this.pending.add(entry);
    const work=Promise.resolve().then(async()=>{
      deadline.signal.throwIfAborted();entry.dispatched=true;
      const response=await fetch(new URL('/v1/owner',this.url),{method:'POST',redirect:'error',signal:deadline.signal,headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},body});
      if(!response.ok||deadline.signal.aborted){entry.refused=!response.ok&&response.status>=400&&response.status<500;try{await response.body?.cancel();}catch{}deadline.signal.throwIfAborted();throw new Refused('REMOTE_OWNER_REFUSED');}
      const text=await readLimitedText(response,this.limits.maxResponseBytes,deadline.signal);deadline.signal.throwIfAborted();
      let value;try{value=JSON.parse(text);}catch{throw new Refused('OWNER_PROTOCOL_MISMATCH');}check(value?.version===1&&value.ok===true,'OWNER_PROTOCOL_MISMATCH');return value.result;
    });
    entry.work=work;const finish=()=>{this.pending.delete(entry);deadline.dispose();};work.then(finish,finish);
    try{return await awaitWithSignal(work,deadline.signal);}catch(error){
      if(entry.dispatched&&!reads.has(method)&&!entry.refused)throw new Refused('OWNER_RESULT_UNCERTAIN');throw error;
    }
  }
  async close(){
    this.stopping=true;for(const {deadline} of this.pending)deadline.abort(new Refused('OWNER_STOPPING'));
    const deadline=deadlineScope(this.limits.drainTimeoutMs,'OWNER_DRAIN_UNCERTAIN');
    try{await awaitWithSignal(Promise.all([...this.pending].map(({work})=>work.catch(()=>{}))),deadline.signal);}finally{deadline.dispose();}
  }
}
for(const method of methods)RemoteOwner.prototype[method]=function(...args){return this.call(method,args);};
