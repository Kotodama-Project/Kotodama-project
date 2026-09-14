import {check,Refused} from './common.mjs';

export const admissionDefaults=Object.freeze({concurrency:2,perRoom:1,perActor:1,maxPending:32,
  maxPendingPerRoom:16,maxPendingPerActor:8,maxDailyCalls:500,maxTotalCalls:5000});

export function admissionLimits(value={}){
  const limits={...admissionDefaults,...value};
  for(const [key,n]of Object.entries(limits))check(Object.hasOwn(admissionDefaults,key)&&Number.isSafeInteger(n)&&
    n>=(['maxDailyCalls','maxTotalCalls','maxPending','maxPendingPerRoom','maxPendingPerActor'].includes(key)?0:1)&&
    n<=(['maxDailyCalls','maxTotalCalls'].includes(key)?1000000:1024),'ANALYSIS_LIMIT_INVALID');
  return limits;
}

// Reservations share the installation's SQLite database, not the Task owner.
// A crashed/failed call consumes its reservation. Restart never refunds it.
export class AnalysisBudget {
  constructor(store,limits,clock=()=>new Date()){
    check(store?.db&&typeof store.transaction==='function','ANALYSIS_BUDGET_STORE_REQUIRED');
    this.store=store;this.limits=admissionLimits(limits);this.clock=clock;
    store.db.exec('CREATE TABLE IF NOT EXISTS analysis_usage(day TEXT PRIMARY KEY, reserved_calls INTEGER NOT NULL CHECK(reserved_calls>=0))');
  }
  reserve(calls=1){
    check(Number.isSafeInteger(calls)&&calls>=1&&calls<=2,'ANALYSIS_RESERVATION_INVALID');
    const day=this.clock().toISOString().slice(0,10),db=this.store.db,limits=this.limits;
    return this.store.transaction(()=>{
      const daily=db.prepare('SELECT reserved_calls FROM analysis_usage WHERE day=?').get(day)?.reserved_calls??0;
      const total=db.prepare('SELECT COALESCE(SUM(reserved_calls),0) AS n FROM analysis_usage').get().n;
      check(daily+calls<=limits.maxDailyCalls,'ANALYSIS_DAILY_LIMIT');
      check(total+calls<=limits.maxTotalCalls,'ANALYSIS_TOTAL_LIMIT');
      db.prepare('INSERT INTO analysis_usage VALUES(?,?) ON CONFLICT(day) DO UPDATE SET reserved_calls=excluded.reserved_calls').run(day,daily+calls);
      return {day,reservedCalls:calls,daily:daily+calls,total:total+calls};
    });
  }
}

export class AnalysisAdmission {
  constructor(limits={}){this.limits=admissionLimits(limits);this.pending=[];this.active=0;this.rooms=new Map();this.actors=new Map();this.closed=false;}
  snapshot(){return {active:this.active,pending:this.pending.length,closed:this.closed};}
  run({room,actor,signal,priority=0},work){
    if(this.closed||signal?.aborted)return Promise.reject(new Refused('CANCELLED'));
    check(typeof room==='string'&&typeof actor==='string'&&typeof work==='function','ANALYSIS_SCOPE_REQUIRED');
    const l=this.limits,canStart=this.active<l.concurrency&&(this.rooms.get(room)??0)<l.perRoom&&(this.actors.get(actor)??0)<l.perActor;
    const roomFull=this.pending.filter(j=>j.room===room).length>=l.maxPendingPerRoom;
    const actorFull=this.pending.filter(j=>j.actor===actor).length>=l.maxPendingPerActor;
    if(!canStart&&(this.pending.length>=l.maxPending||roomFull||actorFull)){
      // Make room for an explicit/corrected turn without losing its source evidence.
      const index=this.pending.findIndex(j=>j.priority<priority&&(!roomFull||j.room===room)&&(!actorFull||j.actor===actor));
      if(index<0||l.maxPending===0||l.maxPendingPerRoom===0||l.maxPendingPerActor===0)return Promise.reject(new Refused('ANALYSIS_QUEUE_FULL'));
      const [old]=this.pending.splice(index,1);old.signal?.removeEventListener('abort',old.abort);old.reject(new Refused('ANALYSIS_QUEUE_PREEMPTED'));
    }
    return new Promise((resolve,reject)=>{
      const job={room,actor,signal,priority,work,resolve,reject};
      job.abort=()=>{const index=this.pending.indexOf(job);if(index>=0){this.pending.splice(index,1);signal?.removeEventListener('abort',job.abort);reject(new Refused('CANCELLED'));this.drain();}};
      signal?.addEventListener('abort',job.abort,{once:true});this.pending.push(job);this.drain();
    });
  }
  drain(){
    const l=this.limits;
    while(!this.closed&&this.active<l.concurrency){
      let index=-1;
      for(let i=0;i<this.pending.length;i++){const j=this.pending[i];if((this.rooms.get(j.room)??0)<l.perRoom&&(this.actors.get(j.actor)??0)<l.perActor&&
        (index<0||j.priority>this.pending[index].priority))index=i;}
      if(index<0)return;
      const [job]=this.pending.splice(index,1);job.signal?.removeEventListener('abort',job.abort);
      if(job.signal?.aborted){job.reject(new Refused('CANCELLED'));continue;}
      this.active++;this.rooms.set(job.room,(this.rooms.get(job.room)??0)+1);this.actors.set(job.actor,(this.actors.get(job.actor)??0)+1);
      Promise.resolve().then(()=>{check(!job.signal?.aborted&&!this.closed,'CANCELLED');return job.work();}).then(job.resolve,job.reject).finally(()=>{
        this.active--;for(const [map,key]of [[this.rooms,job.room],[this.actors,job.actor]]){const n=map.get(key)-1;if(n)map.set(key,n);else map.delete(key);}this.drain();
      });
    }
  }
  close(){this.closed=true;for(const job of this.pending.splice(0)){job.signal?.removeEventListener('abort',job.abort);job.reject(new Refused('CANCELLED'));}}
}
