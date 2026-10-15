// Fixed offline workload against the actual scheduler; no model or child worker.
import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';
import {TaskAdmission} from '../discord-template/src/task-admission.mjs';

const [widthText,workload]=process.argv.slice(2),width=Number(widthText);
assert(['1','2','4'].includes(widthText)&&['wait','cpu'].includes(workload));
assert.equal(Number(process.versions.node.split('.')[0]),24);
const COUNT=16,ITERATIONS=262144,WAIT_MS=40;
const task=(index,action='research')=>({id:`fixture-${index}`,actor:`actor-${index}`,room:`room-${index}`,revision:1,action});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const turn=()=>new Promise(resolve=>setImmediate(resolve));

async function verifyMechanisms(){
  const gate=new TaskAdmission(()=>({maxConcurrentReadOnly:1,maxQueued:1}));
  const held=deferred(),controller=new AbortController();let secondStarted=false;
  const jobs=gate.submitBatch([
    {task:task(0),operation:async()=>{await held.promise;if(controller.signal.aborted)throw Error('CANCELLED');}},
    {task:task(1),operation:async()=>{secondStarted=true;}}
  ]);
  const outcomes=Promise.allSettled(jobs);
  await turn();controller.abort();
  assert.equal(gate.cancel('fixture-0:1'),false);
  await turn();assert.equal(secondStarted,false);assert.equal(gate.status().running,1);
  assert.equal(gate.status().queued,1);
  assert.throws(()=>gate.submitBatch([{task:task(2),operation:async()=>{throw Error('OVERFLOW_DISPATCHED');}}]),/TASK_QUEUE_FULL/);
  assert.equal(gate.status().queued,1);
  held.resolve();const results=await outcomes;await gate.idle();
  assert.equal(results[0].status,'rejected');assert.equal(results[1].status,'fulfilled');
  assert.equal(secondStarted,true);assert.equal(gate.status().running,0);
  await gate.close();

  const barrier=new TaskAdmission(()=>({maxConcurrentReadOnly:4}));
  const before=deferred(),writer=deferred(),started=[];
  const barrierJobs=barrier.submitBatch([
    {task:task(0),operation:async()=>{started.push('reader-before');await before.promise;}},
    {task:task(1,'develop'),operation:async()=>{started.push('writer');await writer.promise;}},
    {task:task(2),operation:async()=>{started.push('reader-after');}}
  ]);
  await turn();assert.deepEqual(started,['reader-before']);
  before.resolve();await turn();assert.deepEqual(started,['reader-before','writer']);
  writer.resolve();await Promise.all(barrierJobs);await barrier.idle();await barrier.close();
  assert.deepEqual(started,['reader-before','writer','reader-after']);
  return {overflow_refused:true,cancel_retains_slot_until_settlement:true,writer_barrier:true};
}

try{
  const verification=await verifyMechanisms();
  const gate=new TaskAdmission(()=>({maxConcurrentReadOnly:width,maxQueued:COUNT}));
  const rows=[],submitted=performance.now();let active=0,peak=0;
  const jobs=gate.submitBatch(Array.from({length:COUNT},(_,index)=>({task:task(index),operation:async()=>{
    const started=performance.now();active++;peak=Math.max(peak,active);assert(active<=width);
    let value=index+1;
    if(workload==='wait')await new Promise(resolve=>setTimeout(resolve,WAIT_MS));
    else for(let step=0;step<ITERATIONS;step++)value=(Math.imul(value,1664525)+1013904223)>>>0;
    const settled=performance.now();active--;
    rows.push({index,value,queue_wait_ms:started-submitted,execution_ms:settled-started,completion_ms:settled-submitted});
  }})));
  const initial=gate.status();assert.equal(initial.running,width);assert.equal(initial.queued,COUNT-width);
  await Promise.all(jobs);await gate.idle();const finished=performance.now();
  assert.equal(rows.length,COUNT);assert.equal(new Set(rows.map(row=>row.index)).size,COUNT);
  assert.equal(gate.status().running,0);assert.equal(gate.status().queued,0);await gate.close();
  console.log(JSON.stringify({schema:'kotodama.task-admission-fixture.v1',status:'PASS',node:process.version,
    width,workload,tasks:COUNT,iterations:ITERATIONS,wait_ms:WAIT_MS,rows:rows.sort((a,b)=>a.index-b.index),
    workload_wall_ms:finished-submitted,initial_queued:initial.queued,peak_active:peak,
    verification:{...verification,all_tasks_settled:true,queue_drained:true,concurrency_bound:true}}));
}catch{
  console.log(JSON.stringify({schema:'kotodama.task-admission-fixture.v1',status:'FAIL',code:'FIXTURE_FAILED'}));
  process.exitCode=1;
}
