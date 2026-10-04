import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {NotificationQueue,isQuiet} from '../src/notifications.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
const policy={enabled:true,startHour:22,endHour:9,timeZone:'Asia/Tokyo'};
test('JST quiet hours include 22:00 and exclude 09:00',()=>{
  assert(isQuiet(policy,new Date('2026-09-13T13:00:00Z')));assert(isQuiet(policy,new Date('2026-09-13T23:59:59Z')));assert(!isQuiet(policy,new Date('2026-09-14T00:00:00Z')));assert(!isQuiet(policy,new Date('2026-09-13T12:59:59Z')));
});
test('deferred notifications survive queue reconstruction and send once after quiet hours',async()=>{
  const db=new DatabaseSync(':memory:');let date=new Date('2026-09-13T14:00:00Z'),sent=0;
  const first=new NotificationQueue(db,()=>policy,{now:()=>date});first.defer('one','task',{id:'task',actor:'owner',revision:1});first.defer('one','task',{id:'task',actor:'owner',revision:1});await first.flush(async()=>sent++);assert.equal(sent,0);
  const resumed=new NotificationQueue(db,()=>policy,{now:()=>date});date=new Date('2026-09-14T00:00:00Z');await resumed.flush(async()=>{sent++;return {state:'sent'};});await resumed.flush(async()=>sent++);assert.equal(sent,1);db.close();
});
test('quiet-hours config retains JST defaults and validates named regional zones',()=>{
  const config=exampleConfig();assert.equal(config.notifications.quietHours.timeZone,'Asia/Tokyo');
  for(const timeZone of ['UTC','America/New_York','Europe/London','Asia/Kolkata','Etc/GMT+5']){
    config.notifications.quietHours.timeZone=timeZone;assert.equal(Config.parse(config).notifications.quietHours.timeZone,timeZone);
  }
  for(const timeZone of ['Mars/Olympus_Mons','+09:00','-0500',' Asia/Tokyo','',null]){
    config.notifications.quietHours.timeZone=timeZone;assert.equal(Config.safeParse(config).success,false);
  }
  config.notifications.quietHours={...policy,timeZone:'UTC',timezone:'Asia/Tokyo'};assert.equal(Config.safeParse(config).success,false);
});
test('regional quiet hours follow local same-day and fractional-offset boundaries',()=>{
  const london={enabled:true,startHour:12,endHour:14,timeZone:'Europe/London'};
  assert(!isQuiet(london,new Date('2026-07-01T10:59:59Z')));assert(isQuiet(london,new Date('2026-07-01T11:00:00Z')));
  assert(isQuiet(london,new Date('2026-07-01T12:59:59Z')));assert(!isQuiet(london,new Date('2026-07-01T13:00:00Z')));
  const kolkata={...policy,timeZone:'Asia/Kolkata'};
  assert(!isQuiet(kolkata,new Date('2026-07-01T16:29:59Z')));assert(isQuiet(kolkata,new Date('2026-07-01T16:30:00Z')));
  assert(isQuiet(kolkata,new Date('2026-07-02T03:29:59Z')));assert(!isQuiet(kolkata,new Date('2026-07-02T03:30:00Z')));
  assert(isQuiet({...policy,timeZone:'UTC'},new Date('2026-07-01T00:00:00Z')));
  assert(!isQuiet({...policy,startHour:0,endHour:0,timeZone:'UTC'},new Date('2026-07-01T00:00:00Z')));
  assert(!isQuiet({...policy,enabled:false},new Date('2026-07-01T14:00:00Z')));
});
test('DST gaps and repeated hours use the configured zone rather than a fixed offset',()=>{
  const ny={enabled:true,startHour:1,endHour:3,timeZone:'America/New_York'};
  assert(isQuiet(ny,new Date('2026-03-08T06:59:59Z')));assert(!isQuiet(ny,new Date('2026-03-08T07:00:00Z')));
  assert(isQuiet(ny,new Date('2026-11-01T05:30:00Z')));assert(isQuiet(ny,new Date('2026-11-01T06:30:00Z')));
  assert(isQuiet(ny,new Date('2026-11-01T07:59:59Z')));assert(!isQuiet(ny,new Date('2026-11-01T08:00:00Z')));
});
test('repeated policy reloads and notification checks reuse one ICU formatter',t=>{
  const original=Intl.DateTimeFormat;let created=0;
  t.mock.method(Intl,'DateTimeFormat',function(...args){created++;return new original(...args);});
  const config=exampleConfig();config.notifications.quietHours={...policy,timeZone:'Pacific/Marquesas'};
  created=0;
  for(let n=0;n<1000;n++)assert(isQuiet(Config.parse(config).notifications.quietHours,new Date('2026-07-01T09:30:00Z')));
  assert.equal(created,1);
});
test('timezone changes release older ICU formatters rather than retaining every zone',t=>{
  const original=Intl.DateTimeFormat;let created=0;
  t.mock.method(Intl,'DateTimeFormat',function(...args){created++;return new original(...args);});
  const zones=Intl.supportedValuesOf('timeZone').slice(0,32),date=new Date('2026-07-01T09:30:00Z');
  for(const timeZone of zones)isQuiet({...policy,timeZone},date);
  const before=created;isQuiet({...policy,timeZone:zones[0]},date);assert.equal(created,before+1);
});
test('queue migration indexes pending rows independently of completed receipt history',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());
  db.exec('CREATE TABLE deferred_notifications(key TEXT PRIMARY KEY,kind TEXT NOT NULL,body TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL)');
  const insert=db.prepare('INSERT INTO deferred_notifications VALUES(?,?,?,?,?)');
  for(let n=0;n<5000;n++)insert.run('done-'+n,'task','{}','synthetic-digest','done');
  const queue=new NotificationQueue(db,()=>({enabled:false}));
  for(const query of ["SELECT count(*) AS n FROM deferred_notifications WHERE state='pending'","SELECT rowid AS notificationRowid FROM deferred_notifications WHERE state='pending' ORDER BY rowid DESC LIMIT 1","SELECT rowid AS notificationRowid,* FROM deferred_notifications WHERE state='pending' AND rowid>0 AND rowid<=6000 ORDER BY rowid LIMIT 20"]){
    const plan=db.prepare('EXPLAIN QUERY PLAN '+query).all().map(row=>row.detail).join('\n');
    assert.match(plan,/deferred_notifications_pending/);assert.doesNotMatch(plan,/SCAN deferred_notifications\b|TEMP B-TREE/);
  }
  queue.defer('new','task',{id:'new'});const sent=[];await queue.flush(async(_kind,body)=>{sent.push(body.id);return {state:'sent'};});
  assert.deepEqual(sent,['new']);queue.defer('new','task',{id:'new'});await queue.flush(async()=>assert.fail('completed receipt replayed'));
  assert.equal(db.prepare('SELECT count(*) AS n FROM deferred_notifications').get().n,5001);
  assert.throws(()=>queue.defer('new','task',{id:'changed'}),/NOTIFICATION_REPLAY_CONFLICT/);
});
test('blocked older recipients cannot starve newer notifications and are retried after wrap',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());const queue=new NotificationQueue(db,()=>({enabled:false}));
  for(let n=0;n<25;n++)queue.defer('notification-'+n,'task',{id:n});
  const attempts=[],sent=[];let blocked=true;
  const send=async(_kind,body)=>{attempts.push(body.id);if(blocked&&body.id<20)return {state:body.id%2?'blocked':'deferred'};sent.push(body.id);return {state:'sent'};};
  await queue.flush(send);assert.equal(attempts.length,20);assert.deepEqual(sent,[]);
  await queue.flush(send);assert.deepEqual(sent,[20,21,22,23,24]);assert.equal(attempts.length,25);
  blocked=false;await queue.flush(send);assert.deepEqual(sent,[20,21,22,23,24,...Array.from({length:20},(_,n)=>n)]);
  await queue.flush(send);assert.equal(attempts.length,45);assert.equal(db.prepare("SELECT count(*) AS n FROM deferred_notifications WHERE state='pending'").get().n,0);
});
test('delivery stops when local quiet hours begin and resumes remaining rows later',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());let date=new Date('2026-07-01T20:59:59Z');
  const queue=new NotificationQueue(db,()=>({...policy,timeZone:'Europe/London'}),{now:()=>date});
  for(let n=0;n<3;n++)queue.defer('notification-'+n,'task',{id:n});
  const sent=[];await queue.flush(async(_kind,body)=>{sent.push(body.id);date=new Date('2026-07-01T21:00:00Z');return {state:'sent'};});assert.deepEqual(sent,[0]);
  await queue.flush(async()=>assert.fail('sent during quiet hours'));date=new Date('2026-07-02T08:00:00Z');
  await queue.flush(async(_kind,body)=>{sent.push(body.id);return {state:'sent'};});assert.deepEqual(sent,[0,1,2]);
});
test('fresh arrivals do not indefinitely postpone blocked retries',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());const queue=new NotificationQueue(db,()=>({enabled:false}));
  for(let n=0;n<25;n++)queue.defer('notification-'+n,'task',{id:n});
  const attempts=[];const send=async(_kind,body)=>{attempts.push(body.id);return {state:body.id<20?'blocked':'sent'};};
  await queue.flush(send);assert.deepEqual(attempts,Array.from({length:20},(_,n)=>n));
  for(let n=25;n<45;n++)queue.defer('notification-'+n,'task',{id:n});
  await queue.flush(send);assert.deepEqual(attempts.slice(20),[20,21,22,23,24]);
  await queue.flush(send);assert.deepEqual(attempts.slice(25),Array.from({length:20},(_,n)=>n));
  await queue.flush(send);assert.deepEqual(attempts.slice(45),Array.from({length:20},(_,n)=>n+25));
});
test('a thrown authorization failure retains its receipt without starving later notifications',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());const queue=new NotificationQueue(db,()=>({enabled:false}));
  for(let n=0;n<25;n++)queue.defer('notification-'+n,'task',{id:n});
  const attempts=[],sent=[];let allowed=false;
  const send=async(_kind,body)=>{attempts.push(body.id);if(body.id===0&&!allowed)throw Error('TASK_ACCESS_DENIED');sent.push(body.id);return {state:'sent'};};
  await assert.rejects(queue.flush(send),/TASK_ACCESS_DENIED/);assert.deepEqual(attempts,[0]);
  await queue.flush(send);assert.deepEqual(sent,Array.from({length:20},(_,n)=>n+1));
  await queue.flush(send);assert.deepEqual(sent,Array.from({length:24},(_,n)=>n+1));assert.equal(queue.pendingCount.get().n,1);
  allowed=true;await queue.flush(send);assert.deepEqual(sent,[...Array.from({length:24},(_,n)=>n+1),0]);assert.equal(queue.pendingCount.get().n,0);
});
test('pending queue limit excludes completed history and retains replay checks',t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());const queue=new NotificationQueue(db,()=>({enabled:false}));
  for(let n=0;n<1024;n++)queue.defer('notification-'+n,'task',{id:n});
  assert.throws(()=>queue.defer('overflow','task',{id:1024}),/NOTIFICATION_QUEUE_LIMIT/);
  queue.defer('notification-0','task',{id:0});assert.throws(()=>queue.defer('notification-0','task',{id:'changed'}),/NOTIFICATION_REPLAY_CONFLICT/);
  db.prepare("UPDATE deferred_notifications SET state='done' WHERE key=?").run('notification-0');queue.defer('overflow','task',{id:1024});
  assert.equal(db.prepare("SELECT count(*) AS n FROM deferred_notifications WHERE state='pending'").get().n,1024);
});
test('hung timer delivery refuses bounded stop, retains raw ownership, and completes a later stop',async t=>{
  const db=new DatabaseSync(':memory:');let release,started,closed=false,sends=0;
  const ready=new Promise(resolve=>started=resolve),rawSend=new Promise(resolve=>release=resolve);
  const queue=new NotificationQueue(db,()=>({enabled:false}),{drainTimeoutMs:15});
  t.after(async()=>{release({state:'sent'});await queue.stop();if(!closed)db.close();});
  queue.defer('first','task',{id:1});queue.defer('second','task',{id:2});
  queue.start(async()=>{sends++;started();return rawSend;});await ready;
  const pending=queue.pending,at=performance.now();
  await assert.rejects(queue.stop(),{code:'NOTIFICATION_DRAIN_UNCERTAIN'});assert(performance.now()-at<500);
  assert.equal(queue.pending,pending);assert.equal(queue.busy,true);assert.equal(queue.timer,null);assert.equal(queue.drainWaiters.size,0);
  assert.equal(queue.pendingCount.get().n,2);assert.equal(sends,1);
  assert.throws(()=>queue.defer('late','task',{id:3}),{code:'NOTIFICATION_QUEUE_STOPPED'});
  assert.throws(()=>queue.start(async()=>assert.fail('restarted after stop')),{code:'NOTIFICATION_QUEUE_STOPPED'});
  await assert.rejects(queue.flush(async()=>assert.fail('dispatched after cutoff')),{code:'NOTIFICATION_QUEUE_STOPPED'});
  release({state:'sent'});await pending;await queue.stop();
  assert.equal(queue.pending,null);assert.equal(queue.busy,false);assert.equal(sends,1);assert.equal(queue.pendingCount.get().n,1);
  assert.equal(db.prepare('SELECT state FROM deferred_notifications WHERE key=?').get('first').state,'done');
  assert.equal(db.prepare('SELECT state FROM deferred_notifications WHERE key=?').get('second').state,'pending');
  db.close();closed=true;await queue.stop();
  await assert.rejects(queue.flush(async()=>assert.fail('post-close dispatch')),{code:'NOTIFICATION_QUEUE_STOPPED'});
  assert.throws(()=>queue.defer('late','task',{}),{code:'NOTIFICATION_QUEUE_STOPPED'});
});
test('direct flush is owned during stop and a late rejection stays pending without replay',async t=>{
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());let rejectSend,started,sends=0;
  const ready=new Promise(resolve=>started=resolve),rawSend=new Promise((_resolve,reject)=>rejectSend=reject);
  const queue=new NotificationQueue(db,()=>({enabled:false}),{drainTimeoutMs:15});queue.defer('one','task',{id:1});
  const flush=queue.flush(async()=>{sends++;started();return rawSend;});const failed=assert.rejects(flush,/TASK_ACCESS_DENIED/);await ready;
  const pending=queue.pending;await assert.rejects(queue.stop(),{code:'NOTIFICATION_DRAIN_UNCERTAIN'});
  await assert.rejects(queue.stop(),{code:'NOTIFICATION_DRAIN_UNCERTAIN'});assert.equal(queue.pending,pending);assert.equal(queue.drainWaiters.size,0);
  rejectSend(Error('TASK_ACCESS_DENIED'));await failed;await queue.stop();
  assert.equal(queue.pending,null);assert.equal(queue.busy,false);assert.equal(queue.pendingCount.get().n,1);assert.equal(sends,1);
  await assert.rejects(queue.flush(async()=>assert.fail('replayed after stop')),{code:'NOTIFICATION_QUEUE_STOPPED'});
});
test('stop before scheduled dispatch reads no closed DB and calls no sender',async()=>{
  const db=new DatabaseSync(':memory:');let reads=0,sends=0;
  const queue=new NotificationQueue(db,()=>{reads++;return {enabled:false};});assert.equal(queue.drainTimeoutMs,15000);queue.defer('one','task',{});
  const flush=queue.flush(async()=>{sends++;return {state:'sent'};});await queue.stop();await flush;assert.equal(sends,0);assert.equal(reads,1);
  db.close();await queue.stop();await assert.rejects(queue.flush(async()=>sends++),{code:'NOTIFICATION_QUEUE_STOPPED'});assert.equal(reads,1);
});
