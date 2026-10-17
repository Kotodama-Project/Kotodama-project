import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,symlink} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson,digest,Refused} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';

const actor='100000000000000002';
const brief={outcome:'元の依頼を保つ',in_scope:['調査'],out_of_scope:['公開'],constraints:['原文を省略しない'],acceptance:['根拠を返す'],unknowns:['未確認の前提']};
async function fixture(t,{workerHook=null,realWorker=false}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-execution-'));
  const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');
  config.projects={operations:['create','read','correct','run_task','resume_task','read_task','read_result','link_task','unlink_task']};
  if(realWorker){config.worker.executable=process.execPath;config.worker.args=[fileURLToPath(new URL('./fixtures/model-cli.mjs',import.meta.url))];}
  const filename=path.join(root,'config.json');await atomicJson(filename,config);
  let runs=0,seen,summaryPath;
  const worker={run:async(task,context,options)=>{
    runs++;seen={task,context};await options.authorize();if(workerHook)await workerHook({task,context,...options});
    const dir=path.join(config.dataDir,'artifacts',`${task.id}-r${task.revision}`);await mkdir(dir,{recursive:true});
    summaryPath=path.join(dir,'result.md');const summary='合成workerの成果';await writeFile(summaryPath,summary);
    return {state:'needs_review',summary,artifacts:[{path:summaryPath,relative:'result.md',sha256:digest(summary),bytes:Buffer.byteLength(summary)}],validations:[],taskRevision:task.revision,sourceRevision:task.source_revision,verifiedExecution:true,independentReview:false};
  }};
  const start=()=>startRuntime(filename,{offline:true,...(realWorker?{}:{worker}),analyzer:{analyze:()=>{throw Error('unexpected analyzer');}},log:()=>{}});
  let runtime=await start();t.after(async()=>{await runtime.close();await rm(root,{recursive:true,force:true});});
  const raw={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'project-origin',actorId:actor,revision:1,final:true,readers:[actor],text:'公開せず資料を作る',metadata:{kind:'text'}};
  const source={key:runtime.store.ingest(raw).key,revision:1};
  const call=input=>controlCommand(config,{action:'project',actor,...input});
  const project=await call({operation:'create',name:'試験',request_id:'create',source,brief});
  const run={operation:'run_task',project_id:project.project.project_id,expected_revision:1,base_digest:project.project_digest,request_id:'run',source,reason:'この条件で実行',task:{title:'調査',request:'根拠をまとめる',action:'research',acceptance:['出典を記載']}};
  return {root,config,filename,source,raw,project,run,call,save:()=>atomicJson(filename,config),get runtime(){return runtime;},get runs(){return runs;},get seen(){return seen;},get summaryPath(){return summaryPath;},restart:async()=>{await runtime.close();runtime=await start();}};
}

test('Project execution uses one existing Task, retains complete conditions and reads real artifact after restart',async t=>{
  const f=await fixture(t),results=await Promise.all([f.call(f.run),f.call(f.run)]);
  await f.runtime.pipeline.tail;
  const taskId=results[0].task_ref.task_id;
  assert.equal(results[1].task_ref.task_id,taskId);assert.equal(f.runs,1);
  assert.equal(f.runtime.store.tasks(actor).length,1);
  assert.deepEqual(f.seen.task.acceptance,[...brief.acceptance,...f.run.task.acceptance]);
  assert.ok(f.seen.task.request.includes(JSON.stringify(brief)));
  assert.equal(f.seen.context[0].text,f.raw.text);
  assert.deepEqual(f.seen.task.projectBinding.sources,[f.source]);
  const args={project_id:f.run.project_id,task_id:taskId};
  let result=await f.call({operation:'read_result',...args});
  assert.equal(result.result.summary,'合成workerの成果');assert.equal(result.result_metadata.artifact_readback,'verified');
  assert.equal(result.completion,'not_observed');assert.equal(result.result.acceptance,'not_evaluated');
  assert.equal(JSON.stringify(result).includes(f.root),false);
  await f.restart();result=await f.call({operation:'read_result',...args});assert.equal(result.owner_state,'needs_review');
  assert.equal((await f.call(f.run)).dispatch.state,'not_repeated');assert.equal(f.runs,1);
  await assert.rejects(f.call({...f.run,task:{...f.run.task,request:'別の依頼'}}),/PROJECT_REQUEST_CONFLICT/);
});

test('run requires the operation grant, current action grant, exact Project version and unchanged Source',async t=>{
  const f=await fixture(t);
  for(const patch of [{expected_revision:2},{base_digest:'0'.repeat(64)},{task:{...f.run.task,action:'swarm_research'}},{task:{...f.run.task,actor:'other'}}])await assert.rejects(f.call({...f.run,...patch}));
  f.config.worker.actions=[];await f.save();await assert.rejects(f.call(f.run),/ACTION_NOT_ALLOWED/);
  f.config.worker.actions=['research'];f.config.projects.operations=f.config.projects.operations.filter(x=>x!=='run_task');await f.save();await assert.rejects(f.call(f.run),/PROJECT_OPERATION_NOT_ALLOWED/);
  f.config.projects.operations.push('run_task');await f.save();
  f.runtime.store.ingest({...f.raw,revision:2,text:'訂正'});await assert.rejects(f.call(f.run),/SOURCE_CHANGED/);
  assert.equal(f.runs,0);assert.equal(f.runtime.store.tasks(actor).length,0);
});

test('authorization revocation during Project check leaves no Task or Project write',async t=>{
  const f=await fixture(t);
  f.runtime.projects.authorizeSource=async()=>{f.config.worker.actions=[];await f.save();};
  await assert.rejects(f.call(f.run),/ACTION_NOT_ALLOWED/);
  assert.equal(f.runtime.store.tasks(actor).length,0);assert.equal(f.runs,0);
  assert.equal((await f.call({operation:'read',project_id:f.run.project_id})).project.revision,1);
});

test('failed admission is visible, retains one Task and replay never retries execution',async t=>{
  const f=await fixture(t);f.runtime.pipeline.authorize=async()=>{throw new Refused('GRANT_REVOKED');};
  const result=await f.call(f.run);
  assert.equal(result.dispatch.state,'refused');assert.equal(result.dispatch.reason,'GRANT_REVOKED');assert.equal(result.owner_state,'cancelled');
  assert.equal(f.runs,0);assert.equal((await f.call(f.run)).dispatch.state,'not_repeated');assert.equal(f.runtime.store.tasks(actor).length,1);
});

test('commit before dispatch crash recovers the same Task as paused, with no automatic execution',async t=>{
  const f=await fixture(t);f.runtime.projects.dispatchTask=async()=>{throw new Refused('SIMULATED_DISCONNECT');};
  const result=await f.call(f.run);assert.equal(result.owner_state,'queued');await f.restart();
  const replay=await f.call(f.run);assert.equal(replay.task_ref.task_id,result.task_ref.task_id);assert.equal(replay.dispatch.state,'not_repeated');
  const state=await f.call({operation:'read_task',project_id:f.run.project_id,task_id:result.task_ref.task_id});
  assert.equal(state.owner_state,'paused');assert.equal(f.runs,0);
});

test('cancelled or corrected work never returns old artifact content',async t=>{
  const f=await fixture(t),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const args={project_id:f.run.project_id,task_id:run.task_ref.task_id};
  await f.runtime.pipeline.stop(run.task_ref.task_id,actor);
  await assert.rejects(f.call({operation:'read_result',...args}),/PROJECT_TASK_CHANGED/);
  assert.equal((await f.call({operation:'read_task',...args})).owner_state,'cancelled');
});

test('Project condition correction during worker execution refuses publication',async t=>{
  let release,entered;const started=new Promise(resolve=>{entered=resolve;}),blocked=new Promise(resolve=>{release=resolve;});
  const f=await fixture(t,{workerHook:async({authorize})=>{entered();await blocked;await authorize();}});
  const run=await f.call(f.run);await started;
  try{await f.call({operation:'correct',project_id:f.run.project_id,expected_revision:2,base_digest:run.project_digest,request_id:'correct',source:f.source,reason:'制約を訂正',brief:{...brief,constraints:['更新した制約']}});}finally{release();}
  await f.runtime.pipeline.tail;
  const observed=await f.call({operation:'read_task',project_id:f.run.project_id,task_id:run.task_ref.task_id});
  assert.equal(observed.owner_state,'failed');await assert.rejects(f.call({operation:'read_result',project_id:f.run.project_id,task_id:run.task_ref.task_id}));
});

test('artifact tamper, replacement symlink and current Source revocation refuse readback',async t=>{
  const f=await fixture(t),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const input={operation:'read_result',project_id:f.run.project_id,task_id:run.task_ref.task_id};
  await writeFile(f.summaryPath,'改ざん');await assert.rejects(f.call(input),/ARTIFACT_CHANGED/);
  if(process.platform!=='win32'){await rm(f.summaryPath);const other=path.join(f.root,'outside.md');await writeFile(other,'合成workerの成果');await symlink(other,f.summaryPath);await assert.rejects(f.call(input));}
  f.runtime.store.ingest({...f.raw,revision:2,readers:[]});await assert.rejects(f.call(input),/SOURCE_ACCESS_DENIED/);
});

test('result readback rechecks authorization and Task after the asynchronous file read',async t=>{
  const f=await fixture(t),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const read=f.runtime.projects.readResult.bind(f.runtime.projects);
  f.runtime.projects.readResult=async task=>{const result=await read(task);f.runtime.store.cancel(task.id,actor);return result;};
  await assert.rejects(f.call({operation:'read_result',project_id:f.run.project_id,task_id:run.task_ref.task_id}),/PROJECT_TASK_CHANGED/);
});


test('explicit resume keeps the Task ID, changes its revision and cannot revive changed Project conditions',async t=>{
  const f=await fixture(t);f.runtime.projects.dispatchTask=async()=>{throw new Refused('SIMULATED_DISCONNECT');};
  const run=await f.call(f.run);await f.restart();
  const resume={operation:'resume_task',project_id:f.run.project_id,expected_revision:2,base_digest:run.project_digest,request_id:'resume',source:f.source,reason:'停止した同じ仕事を再開',task_id:run.task_ref.task_id,expected_task_revision:1};
  const resumed=await f.call(resume);await f.runtime.pipeline.tail;
  assert.equal(resumed.task_ref.task_id,run.task_ref.task_id);assert.equal(resumed.task_ref.revision,2);assert.equal(f.runs,1);
  assert.equal((await f.call(resume)).dispatch.state,'not_repeated');assert.equal(f.runs,1);
  assert.equal((await f.call({operation:'read_result',project_id:f.run.project_id,task_id:run.task_ref.task_id})).owner_state,'needs_review');
  await f.runtime.pipeline.stop(run.task_ref.task_id,actor);
  const changed=await f.call({operation:'correct',project_id:f.run.project_id,expected_revision:3,base_digest:resumed.project_digest,request_id:'change',source:f.source,reason:'別の条件',brief:{...brief,outcome:'変更した目的'}});
  await assert.rejects(f.call({...resume,request_id:'resume-changed',expected_revision:4,base_digest:changed.project_digest,expected_task_revision:3}),/PROJECT_TASK_CONTRACT_CHANGED/);
});


test('non-delivered artifact tampering still invalidates the whole result receipt',async t=>{
  const f=await fixture(t),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const task=f.runtime.store.taskInternal(run.task_ref.task_id),extra=path.join(path.dirname(f.summaryPath),'changes.patch');
  await writeFile(extra,'original patch');task.result.artifacts.push({path:extra,relative:'changes.patch',bytes:14,sha256:digest('original patch')});
  f.runtime.store.statement('UPDATE tasks SET result=? WHERE id=?').run(JSON.stringify(task.result),task.id);
  await writeFile(extra,'modified patch');
  await assert.rejects(f.call({operation:'read_result',project_id:f.run.project_id,task_id:task.id}),/ARTIFACT_CHANGED/);
});


test('resume from a fresh request preserves the original executable Source binding',async t=>{
  const f=await fixture(t);f.runtime.projects.dispatchTask=async()=>{throw new Refused('SIMULATED_DISCONNECT');};
  const run=await f.call(f.run);await f.restart();
  const fresh={...f.raw,sourceId:'fresh-resume-request',text:'止まった仕事を再開して'};
  const source={key:f.runtime.store.ingest(fresh).key,revision:1};
  const resumed=await f.call({operation:'resume_task',project_id:f.run.project_id,expected_revision:2,base_digest:run.project_digest,request_id:'fresh-resume',source,reason:'新しい相談から再開',task_id:run.task_ref.task_id,expected_task_revision:1});
  await f.runtime.pipeline.tail;assert.equal(resumed.dispatch.state,'admitted');assert.equal(f.runs,1);
  assert.deepEqual(f.seen.task.projectBinding.sources,[f.source]);
  assert.equal(f.runtime.store.taskInternal(run.task_ref.task_id).state,'needs_review');
});

test('Project reaches the real CLI subprocess and reads its saved result without a model provider',async t=>{
  const f=await fixture(t,{realWorker:true}),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const result=await f.call({operation:'read_result',project_id:f.run.project_id,task_id:run.task_ref.task_id});
  assert.equal(result.result.summary,'実プロセスを経由した合成の調査結果です。');
  const dir=path.join(f.config.dataDir,'artifacts',run.task_ref.task_id+'-r1');
  const receipt=JSON.parse(await readFile(path.join(dir,'input-receipt.json'),'utf8'));
  assert.equal(receipt.taskBinding.taskId,run.task_ref.task_id);assert.equal(receipt.status,'prepared');
  assert.equal(result.result_metadata.artifact_readback,'verified');
});


test('base64 deliverables remain inside the control response budget, oversized content is refused',async t=>{
  const f=await fixture(t),run=await f.call(f.run);await f.runtime.pipeline.tail;
  const task=f.runtime.store.taskInternal(run.task_ref.task_id),workspace=path.join(f.config.dataDir,'worktrees','synthetic');
  await mkdir(path.join(workspace,'deliverables'),{recursive:true});const file=path.join(workspace,'deliverables','report.txt');
  const set=async count=>{const bytes=Buffer.alloc(count,65);await writeFile(file,bytes);task.result.workspace=workspace;task.result.artifacts=task.result.artifacts.filter(a=>a.relative!=='deliverables/report.txt');task.result.artifacts.push({path:file,relative:'deliverables/report.txt',bytes:count,sha256:digest(bytes)});f.runtime.store.statement('UPDATE tasks SET result=? WHERE id=?').run(JSON.stringify(task.result),task.id);};
  const input={operation:'read_result',project_id:f.run.project_id,task_id:task.id};
  await set(400000);const result=await f.call(input);assert.equal(Buffer.from(result.result.files[0].data,'base64').length,400000);
  await set(600000);await assert.rejects(f.call(input),/PROJECT_RESULT_SIZE_LIMIT/);
});
