import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile,mkdir,link,symlink,lstat} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson,inside,Refused} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {CliAnalyzer} from '../src/llm.mjs';
import {CliWorker} from '../src/worker.mjs';
import {runCommand} from '../src/command.mjs';
import {Store} from '../src/store.mjs';
import fsPromises from 'node:fs/promises';
import {syncBuiltinESMExports} from 'node:module';
import {AccessMonitor} from '../src/access-grace.mjs';

// Synthetic subprocess fixture only. Real isolation is checked separately.
const fixtureVerifier={preflight:async()=>{},verify:async(command,options)=>({...await runCommand(command.executable,command.args,options),isolation:{kind:'synthetic_fixture'}})};
const rootRepo=fileURLToPath(new URL('..',import.meta.url));const actor='100000000000000002';const fixtureCli=path.join(rootRepo,'tests/fixtures/model-cli.mjs');
test('runtime metadata cannot redirect control credentials to an injected host',async t=>{
  const {config,cleanup}=await configFixture(t);t.after(cleanup);
  for(const port of ['80@external.example','80/path',0,65536]){
    await atomicJson(path.join(config.dataDir,'runtime.json'),{port,secretFile:'must-not-be-read'});
    await assert.rejects(controlCommand(config,{action:'status'}),{code:'RUNTIME_PORT_INVALID'});
  }
});
async function configFixture(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-runtime-test-'));const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.analyzer={executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};config.worker={...config.worker,executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};const file=path.join(root,'config.json');await atomicJson(file,config);const cleanup=async()=>{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});};return {root,config,file,cleanup};}
test('real HTTP control and child CLI produce an artifact and verify its bytes',async t=>{
  const {config,file,cleanup}=await configFixture(t);const logs=[];const r=await startRuntime(file,{offline:true,log:v=>logs.push(v)});t.after(async()=>{await r.close();await cleanup();});
  const task=await controlCommand(config,{action:'request',actor,operation:'research',text:'合成情報を調べて',requestId:'same-request'});await r.pipeline.tail;
  const result=await controlCommand(config,{action:'result',actor,taskId:task.id});assert.equal(result.state,'needs_review');assert.equal(result.artifacts.length,1);assert((await readFile(result.artifacts[0].path,'utf8')).includes('合成の調査結果'));
  const duplicate=await controlCommand(config,{action:'request',actor,operation:'research',text:'合成情報を調べて',requestId:'same-request'});assert.equal(duplicate.id,task.id);assert.equal(r.store.tasks(actor).length,1);
  await assert.rejects(controlCommand(config,{action:'tasks',actor:'100000000000000009'}),/OPERATOR_REQUIRED/);assert(logs.some(v=>v.event==='runtime_ready'));
});
test('task listing binds remote Tasks to the requesting actor and current access',async t=>{
  const {config,file,cleanup}=await configFixture(t),other='100000000000000009',tokenEnv='KOTODAMA_TASK_LIST_TEST',previousToken=process.env[tokenEnv];let runtime;
  process.env[tokenEnv]='synthetic-owner-fixture';config.owner={kind:'remote',url:'http://127.0.0.1:1',tokenEnv};config.discord.operators.push(other);await atomicJson(file,config);
  t.after(async()=>{await runtime?.close();if(previousToken===undefined)delete process.env[tokenEnv];else process.env[tokenEnv]=previousToken;await cleanup();});
  runtime=await startRuntime(file,{offline:true,log:()=>{}});
  const visible={id:'task-visible',actor,source_key:'source-visible',source_revision:1,state:'needs_review',title:'本人の仕事'};
  const foreign={...visible,id:'task-foreign',actor:other,source_key:'source-foreign',title:'別の操作者の仕事'},revoked={...visible,id:'task-revoked',source_key:'source-revoked'};
  let lists=0;const sources=[],readable=new Set(['source-visible','source-foreign']);
  runtime.owner.tasks=async principal=>{assert.equal(principal,actor);lists++;return [foreign,revoked,visible];};
  runtime.owner.source=async(key,principal)=>{sources.push([key,principal]);if(!readable.has(key))throw new Refused('SOURCE_ACCESS_DENIED');return {revision:1};};
  assert.deepEqual(await controlCommand(config,{action:'tasks',actor}),[visible]);
  assert.deepEqual(sources,[['source-revoked',actor],['source-visible',actor]]);assert.equal(runtime.store.tasks(actor).length,0);
  readable.delete('source-visible');assert.deepEqual(await controlCommand(config,{action:'tasks',actor}),[]);assert.equal(lists,2);
  config.discord.operators=[other];await atomicJson(file,config);
  await assert.rejects(controlCommand(config,{action:'tasks',actor}),{code:'OPERATOR_REQUIRED'});assert.equal(lists,2);
});
test('actual CLI analysis returns ToDos without executing them',async t=>{const {config,cleanup}=await configFixture(t);t.after(cleanup);const result=await new CliAnalyzer(config).analyze({text:'資料を作る案です',final:true},[]);assert.equal(result.intents[0].kind,'proposal');assert.equal(result.intents[0].explicit,false);});
test('completed prose is a worker document but cannot become structured intent',async t=>{const {config,root,cleanup}=await configFixture(t);t.after(cleanup);const cli=path.join(root,'prose.mjs');await writeFile(cli,"console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:'調査結果の本文です。'}}));",'utf8');config.worker.args=[cli];config.analyzer.args=[cli];const result=await new CliWorker(config).run({id:'task-prose',actor,revision:1,source_revision:1,action:'research',request:'調べて',acceptance:[]},[]);assert.equal(result.resultFormat,'text_summary');assert.equal(result.state,'needs_review');assert.equal(await readFile(result.artifacts[0].path,'utf8'),'調査結果の本文です。');await assert.rejects(new CliAnalyzer(config).analyze({text:'仕事をして',final:true},[]),/MODEL_JSON_INVALID/);});
test('failed remote owner initialization does not leave a runtime lock',async t=>{const {config,file,cleanup}=await configFixture(t);t.after(cleanup);config.owner={kind:'remote',url:'http://127.0.0.1:1',tokenEnv:'KOTODAMA_MISSING_TEST_TOKEN'};await atomicJson(file,config);await assert.rejects(startRuntime(file,{offline:true,log:()=>{}}),/OWNER_CREDENTIAL_REQUIRED/);const store=new Store(config.dataDir);try{assert.equal(store.lock(),undefined);}finally{store.close();}});
test('failed control listen releases its store and host lock before the same runtime restarts',async t=>{
  const {config,file,cleanup}=await configFixture(t),occupied=http.createServer();let runtime,failedStore;
  t.after(async()=>{t.mock.restoreAll();await runtime?.close();if(failedStore?.db.isOpen)failedStore.close();if(occupied.listening)await new Promise((resolve,reject)=>occupied.close(error=>error?reject(error):resolve()));await cleanup();});
  await new Promise((resolve,reject)=>{occupied.once('error',reject);occupied.listen(0,'127.0.0.1',resolve);});
  const port=occupied.address().port,originalListen=http.Server.prototype.listen,originalClaim=Store.prototype.claimHost;
  t.mock.method(http.Server.prototype,'listen',function(...args){if(args[0]===0&&args[1]==='127.0.0.1')args[0]=port;return originalListen.apply(this,args);});
  t.mock.method(Store.prototype,'claimHost',function(...args){failedStore=this;return originalClaim.apply(this,args);});
  await assert.rejects(startRuntime(file,{offline:true,log:()=>{}}),{code:'EADDRINUSE'});
  assert.equal(failedStore.db.isOpen,false,'failed startup closes its SQLite connection');
  t.mock.restoreAll();const reopened=new Store(config.dataDir);try{assert.equal(reopened.lock(),undefined);}finally{reopened.close();}
  runtime=await startRuntime(file,{offline:true,log:()=>{}});assert.equal((await controlCommand(config,{action:'status'})).discord,'offline_fixture');
  await runtime.close();const stopped=new Store(config.dataDir);try{assert.equal(stopped.lock(),undefined);}finally{stopped.close();}
});
test('an empty runtime domain leaves automatic stale-lock recovery disabled',async t=>{
  const {file,cleanup}=await configFixture(t);let runtime;t.after(async()=>{await runtime?.close();await cleanup();});runtime=await startRuntime(file,{offline:true,runtimeDomain:'',log:()=>{}});assert.equal(runtime.store.lock().domain,null);
});
test('runtime reclaims a stale host lock only after its recorded PID is gone',async t=>{
  const {config,file,cleanup}=await configFixture(t);let runtime;t.after(async()=>{await runtime?.close();await cleanup();});
  const stale=new Store(config.dataDir);stale.claimHost('stale-owner',2147483647,'2000-01-01T00:00:00.000Z','fixture-runtime');stale.close();
  runtime=await startRuntime(file,{offline:true,runtimeDomain:'fixture-runtime',log:()=>{}});const lock=runtime.store.lock();assert.match(lock.owner,/^host-/);assert.notEqual(lock.owner,'stale-owner');assert.equal(lock.pid,process.pid);assert.equal(lock.domain,'fixture-runtime');
});
test('runtime never reclaims a stale PID recorded by another runtime domain',async t=>{
  const {config,file,cleanup}=await configFixture(t);t.after(cleanup);const foreign=new Store(config.dataDir);foreign.claimHost('foreign-owner',2147483647,'2000-01-01T00:00:00.000Z','container-a');foreign.close();
  await assert.rejects(startRuntime(file,{offline:true,runtimeDomain:'container-b',log:()=>{}}),{code:'RUNTIME_RECOVERY_DOMAIN_MISMATCH'});const checkStore=new Store(config.dataDir);try{assert.equal(checkStore.lock().owner,'foreign-owner');}finally{checkStore.close();}
});
test('runtime never reclaims a host lock whose PID is still alive',async t=>{
  const {config,file,cleanup}=await configFixture(t);t.after(cleanup);const live=new Store(config.dataDir);live.claimHost('other-live-owner',process.pid,'2000-01-01T00:00:00.000Z','fixture-runtime');live.close();
  await assert.rejects(startRuntime(file,{offline:true,runtimeDomain:'fixture-runtime',log:()=>{}}),{code:'RUNTIME_ALREADY_OWNED'});const checkStore=new Store(config.dataDir);try{assert.equal(checkStore.lock().owner,'other-live-owner');}finally{checkStore.close();}
});

test('policy polling continues while only outage and recovery transitions are logged',async t=>{
  const {config,file,cleanup}=await configFixture(t),logs=[];
  const runtime=await startRuntime(file,{offline:true,log:value=>logs.push(value)});t.after(async()=>{await runtime.close();await cleanup();});
  const policyEvents=()=>logs.filter(value=>['policy_unavailable','policy_restored'].includes(value.event)).map(value=>value.event);
  const waitFor=async condition=>{const deadline=Date.now()+5000;while(!condition()){assert(Date.now()<deadline,'policy monitor did not reach the expected state');await new Promise(resolve=>setTimeout(resolve,10));}};
  const nextPoll=async()=>{const previous=runtime.pipeline.policy();await waitFor(()=>runtime.pipeline.policy()!==previous);};

  await writeFile(file,'{');await waitFor(()=>policyEvents().length===1);
  assert.deepEqual(runtime.pipeline.policy().discord.operators,[]);assert.deepEqual(runtime.pipeline.policy().voice.participantIds,[]);
  await nextPoll();assert.deepEqual(policyEvents(),['policy_unavailable']);
  await writeFile(file,'{}');await nextPoll();assert.deepEqual(policyEvents(),['policy_unavailable']);

  await atomicJson(file,config);await waitFor(()=>policyEvents().length===2);
  assert.deepEqual(runtime.pipeline.policy().discord.operators,config.discord.operators);
  await nextPoll();assert.deepEqual(policyEvents(),['policy_unavailable','policy_restored']);
  await writeFile(file,'{');await waitFor(()=>policyEvents().length===3);
  assert.deepEqual(policyEvents(),['policy_unavailable','policy_restored','policy_unavailable']);
  assert.deepEqual(runtime.pipeline.policy().discord.operators,[]);
});

for(const failure of [false,true])test(`shutdown retains a pending policy read and skips late pruning (${failure?'failed':'successful'} read)`,async t=>{
  const {config,file,cleanup}=await configFixture(t);let runtime,entered,release;
  const ready=new Promise(resolve=>entered=resolve),gate=new Promise(resolve=>release=resolve);
  t.after(async()=>{release();t.mock.restoreAll();syncBuiltinESMExports();await runtime?.close();await cleanup();});
  config.dots={...config.dots,enabled:true,actorId:actor,channelIds:[config.discord.resultChannelId]};await atomicJson(file,config);
  runtime=await startRuntime(file,{offline:true,log:()=>{}});runtime.dots.lastPrunedAt=0;
  const previousPolicy=runtime.pipeline.policy(),originalRead=fsPromises.readFile,originalDrain=AccessMonitor.prototype.drain;let intercepted=false,prunes=0;
  t.mock.method(runtime.dots,'prune',()=>{prunes++;assert(runtime.store.db.isOpen);});
  t.mock.method(fsPromises,'readFile',async function(filename,...args){if(filename===file&&!intercepted){intercepted=true;entered();await gate;if(failure)throw Error('synthetic read failure');}return originalRead.call(this,filename,...args);});syncBuiltinESMExports();
  t.mock.method(AccessMonitor.prototype,'drain',function(options){return originalDrain.call(this,{...options,timeoutMs:20});});
  await ready;await assert.rejects(runtime.close(),{code:'POLICY_DRAIN_UNCERTAIN'});
  assert.equal(runtime.store.db.isOpen,true);assert.equal(runtime.store.lock().pid,process.pid);assert.equal(prunes,0);
  release();await runtime.close();assert.equal(runtime.store.db.isOpen,false);assert.equal(prunes,0);assert.equal(runtime.pipeline.policy(),previousPolicy);
  const reopened=new Store(config.dataDir);try{assert.equal(reopened.lock(),undefined);}finally{reopened.close();}
});

test('shutdown drains the actual monitor probe after its check deadline has returned',async t=>{
  const {config,file,cleanup}=await configFixture(t);let release,entered,returned;
  const gate=new Promise(resolve=>release=resolve),ready=new Promise(resolve=>entered=resolve),checked=new Promise(resolve=>returned=resolve);
  const runtime=await startRuntime(file,{offline:true,log:()=>{}});
  t.after(async()=>{release();runtime.pipeline.active.clear();t.mock.restoreAll();await runtime.close();await cleanup();});
  const source={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'monitor-fixture',actorId:actor,readers:[actor],revision:1,final:true,text:'合成の監視fixture'};
  const key=runtime.store.ingest(source).key,task=runtime.store.createTask(runtime.store.source(key,actor),{title:'fixture',request:'fixture',action:'research',acceptance:[],key:'fixture'});runtime.store.claim(task.id,task.revision);
  const controller=new AbortController();runtime.pipeline.active.set(task.id,{revision:task.revision,controller});
  const taskInternal=runtime.owner.taskInternal.bind(runtime.owner),originalCheck=AccessMonitor.prototype.check,originalDrain=AccessMonitor.prototype.drain;let contexts=0;
  runtime.owner.taskInternal=async id=>{entered();await gate;assert(runtime.store.db.isOpen,'raw verifier still owns SQLite');return taskInternal(id);};
  runtime.owner.assertContext=()=>{contexts++;};
  t.mock.method(AccessMonitor.prototype,'check',async function(id,probe){this.limitMs=10;const result=await originalCheck.call(this,id,probe);returned();return result;});
  t.mock.method(AccessMonitor.prototype,'drain',function(options){return originalDrain.call(this,{...options,timeoutMs:20});});
  await ready;await checked;await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(runtime.close(),{code:'POLICY_DRAIN_UNCERTAIN'});assert.equal(controller.signal.aborted,true);assert.equal(runtime.store.lock().pid,process.pid);
  release();await runtime.close();assert.equal(contexts,0,'a resumed probe stops before its next Store call');assert.equal(runtime.store.db.isOpen,false);
});

test('an unexpected policy-cycle failure stops active workers and logs once while polling continues',async t=>{
  const {config,file,cleanup}=await configFixture(t),logs=[];config.dots={...config.dots,enabled:true,actorId:actor,channelIds:[config.discord.resultChannelId]};await atomicJson(file,config);
  const runtime=await startRuntime(file,{offline:true,log:value=>logs.push(value)}),controller=new AbortController();let polls=0;
  t.after(async()=>{runtime.pipeline.active.clear();await runtime.close();await cleanup();});
  runtime.pipeline.active.set('synthetic-active-worker',{controller});runtime.dots.prune=()=>{polls++;throw new Refused('POLICY_PRUNE_FAILED');};
  const deadline=Date.now()+5000;while(polls<2){assert(Date.now()<deadline,'policy monitor stopped polling');await new Promise(resolve=>setTimeout(resolve,10));}
  assert.equal(controller.signal.aborted,true);assert.equal(logs.filter(value=>value.event==='policy_check_failed').length,1);assert.equal(logs.find(value=>value.event==='policy_check_failed').code,'POLICY_PRUNE_FAILED');
});

test('control admits eight commands, rejects excess, and keeps status responsive',async t=>{
  const {config,file,cleanup}=await configFixture(t),runtime=await startRuntime(file,{offline:true,log:()=>{}});let release;
  const gate=new Promise(resolve=>{release=resolve;});let calls=0;
  t.after(async()=>{release();await runtime.close();await cleanup();});
  runtime.owner.tasks=async()=>{calls++;await gate;return [];};
  const metadata=JSON.parse(await readFile(path.join(config.dataDir,'runtime.json'),'utf8')),token=await readFile(path.join(config.dataDir,'control.secret'),'utf8');
  assert(Number.isInteger(metadata.port)&&metadata.port>=1&&metadata.port<=65535);assert.match(token,/^[a-f0-9]{64}$/);
  const send=()=>fetch(`http://127.0.0.1:${metadata.port}/v1/command`,{method:'POST',redirect:'error',headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify({action:'tasks',actor})});
  const active=Array.from({length:8},send);
  for(let tries=0;calls<8&&tries<200;tries++)await new Promise(resolve=>setTimeout(resolve,5));assert.equal(calls,8);
  const busy=await send();assert.equal(busy.status,503);assert.equal((await busy.json()).error,'CONTROL_BUSY');assert.equal(calls,8);
  assert.equal((await controlCommand(config,{action:'status'})).discord,'offline_fixture');release();
  for(const response of await Promise.all(active)){assert.equal(response.status,200);assert.deepEqual((await response.json()).result,[]);}
});

test('control rejects declared oversize before buffering and drains incomplete uploads on shutdown',async t=>{
  const {config,file,cleanup}=await configFixture(t),runtime=await startRuntime(file,{offline:true,log:()=>{}});
  t.after(async()=>{await runtime.close();await cleanup();});
  const metadata=JSON.parse(await readFile(path.join(config.dataDir,'runtime.json'),'utf8')),token=await readFile(path.join(config.dataDir,'control.secret'),'utf8');
  assert(Number.isInteger(metadata.port)&&metadata.port>=1&&metadata.port<=65535);assert.match(token,/^[a-f0-9]{64}$/);
  const headers={authorization:'Bearer '+token,'content-type':'application/json'};
  const refused=await new Promise((resolve,reject)=>{
    const req=http.request({hostname:'127.0.0.1',port:metadata.port,path:'/v1/command',method:'POST',headers:{...headers,'content-length':200001}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});req.on('error',reject);req.flushHeaders();
  });assert.equal(refused,413);
  const slow=http.request({hostname:'127.0.0.1',port:metadata.port,path:'/v1/command',method:'POST',headers});slow.on('error',()=>{});slow.on('response',res=>res.resume());slow.write('{"action":');
  await new Promise(resolve=>setTimeout(resolve,20));
  const closing=runtime.close();assert.equal(runtime.close(),closing);await closing;slow.destroy();
  const reopened=new Store(config.dataDir);try{assert.equal(reopened.lock(),undefined);assert.equal(reopened.tasks(actor).length,0);}finally{reopened.close();}
});

test('uncertain owner drain retains SQLite ownership and a later close retries safely',async t=>{
  const {config,file,cleanup}=await configFixture(t);process.env.KOTODAMA_RUNTIME_DRAIN_TEST='fixture';
  config.owner={kind:'remote',url:'http://127.0.0.1:1',tokenEnv:'KOTODAMA_RUNTIME_DRAIN_TEST'};await atomicJson(file,config);
  const runtime=await startRuntime(file,{offline:true,log:()=>{}});let calls=0;
  const controller=new AbortController();runtime.pipeline.active.set('shutdown-fixture',{controller});
  const pipelineClose=runtime.pipeline.close.bind(runtime.pipeline);runtime.pipeline.close=async()=>{assert.equal(controller.signal.aborted,true,'workers stop before later drains');runtime.pipeline.active.delete('shutdown-fixture');await pipelineClose();};
  const originalClose=runtime.owner.close.bind(runtime.owner);
  runtime.owner.close=async()=>{if(++calls===1)throw new Refused('OWNER_DRAIN_UNCERTAIN');await originalClose();};
  t.after(async()=>{await runtime.close();delete process.env.KOTODAMA_RUNTIME_DRAIN_TEST;await cleanup();});
  await assert.rejects(runtime.close(),{code:'OWNER_DRAIN_UNCERTAIN'});assert.equal(runtime.store.lock().pid,process.pid);assert.equal(runtime.store.db.prepare('SELECT count(*) AS n FROM sources').get().n,0);
  await runtime.close();assert.equal(calls,2);const reopened=new Store(config.dataDir);try{assert.equal(reopened.lock(),undefined);}finally{reopened.close();}
});
test('runtime replaces an existing linked control token without writing through it',async t=>{
  const {config,file,root,cleanup}=await configFixture(t);await mkdir(config.dataDir,{recursive:true});
  const outside=path.join(root,'outside-secret'),secret=path.join(config.dataDir,'control.secret');await writeFile(outside,'preserve-me');await link(outside,secret);
  const runtime=await startRuntime(file,{offline:true,log:()=>{}});t.after(async()=>{await runtime.close();await cleanup();});
  assert.equal(await readFile(outside,'utf8'),'preserve-me');assert.match(await readFile(secret,'utf8'),/^[a-f0-9]{64}$/);const stat=await lstat(secret);assert.equal(stat.nlink,1);if(process.platform!=='win32')assert.equal(stat.mode&0o777,0o600);
});
test('runtime refuses a symbolic control token without changing its target',{skip:process.platform==='win32'?'Symlink creation requires a separate Windows privilege; Linux CI covers this refusal.':false},async t=>{
  const {config,file,root,cleanup}=await configFixture(t);t.after(cleanup);await mkdir(config.dataDir,{recursive:true});const outside=path.join(root,'outside-symlink-target'),secret=path.join(config.dataDir,'control.secret');await writeFile(outside,'preserve-me');await symlink(outside,secret,'file');
  await assert.rejects(startRuntime(file,{offline:true,log:()=>{}}),{code:'LINK_PATH_REFUSED'});assert.equal(await readFile(outside,'utf8'),'preserve-me');const store=new Store(config.dataDir);try{assert.equal(store.lock(),undefined);}finally{store.close();}
});
test('write worker includes unreported new files and supports later Task revisions',{skip:process.platform==='win32'?'Reference write worker runs on Linux; Windows CLI/client tests still run.':false},async t=>{
  const {config,root,cleanup}=await configFixture(t);t.after(cleanup);for(const args of [['init'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture']]){const r=await runCommand('git',args,{cwd:root});assert.equal(r.code,0);}
  config.worker.actions=['develop'];config.worker.args=[fixtureCli,'--fixture-write'];config.worker.verify=[{executable:process.execPath,args:['--check','created.mjs']}];const worker=new CliWorker(config,{verifier:fixtureVerifier});
  const base={id:'task-fixture',actor,source_revision:1,action:'develop',request:'create',acceptance:[]};const a=await worker.run({...base,revision:1},[]);const b=await worker.run({...base,revision:2},[]);assert.notEqual(a.workspace,b.workspace);assert(a.artifacts.some(f=>f.relative==='created.mjs'));const patch=a.artifacts.find(f=>f.relative==='changes.patch');assert((await readFile(patch.path,'utf8')).includes('created.mjs'));assert.equal(a.validations[0].exitCode,0);
});

test('a primary commit before authentication failure refuses fallback',{skip:process.platform==='win32'},async t=>{
  const {config,root,cleanup}=await configFixture(t);t.after(cleanup);
  for(const args of [['init'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture']])assert.equal((await runCommand('git',args,{cwd:root})).code,0);
  const primary=path.join(root,'primary.mjs');await writeFile(primary,`import {writeFileSync} from 'node:fs';import {execFileSync} from 'node:child_process';writeFileSync('committed.mjs','export const answer=1;');execFileSync('git',['add','committed.mjs']);execFileSync('git',['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','changed']);process.stderr.write('Not logged in.');process.exit(1);`,'utf8');
  config.worker.actions=['develop'];config.worker.verify=[{executable:process.execPath,args:['--version']}];config.worker.args=[primary];config.worker.fallback={executable:process.execPath,args:[fixtureCli],model:'fallback-fixture',timeoutSeconds:10};const worker=new CliWorker(config,{verifier:fixtureVerifier});
  await assert.rejects(worker.run({id:'task-commit',actor,revision:1,source_revision:1,action:'develop',request:'fixture',acceptance:[]},[]),/FALLBACK_WORKSPACE_CHANGED/);
});
