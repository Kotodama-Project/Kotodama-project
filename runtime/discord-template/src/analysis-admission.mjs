import {check,Refused} from './common.mjs';

export const DEFAULT_ANALYSIS_LIMITS=Object.freeze({maxConcurrent:2,maxQueued:32,maxPerRoom:1,maxPerActor:1,maxDailyAnalyses:500,maxTotalAnalyses:10000});
export function analysisLimits(value={}){
  const limits={...DEFAULT_ANALYSIS_LIMITS,...value};
  for(const [key,min,max] of [['maxConcurrent',1,16],['maxQueued',0,256],['maxPerRoom',1,16],['maxPerActor',1,16],['maxDailyAnalyses',0,1000000],['maxTotalAnalyses',0,10000000]])
    check(Number.isSafeInteger(limits[key])&&limits[key]>=min&&limits[key]<=max,'ANALYSIS_LIMIT_INVALID');
  return limits;
}

// A slot is held until the real operation settles, including cancellation.
// Queued entries contain references/closures, not another copy of source text.
export class AnalysisAdmission {
  constructor(readLimits=()=>({})){
    this.readLimits=readLimits;this.queue=[];this.running=0;this.rooms=new Map();this.actors=new Map();this.closed=false;
    this.limits();
  }
  limits(){return analysisLimits(this.readLimits());}
  status(){return {running:this.running,queued:this.queue.length,limits:this.limits()};}
  available(item,limits){return this.running<limits.maxConcurrent&&(this.rooms.get(item.room)??0)<limits.maxPerRoom&&(this.actors.get(item.actor)??0)<limits.maxPerActor;}
  submit({room,actor,priority=0,signal},operation){
    check(!this.closed,'RUNTIME_STOPPING');check(!signal?.aborted,'CANCELLED');
    check(typeof room==='string'&&typeof actor==='string'&&Number.isInteger(priority),'ANALYSIS_ADMISSION_INVALID');
    return new Promise((resolve,reject)=>{
      const item={room,actor,priority,signal,operation,resolve,reject};
      const limits=this.limits();
      if(!this.queue.length&&this.available(item,limits)){this.start(item);return;}
      if(this.queue.length>=limits.maxQueued){
        const victim=this.queue.findIndex(x=>x.priority<priority);
        if(victim<0){reject(new Refused('ANALYSIS_QUEUE_FULL'));return;}
        const [old]=this.queue.splice(victim,1);old.detach();old.reject(new Refused('ANALYSIS_SUPERSEDED'));
      }
      const abort=()=>{const i=this.queue.indexOf(item);if(i>=0){this.queue.splice(i,1);item.detach();reject(new Refused('CANCELLED'));this.pump();}};
      item.detach=()=>signal?.removeEventListener('abort',abort);
      signal?.addEventListener('abort',abort,{once:true});
      this.queue.push(item);this.queue.sort((a,b)=>b.priority-a.priority);
      if(signal?.aborted)abort();else this.pump();
    });
  }
  start(item){
    item.detach?.();this.running++;this.rooms.set(item.room,(this.rooms.get(item.room)??0)+1);this.actors.set(item.actor,(this.actors.get(item.actor)??0)+1);
    const release=()=>{this.running--;for(const [map,key] of [[this.rooms,item.room],[this.actors,item.actor]]){const count=map.get(key)-1;if(count)map.set(key,count);else map.delete(key);}this.pump();};
    Promise.resolve().then(()=>{check(!item.signal?.aborted&&!this.closed,'CANCELLED');return item.operation();}).then(value=>{release();item.resolve(value);},error=>{release();item.reject(error);});
  }
  pump(){
    if(this.closed)return;
    const limits=this.limits();
    while(this.running<limits.maxConcurrent){const i=this.queue.findIndex(x=>this.available(x,limits));if(i<0)break;this.start(this.queue.splice(i,1)[0]);}
  }
  close(){this.closed=true;for(const item of this.queue.splice(0)){item.detach();item.reject(new Refused('RUNTIME_STOPPING'));}}
}
