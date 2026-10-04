import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {exampleConfig} from '../src/config.mjs';
import {startBridge} from '../src/bridge.mjs';

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
async function fixture(t,{limits={},ingest,onImported}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-bridge-limits-')),store=new Store(root),config=exampleConfig();
  config.bridge={enabled:true,host:'127.0.0.1',port:0,actorId:config.discord.operators[0],tokenEnv:'KOTODAMA_BRIDGE_LIMITS_TEST'};
  config.integrations.luma={eventRef:'event-fixture'};process.env.KOTODAMA_BRIDGE_LIMITS_TEST='synthetic-bounded-bridge-fixture';
  let calls=0;const server=await startBridge({config,store,limits,onImported,pipeline:{ingest:async(source,flags)=>{calls++;assert.deepEqual(flags,{execute:false,reply:false});return ingest?ingest(source,store):store.ingest(source);}}});
  t.after(async()=>{await server.drain();store.close();delete process.env.KOTODAMA_BRIDGE_LIMITS_TEST;await rm(root,{recursive:true,force:true});});
  const url='http://127.0.0.1:'+server.address().port,headers={authorization:'Bearer '+process.env.KOTODAMA_BRIDGE_LIMITS_TEST,'content-type':'application/json'};
  const body={eventRef:'event-fixture',revision:1,csv:'Name,Email,Ticket ID\nSample,sample@example.invalid,t1\n'};
  const send=(payload=body)=>fetch(url+'/v1/luma/import',{method:'POST',headers,body:JSON.stringify(payload)});
  return {store,server,url,headers,body,send,calls:()=>calls};
}
function slowUpload(f){
  const request=http.request(f.url+'/v1/luma/import',{method:'POST',headers:{...f.headers,'transfer-encoding':'chunked'}});
  const result=new Promise((resolve,reject)=>{request.once('response',response=>{let text='';response.on('data',chunk=>text+=chunk);response.once('end',()=>resolve({status:response.statusCode,body:JSON.parse(text)}));});request.once('error',reject);});
  request.flushHeaders();request.write('{');return {request,result};
}

test('bridge bounds slow upload admission and explicitly times out unfinished bodies',async t=>{
  const f=await fixture(t,{limits:{maxRequests:2,requestTimeoutMs:250}}),first=slowUpload(f),second=slowUpload(f);
  t.after(()=>{first.request.destroy();second.request.destroy();});
  // Requests on these sockets precede the health probe on a fresh socket.
  await Promise.all([new Promise(r=>first.request.once('socket',socket=>socket.once('connect',r))),new Promise(r=>second.request.once('socket',socket=>socket.once('connect',r)))]);
  const overflow=await fetch(f.url+'/health',{headers:f.headers});assert.equal(overflow.status,503);assert.deepEqual(await overflow.json(),{error:'BRIDGE_BUSY'});
  const results=await Promise.all([first.result,second.result]);assert(results.every(result=>result.status===408&&result.body.error==='BRIDGE_REQUEST_TIMEOUT'));assert.equal(f.calls(),0);
  assert.equal((await fetch(f.url+'/health',{headers:f.headers})).status,200);
});

test('oversized bridge bodies are refused before CSV parsing or ingestion',async t=>{
  const f=await fixture(t,{limits:{maxBodyBytes:64}}),response=await f.send();assert.equal(response.status,413);assert.deepEqual(await response.json(),{error:'BODY_TOO_LARGE'});assert.equal(f.calls(),0);
});

test('simultaneous duplicate CSV imports enter the ingestion writer only once',async t=>{
  const entered=deferred(),release=deferred(),f=await fixture(t,{ingest:async(source,store)=>{entered.resolve();await release.promise;return store.ingest(source);}});
  const first=f.send();await entered.promise;const rest=[f.send(),f.send()];release.resolve();
  const results=await Promise.all([first,...rest]);assert(results.every(response=>response.status===200));const receipts=await Promise.all(results.map(response=>response.json()));assert.equal(receipts.filter(receipt=>receipt.state==='duplicate').length,2);assert.equal(f.calls(),1);
});

test('timed-out ingestion keeps its writer and cancels queued revisions without duplicate effects',async t=>{
  const entered=deferred(),release=deferred(),f=await fixture(t,{limits:{maxRequests:2,requestTimeoutMs:100,drainTimeoutMs:40},ingest:async(source,store)=>{entered.resolve();await release.promise;return store.ingest(source);}});
  const first=f.send();await entered.promise;const queued=f.send({...f.body,revision:2,csv:f.body.csv.replace('t1','t2')});
  const [a,b]=await Promise.all([first,queued]);assert.equal(a.status,504);assert.equal((await a.json()).error,'BRIDGE_IMPORT_UNCERTAIN');assert.equal(b.status,408);
  const refused=await f.send();assert.equal(refused.status,503);assert.equal((await refused.json()).error,'BRIDGE_BUSY');assert.equal(f.calls(),1);
  await assert.rejects(f.server.drain(),{code:'BRIDGE_DRAIN_UNCERTAIN'});release.resolve();await f.server.drain();assert.equal(f.calls(),1);assert.equal(f.store.sources(f.body.actorId??exampleConfig().discord.operators[0]).length,1);
});

test('hung notifications have bounded admission and cannot stall later ingestion',async t=>{
  const release=deferred();let notifications=0;
  const f=await fixture(t,{limits:{notificationTimeoutMs:30,maxNotifications:1,drainTimeoutMs:30},onImported:()=>{notifications++;return release.promise;}});
  const first=await (await f.send()).json();assert.equal(first.notification.state,'unknown');
  const duplicate=await (await f.send()).json();assert.equal(duplicate.state,'duplicate');assert.equal(duplicate.notification.state,'unknown');
  const next=await (await f.send({...f.body,revision:2,csv:f.body.csv.replace('t1','t2')})).json();assert.equal(next.notification.state,'unavailable');assert.equal(f.calls(),2);assert.equal(notifications,1);
  await assert.rejects(f.server.drain(),{code:'BRIDGE_DRAIN_UNCERTAIN'});release.resolve({state:'sent'});await f.server.drain();
});

test('bridge authenticates UTF-8 credentials by byte length without leaking comparison errors',async t=>{
  const f=await fixture(t),response=await fetch(f.url+'/health',{headers:{authorization:'Bearer '+('é'.repeat(30))}});assert.equal(response.status,401);assert.deepEqual(await response.json(),{error:'UNAUTHORIZED'});
});
