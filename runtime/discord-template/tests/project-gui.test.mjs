import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {mkdtemp,mkdir,cp,symlink,rm} from 'node:fs/promises';
import {DatabaseSync} from 'node:sqlite';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {request as httpRequest} from 'node:http';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {sourceSnapshot} from '../src/source-bootstrap.mjs';

const templateRoot=fileURLToPath(new URL('..',import.meta.url));
const bridgeUrl=new URL('../../codex-task-bridge/server.mjs',import.meta.url);
const bridgeAvailable=existsSync(fileURLToPath(bridgeUrl));

function ready(child){
  return new Promise((resolve,reject)=>{
    let output='';const timer=setTimeout(()=>finish(new Error('GUI_FIXTURE_CLI_START_TIMEOUT')),10000);
    const finish=error=>{clearTimeout(timer);child.stdout.off('data',data);child.off('error',failed);child.off('exit',exited);error?reject(error):resolve();};
    const data=chunk=>{output+=chunk;if(output.length>65536)return finish(new Error('GUI_FIXTURE_CLI_OUTPUT_LIMIT'));if(output.includes('"event":"runtime_ready"'))finish();};
    const failed=()=>finish(new Error('GUI_FIXTURE_CLI_START_FAILED'));
    const exited=()=>finish(new Error('GUI_FIXTURE_CLI_EARLY_EXIT'));
    child.stdout.on('data',data);child.stderr.on('data',()=>{});child.once('error',failed);child.once('exit',exited);
  });
}

async function stop(child){
  if(!child?.pid||child.exitCode!==null||child.signalCode!==null)return;
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{child.kill('SIGKILL');},5000);
    const deadline=setTimeout(()=>{cleanup();reject(new Error('GUI_FIXTURE_CLI_STOP_TIMEOUT'));},8000);
    const cleanup=()=>{clearTimeout(timer);clearTimeout(deadline);child.off('exit',exited);};
    const exited=()=>{cleanup();resolve();};child.once('exit',exited);child.kill('SIGTERM');
  });
}

function bridgeRequest(origin,route,secret,principal,body){
  return new Promise((resolve,reject)=>{
    const bytes=body===undefined?null:JSON.stringify(body);
    const req=httpRequest(origin+route,{method:bytes===null?'GET':'POST',headers:{host:'fixture.invalid',authorization:'Bearer '+secret,
      'x-kotodama-principal':principal,...(bytes===null?{}:{'content-type':'application/json','content-length':Buffer.byteLength(bytes)})}},response=>{
      const chunks=[];let length=0;
      response.on('data',chunk=>{length+=chunk.length;if(length>750000){req.destroy(new Error('GUI_FIXTURE_RESPONSE_LIMIT'));return;}chunks.push(chunk);});
      response.on('error',reject);response.on('end',()=>{try{resolve({status:response.statusCode,body:JSON.parse(Buffer.concat(chunks).toString('utf8'))});}catch(error){reject(error);}});
    });
    req.setTimeout(10000,()=>req.destroy(new Error('GUI_FIXTURE_HTTP_TIMEOUT')));req.on('error',reject);req.end(bytes);
  });
}

for(const withTask of [false,true])test(`GUI bridge reads and inspects the pinned official Project v${withTask?2:1} owner without changing work`,
  {timeout:30000,skip:bridgeAvailable?false:'standalone template does not include the repository GUI bridge'},async t=>{
    // Production adapter imports stay dynamic so a standalone template remains
    // independently testable. Repository CI must exercise the real connector.
    const {startBriefBridge,projectionDigest}=await import(bridgeUrl.href);
    const {createProjectAdapter}=await import(new URL('../../codex-task-bridge/project-adapter.mjs',import.meta.url));
    const {syntheticSeed,syntheticCatalog}=await import(new URL('../../local-review-gateway/synthetic-fixture.mjs',import.meta.url));
    const root=await mkdtemp(path.join(tmpdir(),'ktdm-project-gui-')),app=path.join(root,'runtime');let child,bridge;
    t.after(async()=>{try{await bridge?.close();}finally{try{await stop(child);}finally{await rm(root,{recursive:true,force:true});}}});
    await mkdir(app);
    for(const name of ['bin','src','package.json','pnpm-lock.yaml'])await cp(path.join(templateRoot,name),path.join(app,name),{recursive:true});
    await symlink(path.join(templateRoot,'node_modules'),path.join(app,'node_modules'),process.platform==='win32'?'junction':'dir');
    const {exampleConfig}=await import(pathToFileURL(path.join(app,'src/config.mjs')).href);
    const {Store}=await import(pathToFileURL(path.join(app,'src/store.mjs')).href);
    const {controlCommand}=await import(pathToFileURL(path.join(app,'src/runtime.mjs')).href);
    const {atomicJson}=await import(pathToFileURL(path.join(app,'src/common.mjs')).href);
    const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.projects.operations=['read','create','inspect','link_task'];
    const file=path.join(root,'config.json');await atomicJson(file,config);
    const actor=config.discord.operators[0],store=new Store(config.dataDir);let source,existingTask;
    try{source=store.ingest({provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:'gui-synthetic-request',
      actorId:actor,revision:0,readers:[actor],final:true,text:'原意を保持してProjectを確認する',metadata:{kind:'text'}});
      if(withTask){const task=store.createTask(store.sourceInternal(source.key),{title:'既存仕事',request:'実行しない合成fixture',action:'research',acceptance:['参照だけ'],contextSources:[]});
        store.cancel(task.id,actor);existingTask=store.taskInternal(task.id);}
    }finally{store.close();}
    const env={...process.env,KOTODAMA_DEBUG:''};delete env.NODE_OPTIONS;
    child=spawn(process.execPath,[path.join(app,'bin/kotodama.mjs'),'start','--offline','--config',file],{env,stdio:['ignore','pipe','pipe'],windowsHide:true});await ready(child);
    const brief={outcome:'原意を保持する',in_scope:['読取と検査'],out_of_scope:['実行'],constraints:['公開しない'],acceptance:['同じProjectと版を読む'],unknowns:[]};
    let created=await controlCommand(config,{action:'project',actor,operation:'create',request_id:'gui-fixture-create',name:'GUI連携候補',source:{key:source.key,revision:0},brief});
    if(withTask)created=await controlCommand(config,{action:'project',actor,operation:'link_task',request_id:'gui-fixture-link',project_id:created.project.project_id,
      expected_revision:created.project.revision,base_digest:created.project_digest,source:{key:source.key,revision:0},reason:'既存Taskを参照する',task_id:existingTask.id,expected_task_revision:existingTask.revision});
    config.projects.operations=['read','inspect'];await atomicJson(file,config);
    const seed=syntheticSeed(),principal=seed.principal_ref,pin=(await sourceSnapshot(app)).binding.setDigest;
    const project={requesterRef:principal,actorId:actor,projectId:created.project.project_id,source:{key:source.key,revision:0},expiresAt:new Date(Date.now()+60000).toISOString(),
      operations:['read','inspect'],runtimeRoot:app,configFile:file,sourceSetDigest:pin};
    const status=await controlCommand(config,{action:'status'}),adapter=await createProjectAdapter(project);
    if(process.platform==='win32'){
      // The official runtime deliberately cannot attest loaded source on
      // Windows. Assert the real refusal instead of skipping or faking a pin.
      assert.equal(status.source.error,'SOURCE_BOOTSTRAP_UNSUPPORTED');await assert.rejects(adapter.read(principal),/project_connection_denied/);return;
    }
    assert.equal(status.source.error,undefined);assert.equal(status.source.setDigest,pin);
    await assert.rejects(createProjectAdapter({...project,sourceSetDigest:'0'.repeat(64)}),/project_connection_denied/);
    const seeds=syntheticCatalog([seed]),worker='urn:kotodama:principal:00000000-0000-4000-8000-000000000099';
    seeds.principals.push({principal_ref:worker,kind:'agent',actor:{subject:'synthetic-worker',email:null}});seed.access_policy.readers.push(worker);
    const stateRoot=path.join(root,'bridge-state'),reviewStateRoot=path.join(root,'bridge-review');await mkdir(stateRoot);await mkdir(reviewStateRoot);
    const secret=randomBytes(32).toString('hex');
    bridge=await startBriefBridge({stateRoot,reviewStateRoot,seeds,serviceSecret:secret,expectedHost:'fixture.invalid',runner:{},project,
      grant:{work_order_ref:'work-order:gui-fixture',requester_ref:principal,worker_ref:worker,handoff_id:seed.projection.handoff_id,source_revision:1,
        source_sha256:projectionDigest(seed.projection),policy_revision:1,expires_at:project.expiresAt,max_invocations:1,operation:'DRAFT_REQUIREMENTS'}},
      {invoke:async()=>assert.fail('GUI Project read/inspection must not invoke a model')});
    const call=(route,body)=>bridgeRequest(bridge.origin,route,secret,principal,body);
    const state=()=>{const db=new DatabaseSync(path.join(config.dataDir,'kotodama.sqlite'),{readOnly:true});try{return {
      projects:db.prepare('SELECT body FROM projects ORDER BY id').all(),versions:db.prepare('SELECT COUNT(*) AS n FROM project_versions').get().n,
      tasks:db.prepare('SELECT * FROM tasks ORDER BY id').all(),events:db.prepare('SELECT COUNT(*) AS n FROM events').get().n};}finally{db.close();}};
    const before=state();assert.equal(before.tasks.length,withTask?1:0);
    assert.equal((await bridgeRequest(bridge.origin,'/v1/project','invalid',principal)).status,401);
    const read=await call('/v1/project');assert.equal(read.status,200);assert.equal(read.body.view.project_digest,created.project_digest);
    assert.deepEqual(read.body.view.project.brief,brief);assert.equal(read.body.can_inspect,true);
    assert.equal(read.body.view.project.version,withTask?2:1);assert.deepEqual(read.body.view.project.task_refs,created.project.task_refs);
    const inspected=await call('/v1/project/inspect',{binding_sha256:read.body.binding_sha256,expected_revision:created.project.revision,base_digest:created.project_digest,
      reason:'制約を削除した場合の影響を確認',brief:{...brief,constraints:[]}});
    assert.equal(inspected.status,200);assert.equal(inspected.body.inspection.applied,false);
    assert.deepEqual(inspected.body.inspection.impact_task_refs,created.project.task_refs);
    assert.deepEqual(inspected.body.inspection.removed_requirements.constraints,['公開しない']);
    // Exercise owner-side currentness through the real HTTP/CLI/SQLite path,
    // rather than relying only on protocol fixtures or a mocked owner.
    const candidate={binding_sha256:read.body.binding_sha256,expected_revision:created.project.revision,base_digest:created.project_digest,
      reason:'不一致を拒否する',brief:{...brief,constraints:[]}};
    for(const extra of [{surface:'dots'},{surface:null},{action:'project'},{operation:'link_task'},
      {operation:'unlink_task'},{actor:'100000000000000009'},{project_id:'ref/project/other'},{source:{key:source.key,revision:0}}]){
      const denied=await call('/v1/project/inspect',{...candidate,...extra});
      assert.equal(denied.status,503);assert.deepEqual(denied.body,{error:'bridge_unavailable'});
      assert.deepEqual(state(),before,'GUI authority fields must not change Project, events or Task state');
    }
    for(const mismatch of [{expected_revision:created.project.revision+1},{base_digest:'0'.repeat(64)},{binding_sha256:'0'.repeat(64)}]){
      const denied=await call('/v1/project/inspect',{...candidate,...mismatch});
      assert.equal(denied.status,503);assert.deepEqual(denied.body,{error:'bridge_unavailable'});
      assert.deepEqual(state(),before,'rejected inspection must not change Project, events or Task state');
    }
    const wrongPrincipal=await bridgeRequest(bridge.origin,'/v1/project',secret,worker);
    assert.equal(wrongPrincipal.status,404);assert.deepEqual(wrongPrincipal.body,{error:'information_unavailable'});
    const reread=await call('/v1/project');assert.equal(reread.status,200);assert.equal(reread.body.view.project_digest,created.project_digest);assert.deepEqual(state(),before);
    config.projects.operations=[];await atomicJson(file,config);
    const revoked=await call('/v1/project');assert.equal(revoked.status,503);assert.deepEqual(revoked.body,{error:'bridge_unavailable'});
    assert.deepEqual(state(),before);
  });
