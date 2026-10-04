import {check,digest,Refused} from './common.mjs';
import {hourInTimeZone} from './time-zone.mjs';

export function isQuiet(policy,date=new Date()){
  if(!policy?.enabled)return false;
  const hour=hourInTimeZone(policy.timeZone,date);
  return policy.startHour>policy.endHour?hour>=policy.startHour||hour<policy.endHour:hour>=policy.startHour&&hour<policy.endHour;
}
// Delivery scheduling only; task state and content remain with the existing owner.
export class NotificationQueue {
  constructor(db,policy,{now=()=>new Date(),onError=()=>{},drainTimeoutMs=15000}={}){
    check(Number.isSafeInteger(drainTimeoutMs)&&drainTimeoutMs>0&&drainTimeoutMs<=60000,'NOTIFICATION_DRAIN_CONFIG_INVALID');
    Object.assign(this,{db,policy,now,onError,drainTimeoutMs});this.busy=false;this.cursor=0;this.sweepEnd=0;this.stopping=false;this.pending=null;this.drainWaiters=new Set();
    db.exec('CREATE TABLE IF NOT EXISTS deferred_notifications(key TEXT PRIMARY KEY,kind TEXT NOT NULL,body TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL)');
    // A partial state index also orders equal-state entries by their implicit rowid.
    // Completed receipts remain for replay checks without slowing pending scans.
    db.exec("CREATE INDEX IF NOT EXISTS deferred_notifications_pending ON deferred_notifications(state) WHERE state='pending'");
    this.prior=db.prepare('SELECT digest FROM deferred_notifications WHERE key=?');
    this.pendingCount=db.prepare("SELECT count(*) AS n FROM deferred_notifications WHERE state='pending'");
    this.insert=db.prepare('INSERT INTO deferred_notifications VALUES(?,?,?,?,?)');
    this.lastPending=db.prepare("SELECT rowid AS notificationRowid FROM deferred_notifications WHERE state='pending' ORDER BY rowid DESC LIMIT 1");
    this.pendingRows=db.prepare("SELECT rowid AS notificationRowid,* FROM deferred_notifications WHERE state='pending' AND rowid>? AND rowid<=? ORDER BY rowid LIMIT 20");
    this.markDone=db.prepare("UPDATE deferred_notifications SET state='done' WHERE key=?");
  }
  quiet(){return isQuiet(this.policy(),this.now());}
  defer(key,kind,body){
    check(!this.stopping,'NOTIFICATION_QUEUE_STOPPED');
    const bytes=JSON.stringify(body),hash=digest(bytes);check(bytes.length<=20000,'NOTIFICATION_SIZE_LIMIT');
    const prior=this.prior.get(key);if(prior){check(prior.digest===hash,'NOTIFICATION_REPLAY_CONFLICT');return;}
    check(this.pendingCount.get().n<1024,'NOTIFICATION_QUEUE_LIMIT');
    this.insert.run(key,kind,bytes,hash,'pending');
  }
  flush(send){
    try{check(!this.stopping,'NOTIFICATION_QUEUE_STOPPED');if(this.busy||this.quiet())return Promise.resolve();}catch(error){return Promise.reject(error);}
    this.busy=true;
    // Own the raw operation before dispatch, including direct/manual flush calls.
    const operation=Promise.resolve().then(()=>this.#flushPending(send));this.pending=operation;
    const settled=()=>{this.pending=null;this.busy=false;for(const finish of this.drainWaiters)finish();};
    operation.then(settled,settled);return operation;
  }
  async #flushPending(send){
    if(this.stopping)return;
    // Freeze this round's end so fresh arrivals cannot postpone blocked retries.
    if(!this.sweepEnd||this.cursor>=this.sweepEnd){this.cursor=0;this.sweepEnd=this.lastPending.get()?.notificationRowid??0;}
    let rows=this.pendingRows.all(this.cursor,this.sweepEnd);
    if(!rows.length&&this.cursor){this.cursor=0;this.sweepEnd=this.lastPending.get()?.notificationRowid??0;rows=this.pendingRows.all(0,this.sweepEnd);}
    for(const row of rows){
      if(this.stopping||this.quiet())break;
      // A recipient-specific exception still consumes this position in the round.
      // Keep its receipt pending and propagate the error; later ticks can progress.
      this.cursor=row.notificationRowid;
      const result=await send(row.kind,JSON.parse(row.body));
      if(result?.state==='blocked'||result?.state==='deferred')continue;
      this.markDone.run(row.key);
    }
  }
  start(send){
    check(!this.stopping,'NOTIFICATION_QUEUE_STOPPED');check(!this.timer,'NOTIFICATION_QUEUE_ALREADY_STARTED');
    const tick=()=>{if(!this.stopping&&!this.pending)void this.flush(send).catch(()=>this.onError('NOTIFICATION_DELIVERY_BLOCKED'));};
    this.timer=setInterval(tick,60000);this.timer.unref();tick();
  }
  async stop(){
    this.stopping=true;clearInterval(this.timer);this.timer=null;if(!this.pending)return;
    // A deadline ends this wait, never the raw send or its ownership of the DB.
    await new Promise((resolve,reject)=>{
      const finish=()=>{clearTimeout(timer);this.drainWaiters.delete(finish);resolve();};
      const timer=setTimeout(()=>{this.drainWaiters.delete(finish);reject(new Refused('NOTIFICATION_DRAIN_UNCERTAIN'));},this.drainTimeoutMs);
      this.drainWaiters.add(finish);
    });
  }
}
