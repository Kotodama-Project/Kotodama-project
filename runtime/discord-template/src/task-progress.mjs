import {check,digest,errorCode} from './common.mjs';

export const progressTargetKey=task=>digest(['quiet-task-progress-target',task.id,task.revision]);
const states=new Set(['queued','running','needs_review','failed','paused','stopping','cancelled','uncertain']);

/** A delivery projection over existing local Task events, never another Task owner. */
export class QuietTaskProgress {
  constructor({store,policy,deliver,onError=()=>{},clock=Date.now}){
    Object.assign(this,{store,policy,deliver,onError,clock});this.cursor=this.latest();this.closed=false;this.pending=null;this.wasEnabled=this.enabled();
  }
  latest(){return this.store.statement('SELECT coalesce(max(seq),0) AS seq FROM events').get().seq;}
  enabled(){return !this.closed&&this.policy().owner.kind==='local'&&this.policy().notifications?.taskProgress?.enabled===true;}
  remember(task,messageId){
    if(!this.enabled())return;
    check(/^\d{5,24}$/.test(messageId),'PROGRESS_MESSAGE_ID_INVALID');
    const key=progressTargetKey(task);if(this.store.claimDelivery(key,{id:task.id,revision:task.revision,actor:task.actor}))this.store.delivered(key,messageId);
  }
  claim(task){
    if(!this.enabled())return false;
    const limits=this.policy().notifications.taskProgress,now=this.clock();check(Number.isFinite(now),'PROGRESS_CLOCK_INVALID');
    return this.store.transaction(()=>{
      const count=this.store.statement("SELECT count(*) AS n,max(json_extract(body,'$.attempted_ms')) AS last FROM events WHERE task_id=? AND type='task.progress_attempt'").get(task.id);
      if(count.n>=limits.maxUpdates||count.last!==null&&now-count.last<limits.minIntervalSeconds*1000)return false;
      const key=digest(['quiet-task-progress',task.id,task.revision,task.state]);
      if(!this.store.claimDelivery(key,{id:task.id,revision:task.revision,state:task.state}))return false;
      this.store.event('task.progress_attempt',{revision:task.revision,state:task.state,attempted_ms:now},task.id);return key;
    });
  }
  tick(){
    if(this.pending)return this.pending;if(this.closed)return Promise.resolve();
    this.pending=this.process().catch(e=>this.onError(errorCode(e))).finally(()=>{this.pending=null;});return this.pending;
  }
  async process(){
    if(!this.enabled()){this.cursor=this.latest();this.wasEnabled=false;return;}
    if(!this.wasEnabled){this.cursor=this.latest();this.wasEnabled=true;return;}
    const events=this.store.statement('SELECT seq,type,task_id FROM events WHERE seq>? ORDER BY seq LIMIT 64').all(this.cursor);
    if(!events.length)return;this.cursor=events.at(-1).seq;
    const ids=[...new Set(events.filter(e=>e.task_id&&e.type.startsWith('task.')&&e.type!=='task.progress_attempt').map(e=>e.task_id))];
    for(const id of ids){
      if(!this.enabled())return;
      try{
        const task=this.store.taskInternal(id);if(!states.has(task.state))continue;
        if(this.store.deliveryState(digest(['quiet-task-progress',task.id,task.revision,task.state])))continue;
        const target=this.store.statement("SELECT message_id FROM deliveries WHERE key=? AND state='sent'").get(progressTargetKey(task));if(!target)continue;
        await this.deliver(task,{messageId:target.message_id,claim:()=>this.claim(task),isActive:()=>this.enabled()});
      }catch(e){this.onError(errorCode(e));}
    }
  }
  start(){if(this.timer||this.closed)return;this.timer=setInterval(()=>{void this.tick();},5000);this.timer.unref();}
  async close(){this.closed=true;clearInterval(this.timer);await this.pending;}
}
