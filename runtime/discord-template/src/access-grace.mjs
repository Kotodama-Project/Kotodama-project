import {Refused} from './common.mjs';
import {awaitWithSignal,deadlineScope} from './http-limits.mjs';

// A transient Discord failure (rate limit, server error, timeout, transport
// error) does not prove that access was revoked. A running Task survives only a
// short, counted window of such failures; a definitive denial or any other
// failure still stops it at once. The window starts when the first failing
// check started, so a slow failure counts against it.
export class AccessGrace{
  constructor({graceMs=5000,maxUnavailable=3,now=()=>Date.now()}={}){Object.assign(this,{graceMs,maxUnavailable,now});this.pending=new Map();}
  tolerate(id,error,startedAt=this.now()){
    if(error?.code!=='ACCESS_UNAVAILABLE'){this.pending.delete(id);return false;}
    const entry=this.pending.get(id)??{since:startedAt,count:0};entry.count++;
    if(entry.count>this.maxUnavailable||this.now()-entry.since>this.graceMs){this.pending.delete(id);return false;}
    this.pending.set(id,entry);return true;
  }
  clear(id){this.pending.delete(id);}
  retain(ids){const keep=new Set(ids);for(const id of this.pending.keys())if(!keep.has(id))this.pending.delete(id);}
}

// Bounds each running-Task check in wall-clock time. discord.js retries hung
// connections and 429 responses internally, so a check that has not finished
// within limitMs counts as ACCESS_UNAVAILABLE, and a check still in flight on
// the next tick is not duplicated: it counts as unavailable again. Only a
// check started in this tick can confirm access.
export class AccessMonitor{
  constructor({grace=new AccessGrace(),limitMs=2000,maxInflight=8}={}){this.grace=grace;this.limitMs=limitMs;this.maxInflight=maxInflight;this.inflight=new Map();this.stopping=false;}
  async check(id,probe){
    if(this.stopping)return false;
    const startedAt=this.grace.now();
    if(this.inflight.has(id)||this.inflight.size>=this.maxInflight)return this.grace.tolerate(id,new Refused('ACCESS_UNAVAILABLE'),startedAt);
    const pending=Promise.resolve().then(()=>{if(this.stopping)throw new Refused('RUNTIME_STOPPING');return probe();});
    this.inflight.set(id,pending);const finished=()=>this.inflight.delete(id);pending.then(finished,finished);
    let timer;
    const limit=new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Refused('ACCESS_UNAVAILABLE')),this.limitMs);timer.unref?.();});
    try{await Promise.race([pending,limit]);this.grace.clear(id);return true;}
    catch(error){pending.catch(()=>{});return this.grace.tolerate(id,error,startedAt);}
    finally{clearTimeout(timer);}
  }
  retain(ids){this.grace.retain(ids);}
  stop(){this.stopping=true;}
  async drain({pending=[],timeoutMs=15000}={}){
    // A check deadline does not settle its underlying verifier.
    this.stop();const deadline=deadlineScope(timeoutMs,'POLICY_DRAIN_UNCERTAIN');
    try{await awaitWithSignal(Promise.allSettled([...pending,...this.inflight.values()]),deadline.signal);}finally{deadline.dispose();}
  }
}
