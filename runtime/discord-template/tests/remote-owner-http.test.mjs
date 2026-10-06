import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {RemoteOwner} from '../src/remote-owner.mjs';
import {Refused} from '../src/common.mjs';

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
async function fixture(t,handler,limits={}){
  process.env.KOTODAMA_OWNER_HTTP_TEST='synthetic-owner-fixture';let calls=0;
  const server=http.createServer(async(req,res)=>{const chunks=[];for await(const chunk of req)chunks.push(chunk);calls++;const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));assert.equal(req.headers.authorization,'Bearer synthetic-owner-fixture');assert.equal(body.version,1);handler(req,res,body);});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const owner=new RemoteOwner({url:'http://127.0.0.1:'+server.address().port,tokenEnv:'KOTODAMA_OWNER_HTTP_TEST'},limits);
  t.after(async()=>{await owner.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));delete process.env.KOTODAMA_OWNER_HTTP_TEST;});
  return {owner,calls:()=>calls};
}
function success(res,result){res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({version:1,ok:true,result}));}

test('remote owner admission is finite and refused calls never reach the HTTP owner',async t=>{
  const entered=deferred(),responses=[],f=await fixture(t,(_req,res)=>{responses.push(res);if(responses.length===2)entered.resolve();},{maxConcurrent:2});
  const calls=[f.owner.tasks('actor'),f.owner.tasks('actor')];await entered.promise;
  await assert.rejects(f.owner.tasks('actor'),{code:'OWNER_BUSY'});assert.equal(f.calls(),2);
  for(const res of responses)success(res,[{id:'stable-task'}]);assert.deepEqual(await Promise.all(calls),[[{id:'stable-task'}],[{id:'stable-task'}]]);assert.equal(f.owner.pending.size,0);
});

test('remote owner refuses an oversized outgoing write before dispatch',async t=>{
  const f=await fixture(t,(_req,res)=>success(res,null),{maxRequestBytes:128});
  await assert.rejects(f.owner.createTask({text:'x'.repeat(256)}),{code:'OWNER_REQUEST_LIMIT'});assert.equal(f.calls(),0);assert.equal(f.owner.pending.size,0);
});

test('remote owner response deadline cancels a hung streamed HTTP response',async t=>{
  const entered=deferred(),disconnected=deferred(),f=await fixture(t,(_req,res)=>{res.once('close',()=>disconnected.resolve());res.writeHead(200,{'content-type':'application/json'});res.write('{"version":1,');entered.resolve();});
  const result=assert.rejects(f.owner.tasks('actor'),{code:'OWNER_TIMEOUT'});
  await entered.promise;[...f.owner.pending][0].deadline.abort(new Refused('OWNER_TIMEOUT'));
  await result;await disconnected.promise;await f.owner.close();assert.equal(f.owner.pending.size,0);assert.equal(f.calls(),1);
});

test('a dispatched remote write reports uncertainty on deadline and is never retried',async t=>{
  const entered=deferred(),f=await fixture(t,(_req,res,body)=>{assert.equal(body.method,'createTask');res.writeHead(200,{'content-type':'application/json'});res.write('{');entered.resolve();});
  const result=assert.rejects(f.owner.createTask({id:'stable-task'}),{code:'OWNER_RESULT_UNCERTAIN'});
  // Observe actual dispatch before delivering the deadline signal. A short
  // wall-clock timeout can otherwise fire before localhost receives the write.
  await entered.promise;[...f.owner.pending][0].deadline.abort(new Refused('OWNER_TIMEOUT'));
  await result;await f.owner.close();assert.equal(f.calls(),1);
});

test('a remote connection loss after write dispatch remains uncertain with one request',async t=>{
  const f=await fixture(t,(_req,res)=>res.socket.destroy());await assert.rejects(f.owner.createTask({id:'stable-task'}),{code:'OWNER_RESULT_UNCERTAIN'});assert.equal(f.calls(),1);
});

test('an identical write is refused while its earlier request is still pending',async t=>{
  const entered=deferred();let response;
  const f=await fixture(t,(_req,res)=>{response=res;entered.resolve();},{maxConcurrent:2});
  const first=f.owner.createTask({id:'stable-task'});await entered.promise;
  await assert.rejects(f.owner.createTask({id:'stable-task'}),{code:'OWNER_WRITE_PENDING'});assert.equal(f.calls(),1);success(response,{id:'stable-task'});assert.deepEqual(await first,{id:'stable-task'});
});

test('declared oversized responses are cancelled before buffering their body',async t=>{
  const disconnected=deferred(),f=await fixture(t,(_req,res)=>{res.once('close',()=>disconnected.resolve());res.writeHead(200,{'content-length':1000});res.write('x');},{maxResponseBytes:128});
  await assert.rejects(f.owner.tasks('actor'),{code:'OWNER_RESPONSE_LIMIT'});await disconnected.promise;assert.equal(f.calls(),1);
});

test('closing the remote owner cancels current HTTP calls and refuses new dispatch',async t=>{
  const entered=deferred(),f=await fixture(t,(_req,res)=>{res.writeHead(200);res.write('{');entered.resolve();});
  const result=assert.rejects(f.owner.tasks('actor'),{code:'OWNER_STOPPING'});await entered.promise;await f.owner.close();await result;
  await assert.rejects(f.owner.tasks('actor'),{code:'OWNER_STOPPING'});assert.equal(f.calls(),1);assert.equal(f.owner.pending.size,0);
});

test('uncooperative fetch retains its admission slot after timeout and shutdown uncertainty',async t=>{
  const previous=globalThis.fetch,release=deferred();process.env.KOTODAMA_OWNER_HTTP_TEST='synthetic-owner-fixture';let calls=0;
  globalThis.fetch=()=>{calls++;return release.promise;};
  const owner=new RemoteOwner({url:'http://127.0.0.1:1',tokenEnv:'KOTODAMA_OWNER_HTTP_TEST'},{maxConcurrent:1,timeoutMs:30,drainTimeoutMs:30});
  t.after(()=>{globalThis.fetch=previous;delete process.env.KOTODAMA_OWNER_HTTP_TEST;});
  await assert.rejects(owner.createTask({id:'stable-task'}),{code:'OWNER_RESULT_UNCERTAIN'});assert.equal(owner.pending.size,1);
  await assert.rejects(owner.createTask({id:'stable-task'}),{code:'OWNER_BUSY'});await assert.rejects(owner.close(),{code:'OWNER_DRAIN_UNCERTAIN'});assert.equal(calls,1);
  release.resolve(new Response(JSON.stringify({version:1,ok:true,result:{id:'stable-task'}})));await owner.close();assert.equal(owner.pending.size,0);
});

test('invalid bounded JSON responses have an explicit protocol refusal',async t=>{
  const f=await fixture(t,(_req,res)=>{res.writeHead(200);res.end('{');});await assert.rejects(f.owner.tasks('actor'),{code:'OWNER_PROTOCOL_MISMATCH'});
});
