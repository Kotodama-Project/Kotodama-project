import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,readdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Config,exampleConfig} from '../src/config.mjs';
import {Analysis} from '../src/llm.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {Store} from '../src/store.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {companyPackDigest,companyPackPaths} from '../src/company-pack-worker.mjs';
import {resultFiles} from '../src/result-files.mjs';
import {runCommand} from '../src/command.mjs';
const python=process.env.KOTODAMA_TEST_PYTHON??(process.platform==='win32'?'python':'python3');
const actor='100000000000000002';

async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-pack-runtime-')),dataDir=path.join(root,'data'),outputRoot=path.join(dataDir,'worktrees','company-pack-operations');await mkdir(outputRoot,{recursive:true});
  const base=exampleConfig({workspace:root}),config=Config.parse({...base,dataDir,worker:{...base.worker,executable:'model-must-not-run',actions:['create_company_pack'],verification:{kind:'docker',image:process.env.KOTODAMA_TEST_VERIFIER_IMAGE??'sha256:'+'a'.repeat(64)},companyPack:{pythonExecutable:python,outputRoot,ownerRef:'ref/local/synthetic-owner',workOrderRef:'work-order:synthetic-explicit',capabilityRef:'capability:synthetic-explicit',retentionPolicyRef:'retention-policy:synthetic-owner',authorityExpiresAt:new Date(Date.now()+3600000).toISOString()}}});
  const file=path.join(root,'config.json');await writeFile(file,JSON.stringify(config));let runtime;
  t.after(async()=>{await runtime?.close();assert.equal(path.dirname(root),os.tmpdir());await rm(root,{recursive:true,force:true});});
  return {root,config,file,outputRoot,start:async()=>{runtime=await startRuntime(file,{offline:true,log:()=>{}});return runtime;}};
}

test('Company Pack request digest matches the Python canonical format including Unicode',async()=>{
  const value={path:'/tmp/日本語/😀',owner_kind:'local',request:{revision:2,value:'line\nquote"'},flag:false};
  const script="import json,hashlib,sys; v=json.load(sys.stdin); print(hashlib.sha256((json.dumps(v,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\\n').encode('utf-8')).hexdigest())";
  const result=await runCommand(python,['-S','-c',script],{input:JSON.stringify(value),timeoutMs:10000});assert.equal(result.code,0,result.stderr);assert.equal(companyPackDigest(value),result.stdout.trim());
});

test('Company Pack action remains opt-in and cannot be emitted by an analyzer',()=>{
  const config=exampleConfig();assert(!config.worker.actions.includes('create_company_pack'));assert.equal(config.worker.companyPack,undefined);
  const result={summary:'fixture',intents:[{kind:'request',title:'fixture',request:'pack',action:'create_company_pack',explicit:true,complete:true,acceptance:[]}],replyRequested:false,reply:''};
  assert.equal(Analysis.safeParse(result).success,false);
});

test('Company Pack outputs cannot escape or occupy ordinary Task worktrees',async t=>{
  const f=await fixture(t);assert.equal(companyPackPaths(f.config).output,f.outputRoot);
  for(const outputRoot of [f.root,path.join(f.config.dataDir,'worktrees'),path.join(f.config.dataDir,'worktrees','task-other-r1'),path.join(f.config.dataDir,'worktrees','company-pack-results')]){
    const config=structuredClone(f.config);config.worker.companyPack.outputRoot=outputRoot;assert.throws(()=>companyPackPaths(config),{code:'COMPANY_PACK_OUTPUT_SCOPE'});
  }
});

test('disabled and remote requests stop before any owner or Source write',async t=>{
  const f=await fixture(t),store=new Store(f.config.dataDir);try{const source={provider:'discord',guildId:f.config.discord.guildId,channelId:f.config.discord.resultChannelId,sourceId:'explicit',actorId:actor,readers:[actor],revision:1,final:true,text:'fixture-company',metadata:{kind:'trusted_cli'}};
  const request={title:'fixture',request:'fixture-company',action:'create_company_pack'};let calls=0;
  const denied=structuredClone(f.config);denied.worker.actions=[];const p=new Pipeline({store,config:denied});await assert.rejects(p.request(source,request),{code:'ACTION_NOT_ALLOWED'});
  const remote=structuredClone(f.config);remote.owner={kind:'remote',url:'https://example.invalid',tokenEnv:'SYNTHETIC_OWNER'};
  const q=new Pipeline({store,config:remote,owner:{kind:'remote',ingest:async()=>calls++,createTask:async()=>calls++}});await assert.rejects(q.request(source,request),{code:'COMPANY_PACK_LOCAL_OWNER_REQUIRED'});
  assert.equal(calls,0);assert.equal(store.db.prepare('SELECT COUNT(*) AS n FROM sources').get().n,0);assert.equal(store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,0);
  }finally{store.close();}
});

test('Windows rejects the local write before starting a process or creating an operation',{
  skip:process.platform==='linux'?'Linux success is checked with the prepared Docker image':false
},async t=>{
  const f=await fixture(t),runtime=await f.start();const task=await controlCommand(f.config,{action:'request',actor,operation:'create_company_pack',text:'fixture-company',requestId:'windows-refusal'});await runtime.pipeline.tail;
  const current=runtime.store.task(task.id,actor);assert.equal(current.state,'failed');assert.equal(current.result.summary,'WRITE_WORKER_REQUIRES_LINUX_HOST');
  assert.equal(runtime.store.db.prepare("SELECT COUNT(*) AS n FROM events WHERE type='worker.started'").get().n,0);assert.deepEqual(await readdir(f.outputRoot),[]);
  await assert.rejects(readFile(path.join(f.config.dataDir,'runs','company-pack',`${task.id}-r1`,'request.json')),{code:'ENOENT'});
});

const realLinux=process.platform==='linux'&&Boolean(process.env.KOTODAMA_TEST_VERIFIER_IMAGE);
test('real Linux HTTP request creates one Task, Python Pack and isolated readback result',{
  skip:realLinux?false:'requires the explicitly prepared Linux Docker fixture',timeout:60000
},async t=>{
  const f=await fixture(t),runtime=await f.start();const input={action:'request',actor,operation:'create_company_pack',text:'fixture-company',requestId:'pack-e2e'};
  const task=await controlCommand(f.config,input);await runtime.pipeline.tail;const result=await controlCommand(f.config,{action:'result',actor,taskId:task.id});
  assert.equal(result.state,'needs_review');assert.equal(result.adapter,'company_pack_builtin_v1');assert.equal(result.modelExecution,null);assert.equal(result.validations[0].isolation.kind,'docker');assert.equal(result.validations[0].isolation.network,'none');assert.equal(result.validations[0].isolation.cleanupConfirmed,true);
  assert(result.artifacts.some(a=>a.relative==='pack/manifest.json'));const receipt=JSON.parse(await readFile(result.artifacts.find(a=>a.relative==='operation-receipt.json').path,'utf8'));
  assert.equal(receipt.task_ref,'task:'+task.id);assert.equal(receipt.record_binding.task_revision,task.revision);assert.equal(receipt.task_state_changed,false);assert.equal(receipt.record_binding.authority_verified,false);
  const attachments=await resultFiles(result,{artifactRoot:path.join(f.config.dataDir,'worktrees')});assert.equal(attachments.length,1);assert.equal(attachments[0].name,'company-pack.txt');
  const bundle=JSON.parse(attachments[0].attachment.toString('utf8'));assert.equal(bundle.taskId,task.id);assert.equal(bundle.packId,'fixture-company');assert(bundle.files.some(file=>file.path==='manifest.json'));assert(!attachments[0].attachment.includes(Buffer.from(f.config.dataDir)));
  assert.equal(runtime.store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,1);const starts=runtime.store.db.prepare("SELECT COUNT(*) AS n FROM events WHERE type='worker.started'").get().n;
  assert.equal((await controlCommand(f.config,input)).id,task.id);await runtime.pipeline.tail;assert.equal(runtime.store.db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,1);assert.equal(runtime.store.db.prepare("SELECT COUNT(*) AS n FROM events WHERE type='worker.started'").get().n,starts);
  assert.throws(()=>runtime.store.finish(task.id,task.revision,result),{code:'TASK_CHANGED'});
  const changed=structuredClone(f.config);changed.worker.actions=[];delete changed.worker.companyPack;await writeFile(f.file,JSON.stringify(changed));
  assert.equal((await controlCommand(f.config,{action:'result',actor,taskId:task.id})).taskRevision,task.revision);
  const artifact=result.artifacts.find(a=>a.relative==='pack/manifest.json');await writeFile(artifact.path,'{}');await assert.rejects(controlCommand(f.config,{action:'result',actor,taskId:task.id}),{code:'ARTIFACT_CHANGED'});
});

test('a changed Company Pack grant scope refuses admission without output',async t=>{
  const f=await fixture(t),runtime=await f.start(),changed=structuredClone(f.config);changed.worker.companyPack.workOrderRef='work-order:changed';await writeFile(f.file,JSON.stringify(changed));
  await assert.rejects(controlCommand(f.config,{action:'request',actor,operation:'create_company_pack',text:'fixture-company',requestId:'changed-scope'}),{code:'COMPANY_PACK_BINDING_CHANGED'});
  assert.deepEqual(await readdir(f.outputRoot),[]);assert.equal(runtime.store.db.prepare("SELECT COUNT(*) AS n FROM events WHERE type='worker.started'").get().n,0);
});

test('expired Company Pack authority refuses before any process or output',async t=>{
  const f=await fixture(t);f.config.worker.companyPack.authorityExpiresAt=new Date(Date.now()-1000).toISOString();await writeFile(f.file,JSON.stringify(f.config));const runtime=await f.start();
  await assert.rejects(controlCommand(f.config,{action:'request',actor,operation:'create_company_pack',text:'fixture-company',requestId:'expired'}),{code:'COMPANY_PACK_AUTHORITY_EXPIRED'});
  assert.deepEqual(await readdir(f.outputRoot),[]);assert.equal(runtime.store.db.prepare("SELECT COUNT(*) AS n FROM events WHERE type='worker.started'").get().n,0);
});
