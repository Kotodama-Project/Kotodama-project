import {check,Refused} from './common.mjs';

/** Private service contract. A remote owner replaces, never mirrors, local Tasks. */
export class RemoteOwner {
  constructor(config){this.kind='remote';this.url=new URL(config.url);check(this.url.protocol==='https:'||(this.url.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(this.url.hostname)),'OWNER_TRANSPORT_REFUSED');this.token=process.env[config.tokenEnv];check(this.token,'OWNER_CREDENTIAL_REQUIRED');}
  async call(method,args){const response=await fetch(new URL('/v1/owner',this.url),{method:'POST',redirect:'error',signal:AbortSignal.timeout(15000),headers:{authorization:'Bearer '+this.token,'content-type':'application/json'},body:JSON.stringify({version:1,method,args})});check(response.ok,'REMOTE_OWNER_REFUSED');const text=await response.text();check(Buffer.byteLength(text)<=4000000,'OWNER_RESPONSE_LIMIT');const value=JSON.parse(text);check(value.version===1&&value.ok===true,'OWNER_PROTOCOL_MISMATCH');return value.result;}
}
for(const method of ['ingest','source','createTask','reviseTask','task','taskInternal','tasks','claim','finish','cancel','resume','confirmStop','bindContext','assertContext'])RemoteOwner.prototype[method]=function(...args){return this.call(method,args);};
