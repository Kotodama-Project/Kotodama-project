import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson,inside} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {CliAnalyzer} from '../src/llm.mjs';
import {CliWorker} from '../src/worker.mjs';
import {runCommand} from '../src/command.mjs';
import {Store} from '../src/store.mjs';

const rootRepo=fileURLToPath(new URL('..',import.meta.url));const actor='100000000000000002';const fixtureCli=path.join(rootRepo,'tests/fixtures/model-cli.mjs');
async function configFixture(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-runtime-test-'));const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.analyzer={executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};config.worker={...config.worker,executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};const file=path.join(root,'config.json');await atomicJson(file,config);const cleanup=async()=>{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});};return {root,config,file,cleanup};}
test('real HTTP control and child CLI produce an artifact and verify its bytes',async t=>{
  const {config,file,cleanup}=await configFixture(t);const logs=[];const r=await startRuntime(file,{offline:true,log:v=>logs.push(v)});t.after(async()=>{await r.close();await cleanup();});
  const task=await controlCommand(config,{action:'request',actor,operation:'research',text:'合成情報を調べて',requestId:'same-request'});await r.pipeline.tail;
  const result=await controlCommand(config,{action:'result',actor,taskId:task.id});assert.equal(result.state,'needs_review');assert.equal(result.artifacts.length,1);assert((await readFile(result.artifacts[0].path,'utf8')).includes('合成の調査結果'));
  const duplicate=await controlCommand(config,{action:'request',actor,operation:'research',text:'合成情報を調べて',requestId:'same-request'});assert.equal(duplicate.id,task.id);assert.equal(r.store.tasks(actor).length,1);
  await assert.rejects(controlCommand(config,{action:'tasks',actor:'100000000000000009'}),/OPERATOR_REQUIRED/);assert(logs.some(v=>v.event==='runtime_ready'));
});
test('actual CLI analysis returns ToDos without executing them',async t=>{const {config,cleanup}=await configFixture(t);t.after(cleanup);const result=await new CliAnalyzer(config).analyze({text:'資料を作る案です',final:true},[]);assert.equal(result.intents[0].kind,'proposal');assert.equal(result.intents[0].explicit,false);});
test('completed prose is a worker document but cannot become structured intent',async t=>{const {config,root,cleanup}=await configFixture(t);t.after(cleanup);const cli=path.join(root,'prose.mjs');await writeFile(cli,"console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:'調査結果の本文です。'}}));",'utf8');config.worker.args=[cli];config.analyzer.args=[cli];const result=await new CliWorker(config).run({id:'task-prose',actor,revision:1,source_revision:1,action:'research',request:'調べて',acceptance:[]},[]);assert.equal(result.resultFormat,'text_summary');assert.equal(result.state,'needs_review');assert.equal(await readFile(result.artifacts[0].path,'utf8'),'調査結果の本文です。');await assert.rejects(new CliAnalyzer(config).analyze({text:'仕事をして',final:true},[]),/MODEL_JSON_INVALID/);});
test('failed remote owner initialization does not leave a runtime lock',async t=>{const {config,file,cleanup}=await configFixture(t);t.after(cleanup);config.owner={kind:'remote',url:'http://127.0.0.1:1',tokenEnv:'KOTODAMA_MISSING_TEST_TOKEN'};await atomicJson(file,config);await assert.rejects(startRuntime(file,{offline:true,log:()=>{}}),/OWNER_CREDENTIAL_REQUIRED/);const store=new Store(config.dataDir);try{assert.equal(store.lock(),undefined);}finally{store.close();}});
test('write worker includes unreported new files and supports later Task revisions',{skip:process.platform==='win32'?'Reference write worker runs on Linux; Windows CLI/client tests still run.':false},async t=>{
  const {config,root,cleanup}=await configFixture(t);t.after(cleanup);for(const args of [['init'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture']]){const r=await runCommand('git',args,{cwd:root});assert.equal(r.code,0);}
  config.worker.actions=['develop'];config.worker.args=[fixtureCli,'--fixture-write'];config.worker.verify=[{executable:process.execPath,args:['--check','created.mjs']}];const worker=new CliWorker(config);
  const base={id:'task-fixture',actor,source_revision:1,action:'develop',request:'create',acceptance:[]};const a=await worker.run({...base,revision:1},[]);const b=await worker.run({...base,revision:2},[]);assert.notEqual(a.workspace,b.workspace);assert(a.artifacts.some(f=>f.relative==='created.mjs'));const patch=a.artifacts.find(f=>f.relative==='changes.patch');assert((await readFile(patch.path,'utf8')).includes('created.mjs'));assert.equal(a.validations[0].exitCode,0);
});

test('a primary commit before authentication failure refuses fallback',{skip:process.platform==='win32'},async t=>{
  const {config,root,cleanup}=await configFixture(t);t.after(cleanup);
  for(const args of [['init'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture']])assert.equal((await runCommand('git',args,{cwd:root})).code,0);
  const primary=path.join(root,'primary.mjs');await writeFile(primary,`import {writeFileSync} from 'node:fs';import {execFileSync} from 'node:child_process';writeFileSync('committed.mjs','export const answer=1;');execFileSync('git',['add','committed.mjs']);execFileSync('git',['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','changed']);process.stderr.write('Not logged in.');process.exit(1);`,'utf8');
  config.worker.actions=['develop'];config.worker.args=[primary];config.worker.fallback={executable:process.execPath,args:[fixtureCli],model:'fallback-fixture',timeoutSeconds:10};const worker=new CliWorker(config);
  await assert.rejects(worker.run({id:'task-commit',actor,revision:1,source_revision:1,action:'develop',request:'fixture',acceptance:[]},[]),/FALLBACK_WORKSPACE_CHANGED/);
});
