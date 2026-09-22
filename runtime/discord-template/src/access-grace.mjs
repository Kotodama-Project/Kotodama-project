// A transient Discord failure (rate limit, server error, timeout, transport
// error) does not prove that access was revoked. A running Task survives only a
// short, counted window of such failures; a definitive denial or any other
// failure still stops it at once.
export class AccessGrace{
  constructor({graceMs=5000,maxUnavailable=3,now=()=>Date.now()}={}){Object.assign(this,{graceMs,maxUnavailable,now});this.pending=new Map();}
  tolerate(id,error){
    if(error?.code!=='ACCESS_UNAVAILABLE'){this.pending.delete(id);return false;}
    const at=this.now(),entry=this.pending.get(id)??{since:at,count:0};entry.count++;
    if(entry.count>this.maxUnavailable||at-entry.since>this.graceMs){this.pending.delete(id);return false;}
    this.pending.set(id,entry);return true;
  }
  clear(id){this.pending.delete(id);}
  retain(ids){const keep=new Set(ids);for(const id of this.pending.keys())if(!keep.has(id))this.pending.delete(id);}
}
