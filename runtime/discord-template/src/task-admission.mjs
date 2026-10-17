import {check,Refused} from './common.mjs';

export const DEFAULT_TASK_LIMITS=Object.freeze({maxConcurrentReadOnly:1,maxQueued:32,maxQueuedBytes:65536,maxInputBytes:524288,maxResultBytes:8388608});
const READ_ONLY=new Set(['research','summarize']);
export function isReadOnlyTask(task){return READ_ONLY.has(task.action)&&(task.requiredActions??[task.action]).every(action=>READ_ONLY.has(action));}
export function taskLimits(value={}){
  const limits={...DEFAULT_TASK_LIMITS,...value};
  for(const [key,min,max] of [['maxConcurrentReadOnly',1,4],['maxQueued',0,256],['maxQueuedBytes',0,1048576],['maxInputBytes',1024,8388608],['maxResultBytes',1024,67108864]])
    check(Number.isSafeInteger(limits[key])&&limits[key]>=min&&limits[key]<=max,'TASK_LIMIT_INVALID');
  return limits;
}

// Holds scheduling references only. The existing owner retains Task state,
// sources, results, cancellation, and restart recovery.
export class TaskAdmission {
  constructor(readLimits=()=>({})){
    this.readLimits=readLimits;this.queue=[];this.active=new Map();this.entries=new Map();
    this.closed=false;this.waiting=null;this.lastGroup=null;this.limits();
  }
  limits(){return taskLimits(this.readLimits());}
  idle(){return this.waiting?.promise??Promise.resolve();}
  status(){return {running:this.active.size,queued:this.queue.length,queuedBytes:this.queue.reduce((total,item)=>total+item.bytes,0),closed:this.closed,limits:this.limits()};}
  descriptor(task){
    const value={id:task.id,actor:task.actor,revision:task.revision,room:task.room??'',sourceKey:task.source_key??'',readOnly:isReadOnlyTask(task)};
    check(typeof value.id==='string'&&value.id.length>0&&value.id.length<=128&&typeof value.actor==='string'&&value.actor.length>0&&value.actor.length<=128&&typeof value.room==='string'&&value.room.length<=256&&typeof value.sourceKey==='string'&&value.sourceKey.length<=128&&Number.isSafeInteger(value.revision)&&value.revision>0,'TASK_ADMISSION_INVALID');
    return {...value,key:value.id+':'+value.revision,bytes:Buffer.byteLength(JSON.stringify(value))};
  }
  #next(queue,active,limits,lastGroup=this.lastGroup){
    const barrier=queue.findIndex(item=>!item.readOnly);
    const candidates=queue.map((item,index)=>({item,index})).filter(({item,index})=>{
      if(barrier>=0&&index>barrier)return false;
      if(!item.readOnly)return active.length===0;
      return active.length<limits.maxConcurrentReadOnly&&active.every(run=>run.readOnly&&run.actor!==item.actor&&(!item.room||run.room!==item.room));
    });
    return (candidates.find(({item})=>item.actor+'\n'+item.room!==lastGroup)??candidates[0])?.index??-1;
  }
  submitBatch(requests){
    check(!this.closed,'RUNTIME_STOPPING');
    const limits=this.limits(),newEntries=[],seen=new Map(),answers=[];
    check(Array.isArray(requests)&&requests.length<=limits.maxQueued+limits.maxConcurrentReadOnly,'TASK_QUEUE_FULL');
    for(const {task,operation} of requests){
      check(typeof operation==='function','TASK_ADMISSION_INVALID');
      const descriptor=this.descriptor(task),existing=this.entries.get(descriptor.key)??seen.get(descriptor.key);
      if(existing){check(JSON.stringify(existing.descriptor)===JSON.stringify(descriptor),'TASK_ADMISSION_CONFLICT');answers.push(existing);continue;}
      const item={...descriptor,descriptor,operation};newEntries.push(item);seen.set(item.key,item);answers.push(item);
    }
    // Predict dispatch before publishing anything. An overflowing batch must
    // not start its first Task and then reject the remaining Tasks.
    const pending=[...this.queue,...newEntries],running=[...this.active.values()];let lastGroup=this.lastGroup;
    for(let index;(index=this.#next(pending,running,limits,lastGroup))>=0;){const [item]=pending.splice(index,1);running.push(item);lastGroup=item.actor+'\n'+item.room;}
    check(pending.length<=limits.maxQueued,'TASK_QUEUE_FULL');
    check(pending.reduce((total,item)=>total+item.bytes,0)<=limits.maxQueuedBytes,'TASK_QUEUE_BYTES_EXCEEDED');
    if(newEntries.length&&!this.waiting){let resolve;const promise=new Promise(done=>{resolve=done;});this.waiting={promise,resolve};}
    for(const item of newEntries){
      item.promise=new Promise((resolve,reject)=>{item.resolve=resolve;item.reject=reject;});
      this.entries.set(item.key,item);this.queue.push(item);
    }
    this.#pump();return answers.map(item=>item.promise);
  }
  cancel(key,code='CANCELLED'){
    const index=this.queue.findIndex(item=>item.key===key);if(index<0)return false;
    const [item]=this.queue.splice(index,1);this.entries.delete(key);item.reject(new Refused(code));this.#pump();this.#settled();return true;
  }
  superseded(id,revision){return [...this.entries.values()].some(item=>item.id===id&&item.revision>revision);}
  cancelStale(id,revision){for(const item of [...this.queue])if(item.id===id&&item.revision<revision)this.cancel(item.key,'TASK_CHANGED');}
  cancelSource(sourceKey){for(const item of [...this.queue])if(item.sourceKey===sourceKey)this.cancel(item.key,'SOURCE_CHANGED');}
  close(code='RUNTIME_STOPPING'){
    this.closed=true;
    for(const item of this.queue.splice(0)){this.entries.delete(item.key);item.reject(new Refused(code));}
    this.#settled();return this.idle();
  }
  #settled(){if(!this.entries.size&&this.waiting){const waiting=this.waiting;this.waiting=null;waiting.resolve();}}
  #pump(){
    if(this.closed)return;
    let limits;try{limits=this.limits();}catch(error){this.close('TASK_LIMIT_INVALID');return;}
    for(let index;(index=this.#next(this.queue,[...this.active.values()],limits))>=0;){
      const [item]=this.queue.splice(index,1);this.active.set(item.key,item);this.lastGroup=item.actor+'\n'+item.room;
      Promise.resolve().then(()=>item.operation()).then(item.resolve,item.reject).finally(()=>{
        this.active.delete(item.key);this.entries.delete(item.key);this.#pump();this.#settled();
      });
    }
  }
}
