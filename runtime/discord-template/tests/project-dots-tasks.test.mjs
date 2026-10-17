import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {request} from 'node:http';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {exampleConfig,loadConfig} from '../src/config.mjs';
import {atomicJson} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {DiscordAdapter} from '../src/discord.mjs';

const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const actor='100000000000000002',channel='100000000000000003';
const operations=['read','create','inspect','correct','link_task','unlink_task','read_task'];
const taskOperations=['read','link_task','unlink_task','read_task'];
const brief={outcome:'要件と仕事を結び付ける',in_scope:[],out_of_scope:[],constraints:['原意を保持する'],acceptance:['担当成果を確認できる'],unknowns:[]};
const code=result=>result.content?.[0]?.text;

function controlPost(port,route,body,authorization){
  assert(Number.isInteger(port)&&port>=1&&port<=65535,'synthetic control port must be a valid integer');
  assert(['/v1/project','/v1/command'].includes(route),'only fixed control routes are allowed');
  return new Promise((resolve,reject)=>{
    // Separate options prevent a file-derived port from changing the host.
    // node:http does not follow redirects with the synthetic bearer credential.
    const outgoing=request({hostname:'127.0.0.1',port,path:route,method:'POST',
      headers:{'content-type':'application/json',...(authorization===undefined?{}:{authorization})}},response=>{
      const chunks=[];
      response.on('data',chunk=>chunks.push(chunk));response.on('error',reject);
      response.on('end',()=>{
        try{resolve({status:response.statusCode,body:JSON.parse(Buffer.concat(chunks).toString('utf8'))});}
        catch(error){reject(error);}
      });
    });
    outgoing.on('error',reject);
    outgoing.end(typeof body==='string'?body:JSON.stringify(body));
  });
}

test('synthetic control requests reject a file-derived URL authority or route',()=>{
  for(const port of ['12345@outbound.invalid', '12345',0,65536,1.5,null,{},NaN]){
    assert.throws(()=>controlPost(port,'/v1/project',{},undefined),/valid integer/);
  }
  for(const route of ['http://outbound.invalid','//outbound.invalid','/v1/project?redirect=1']){
    assert.throws(()=>controlPost(12345,route,{},undefined),/fixed control routes/);
  }
});

async function fixture(t,{dotsOperations=taskOperations,worker}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-dots-tasks-')),config=exampleConfig({workspace:root}),cleanups=[];
  t.after(async()=>{try{for(const cleanup of cleanups.reverse())await cleanup();}finally{assert(path.basename(root).startsWith('ktdm-project-dots-tasks-'));await rm(root,{recursive:true,force:true});}});
  config.dataDir=path.join(root,'data');config.projects={operations:[...operations,'run_task','resume_task','read_result']};
  config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600,projectOperations:dotsOperations};
  // Publish a complete grant update; the policy watcher must not observe a
  // truncate/write gap and exercise the unrelated malformed-config refusal.
  const file=path.join(root,'bot.json'),save=()=>atomicJson(file,config);await save();
  const runtime=await startRuntime(file,{offline:true,log:()=>{},...(worker?{worker}:{})});cleanups.push(()=>runtime.close());
  const sent=[];runtime.dots.deliver=async(source,message,{beforeSend})=>{beforeSend();sent.push(message);return {id:'synthetic-'+sent.length};};
  const adapter=new DiscordAdapter({config:runtime.config,store:runtime.store,pipeline:runtime.pipeline,dots:runtime.dots});adapter.verifiedInstallation=true;cleanups.push(()=>adapter.client.destroy());
  const client=new Client({name:'synthetic-project-task-owner',version:'1'}),transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:file},stderr:'pipe'});
  await client.connect(transport);cleanups.push(()=>client.close());
  const call=async(name,args)=>{const result=await client.callTool({name,arguments:args});assert.equal(result.isError,undefined,code(result));return result.structuredContent;};
  const original={provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:'project-request',actorId:actor,readers:[actor],revision:1,final:true,text:'既存TaskをこのProjectへ対応付けて',metadata:{kind:'text'}};
  const request=runtime.dots.enqueue(original),source=(await call('discord_read_request',{id:request.id,revision:1})).source;
  // An existing operator-owned Project and Task predate the Dots association.
  const project=await runtime.projects.handle({actor,operation:'create',request_id:'operator-create',name:'合成Project',source,brief});
  const taskSource={...original,sourceId:'existing-task',text:'UNEXPOSED_TASK_SOURCE'},key=runtime.store.ingest(taskSource).key;
  const task=runtime.store.createTask(runtime.store.source(key,actor),{title:'合成の担当仕事',request:'UNEXPOSED_TASK_REQUEST',action:'research',acceptance:['条件を調べる']});
  runtime.store.claim(task.id,task.revision);
  runtime.store.finish(task.id,task.revision,{state:'needs_review',summary:'UNEXPOSED_RESULT_SUMMARY',artifacts:[{path:'UNEXPOSED_ARTIFACT_PATH',sha256:'a'.repeat(64),bytes:12}],validations:[{exitCode:0}],verifiedExecution:true,independentReview:true});
  const association=(view,id,operation='link_task')=>({operation,project_id:view.project.project_id,expected_revision:view.project.revision,base_digest:view.project_digest,source,reason:'既存の担当仕事を対応付ける',request_id:id,task_id:task.id,...(operation==='link_task'?{expected_task_revision:task.revision}:{})});
  const prepare=async candidate=>call('project_prepare_change',{id:request.id,revision:request.revision,candidate});
  const confirm=async draft=>{let response;await adapter.interaction({isButton:()=>true,customId:'kotodama-project:'+draft.id+':'+draft.digest.slice(0,16),user:{id:actor},deferReply:async()=>{},editReply:async message=>{response=message;}});assert.match(response.content,/この内容の(Project保存|Task実行)を許可しました/);assert.equal((await call('project_read_change',{approval_id:draft.id})).state,'approved');};
  const commit=(candidate,draft)=>{const {operation,...payload}=candidate;return client.callTool({name:'project_'+operation,arguments:{...payload,approval_id:draft.id}});};
  const approved=async candidate=>{const draft=await prepare(candidate);await confirm(draft);return draft;};
  const commitSuccess=async(candidate,draft)=>{const result=await commit(candidate,draft);assert.equal(result.isError,undefined,code(result));return result.structuredContent;};
  const taskSnapshot=()=>JSON.stringify({rows:runtime.store.db.prepare('SELECT * FROM tasks ORDER BY id').all(),events:runtime.store.db.prepare('SELECT * FROM events WHERE task_id IS NOT NULL ORDER BY seq').all()});
  const projectSnapshot=()=>JSON.stringify({rows:runtime.store.db.prepare('SELECT * FROM projects ORDER BY id').all(),versions:runtime.store.db.prepare('SELECT * FROM project_versions ORDER BY project_id,revision').all(),requests:runtime.store.db.prepare('SELECT * FROM project_requests ORDER BY request_id').all(),events:runtime.store.db.prepare("SELECT * FROM events WHERE type LIKE 'project.%' ORDER BY seq").all()});
  return {config,file,save,runtime,client,request,source,project,task,taskSource,sent,call,association,prepare,confirm,commit,approved,commitSuccess,taskSnapshot,projectSnapshot};
}

test('Task-only grants expose strict approval-bound writes and read-only metadata tools',async t=>{
  const f=await fixture(t),catalog=(await f.client.listTools()).tools.filter(tool=>tool.name.startsWith('project_'));
  assert.deepEqual(catalog.map(tool=>tool.name),['project_read','project_link_task','project_unlink_task','project_read_task','project_prepare_change','project_read_change']);
  for(const name of ['project_link_task','project_unlink_task']){const tool=catalog.find(tool=>tool.name===name);assert.equal(tool.annotations.readOnlyHint,false);assert.equal(tool.annotations.destructiveHint,true);assert(tool.inputSchema.required.includes('approval_id'));}
  assert.equal(catalog.find(tool=>tool.name==='project_read_task').annotations.readOnlyHint,true);assert(!catalog.some(tool=>/approve/.test(tool.name)));
  const candidate=f.association(f.project,'link'),{operation,...payload}=candidate,before=f.projectSnapshot();
  assert.equal((await f.client.callTool({name:'project_link_task',arguments:payload})).isError,true);
  for(const extra of [{actor:'100000000000000009'},{surface:'operator'},{owner_ref:'ref/another-owner'},{context_digest:'c'.repeat(64)},{path:'elsewhere'},{expected_task_revision:0}]){
    assert.equal((await f.client.callTool({name:'project_prepare_change',arguments:{id:f.request.id,revision:1,candidate:{...candidate,...extra}}})).isError,true);
  }
  for(const operation of ['link_task','unlink_task']){
    const value=f.association(f.project,operation,operation);
    await assert.rejects(controlCommand(await loadConfig(f.file),{action:'project',surface:'dots',actor,...value}),/PROJECT_APPROVAL_REQUIRED/);
  }
  assert.equal(f.projectSnapshot(),before);assert.equal(f.runtime.store.db.prepare('SELECT count(*) AS n FROM dot_project_drafts').get().n,0);
});

test('stdio Task writes reject caller authority fields before forwarding an approved candidate',async t=>{
  const f=await fixture(t);let view=f.project;
  for(const operation of ['link_task','unlink_task']){
    const candidate=f.association(view,'authority-'+operation,operation),draft=await f.approved(candidate);
    const {operation:ignored,...payload}=candidate,before=f.projectSnapshot(),tasks=f.taskSnapshot();
    const forwarded=[],handle=f.runtime.projects.handle.bind(f.runtime.projects);
    f.runtime.projects.handle=(...args)=>{forwarded.push(args);return handle(...args);};
    try{
      for(const extra of [{surface:'operator'},{surface:null},{surface:''},{surface:['dots']},
        {actor:'100000000000000009'},{action:'request'},{operation:'read'}]){
        const result=await f.client.callTool({name:'project_'+operation,arguments:{...payload,approval_id:draft.id,...extra}});
        assert.equal(result.isError,true,JSON.stringify(extra));
        assert.equal(f.projectSnapshot(),before);assert.equal(f.taskSnapshot(),tasks);
      }
      assert.equal((await f.client.callTool({name:'project_'+operation,arguments:payload})).isError,true);
      assert.equal(forwarded.length,0,'invalid authority fields must not reach the Project owner');
      view=await f.commitSuccess(candidate,draft);assert.equal(forwarded.length,1);
      assert.equal(f.taskSnapshot(),tasks);
    }finally{f.runtime.projects.handle=handle;}
  }
  assert.deepEqual(view.project.task_refs,[]);
});

test('both control routes authenticate before parsing and preserve operator versus Dots Task grants',async t=>{
  const f=await fixture(t),{port}=JSON.parse(await readFile(path.join(f.config.dataDir,'runtime.json'),'utf8'));
  const token=await readFile(path.join(f.config.dataDir,'control.secret'),'utf8');
  assert(/^[a-f0-9]{64}$/.test(token),'synthetic control token must be 64 hex characters');
  const post=(route,body,authorization)=>controlPost(port,route,body,authorization);
  const denied=async(route,input,error,authorization='Bearer '+token,status=400)=>{
    const before=f.projectSnapshot(),tasks=f.taskSnapshot(),result=await post(route,input,authorization);
    assert.equal(result.status,status);assert.deepEqual(result.body,{ok:false,error});
    assert.equal(f.projectSnapshot(),before);assert.equal(f.taskSnapshot(),tasks);
  };
  let view=f.project;
  for(const route of ['/v1/project','/v1/command']){
    for(const operation of ['link_task','unlink_task']){
      const candidate=f.association(view,route.slice(4)+'-'+operation,operation),input={action:'project',actor,...candidate};
      for(const authorization of [undefined,'Bearer '+('0'.repeat(64))]){
        const before=f.projectSnapshot(),tasks=f.taskSnapshot();
        for(const body of [input,{...input,surface:'dots'},'{']){
          const result=await post(route,body,authorization);
          assert.equal(result.status,401);assert.deepEqual(result.body,{ok:false,error:'UNAUTHORIZED'});
        }
        assert.equal(f.projectSnapshot(),before);assert.equal(f.taskSnapshot(),tasks);
      }
      await denied(route,{...input,actor:'100000000000000009'},'OPERATOR_REQUIRED');
      for(const surface of [null,'','operator','DOTS',false,[],['dots'],{}])await denied(route,{...input,surface},'PROJECT_SURFACE_INVALID');
      await denied(route,{...input,surface:'dots'},'PROJECT_APPROVAL_REQUIRED');
      await denied(route,{...input,surface:'dots',approval_id:'project_'+('f'.repeat(24))},'PROJECT_APPROVAL_REQUIRED');
      // The broad local credential still needs the current installation grant.
      f.config.projects.operations=operations.filter(value=>value!==operation);await f.save();
      await denied(route,input,'PROJECT_OPERATION_NOT_ALLOWED');
      f.config.projects.operations=operations;await f.save();
      const tasks=f.taskSnapshot(),result=await post(route,input,'Bearer '+token);
      assert.equal(result.status,200);view=result.body.result;
      assert.equal(view.project.task_refs.length,operation==='link_task'?1:0);assert.equal(f.taskSnapshot(),tasks);
    }
  }
});

test('stdio confirms exact Task links, reports metadata and unlinks revoked Tasks without mutating them',async t=>{
  const f=await fixture(t),link=f.association(f.project,'link-1'),draft=await f.prepare(link),initial=f.projectSnapshot();let tasks=f.taskSnapshot();
  assert.equal(draft.projectWritePerformed,false);assert.deepEqual(JSON.parse(f.sent[0].files[0].attachment.toString('utf8')),{...link,actor});assert.match(f.sent[0].content,/Task関連付け/);
  assert.equal(code(await f.commit(link,draft)),'PROJECT_APPROVAL_REQUIRED');await f.confirm(draft);
  for(const change of [{task_id:'task-00000000-0000-4000-8000-000000000001'},{expected_task_revision:2},{request_id:'changed-key'}])assert.equal(code(await f.commit({...link,...change},draft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  const wrongOperation=f.association(f.project,'link-1','unlink_task');assert.equal(code(await f.commit(wrongOperation,draft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  assert.equal(code(await f.commit(link,{id:'project_'+('f'.repeat(24))})),'PROJECT_APPROVAL_REQUIRED');assert.equal(f.projectSnapshot(),initial);
  const linked=await f.commitSuccess(link,draft);assert.equal(linked.project.version,2);assert.equal(linked.project.revision,2);
  assert.deepEqual(linked.project.task_refs,[{adapter:'discord_local_task_v1',task_id:f.task.id,revision:1}]);assert.equal((await f.commitSuccess(link,draft)).replay,true);
  const args={project_id:linked.project.project_id,task_id:f.task.id},observed=await f.call('project_read_task',args);
  assert.equal(observed.resolution,'observed');assert.equal(observed.owner_state,'needs_review');assert.equal(observed.result_metadata.artifact_count,1);assert.equal(observed.result_metadata.checks,'reported_pass');
  assert.equal(observed.result_metadata.artifact_readback,'not_run');assert.equal(observed.completion,'not_observed');assert.equal(observed.execution_authorized,false);assert.equal(observed.task_state_changed,false);assert(!JSON.stringify(observed).includes('UNEXPOSED_'));assert.equal(f.taskSnapshot(),tasks);
  // A candidate approved before the existing Task owner advances its revision remains stale.
  const stale=f.association(linked,'stale-task'),staleDraft=await f.approved(stale);f.runtime.store.cancel(f.task.id,actor);tasks=f.taskSnapshot();const before=f.projectSnapshot();
  assert.equal(code(await f.commit(stale,staleDraft)),'PROJECT_TASK_REVISION_STALE');assert.equal(f.projectSnapshot(),before);
  const changed=await f.call('project_read_task',args);assert.equal(changed.resolution,'revision_changed');assert.equal(changed.owner_state,'cancelled');assert.equal(changed.result_metadata.availability,'unavailable');
  const refresh={...f.association(linked,'refresh-link'),expected_task_revision:2},refreshed=await f.commitSuccess(refresh,await f.approved(refresh));assert.equal(refreshed.project.task_refs[0].revision,2);assert.equal(f.taskSnapshot(),tasks);
  f.runtime.store.ingest({...f.taskSource,revision:2,withdrawn:true});tasks=f.taskSnapshot();
  const denied=await f.client.callTool({name:'project_read_task',arguments:args});assert.equal(code(denied),'SOURCE_ACCESS_DENIED');assert.equal(denied.structuredContent,undefined);
  assert.equal((await f.call('project_read',{project_id:args.project_id})).project.task_refs.length,1);
  const unlink=f.association(refreshed,'unlink-1','unlink_task'),unlinkDraft=await f.prepare(unlink);assert.match(f.sent.at(-1).content,/Task関連解除/);
  assert.equal(code(await f.commit(unlink,unlinkDraft)),'PROJECT_APPROVAL_REQUIRED');await f.confirm(unlinkDraft);
  assert.equal((await f.commit({...unlink,expected_task_revision:2},unlinkDraft)).isError,true);
  assert.equal(code(await f.commit({...unlink,task_id:'task-00000000-0000-4000-8000-000000000001'},unlinkDraft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  const unlinked=await f.commitSuccess(unlink,unlinkDraft);assert.deepEqual(unlinked.project.task_refs,[]);assert.equal(unlinked.project.revision,4);assert.equal((await f.commitSuccess(unlink,unlinkDraft)).replay,true);
  assert.equal(f.taskSnapshot(),tasks);assert.equal(code(await f.client.callTool({name:'project_read_task',arguments:args})),'PROJECT_TASK_NOT_LINKED');
  await f.runtime.dots.cancel(f.request.id,actor);assert.equal(code(await f.commit(unlink,unlinkDraft)),'DOTS_REQUEST_NOT_PENDING');assert.equal(f.taskSnapshot(),tasks);
});

test('Task association guards survive in-flight grant revocation and pending request cancellation',async t=>{
  for(const mode of ['link-grant','unlink-cancel','read-grant']){
    const f=await fixture(t);let view=f.project;
    if(mode!=='link-grant')view=await f.runtime.projects.handle({actor,...f.association(view,'operator-link')});
    const operation=mode==='unlink-cancel'?'unlink_task':'link_task',candidate=f.association(view,'pending-'+mode,operation);
    const draft=mode==='read-grant'?null:await f.approved(candidate),before=f.projectSnapshot(),tasks=f.taskSnapshot();
    f.runtime.projects.authorizeSource=async()=>{
      if(mode==='unlink-cancel')await f.runtime.dots.cancel(f.request.id,actor);
      else {f.config.dots.projectOperations=[];await f.save();}
    };
    const result=mode==='read-grant'?await f.client.callTool({name:'project_read_task',arguments:{project_id:view.project.project_id,task_id:f.task.id}}):await f.commit(candidate,draft);
    assert.equal(result.isError,true);assert.equal(result.structuredContent,undefined);assert.equal(code(result),mode==='unlink-cancel'?'DOTS_REQUEST_NOT_PENDING':'PROJECT_OPERATION_NOT_ALLOWED');
    assert.equal(f.projectSnapshot(),before);assert.equal(f.taskSnapshot(),tasks);
  }
});

test('read_task grant never grants preparation or write authority',async t=>{
  const f=await fixture(t,{dotsOperations:['read_task']}),linked=await f.runtime.projects.handle({actor,...f.association(f.project,'operator-link')});
  assert.deepEqual((await f.client.listTools()).tools.filter(tool=>tool.name.startsWith('project_')).map(tool=>tool.name),['project_read_task']);
  const before=f.projectSnapshot(),tasks=f.taskSnapshot();assert.equal((await f.call('project_read_task',{project_id:linked.project.project_id,task_id:f.task.id})).result_metadata.artifact_readback,'not_run');
  await assert.rejects(controlCommand(await loadConfig(f.file),{action:'project',surface:'dots',actor,operation:'prepare',id:f.request.id,revision:1,candidate:f.association(linked,'blocked')}),/PROJECT_OPERATION_NOT_ALLOWED/);
  for(const operation of ['link_task','unlink_task'])await assert.rejects(controlCommand(await loadConfig(f.file),{action:'project',surface:'dots',actor,...f.association(linked,'blocked-'+operation,operation)}),/PROJECT_OPERATION_NOT_ALLOWED/);
  assert.equal(f.projectSnapshot(),before);assert.equal(f.taskSnapshot(),tasks);
});


test('stdio execution and same-Task resume require exact requester approval and current grants',async t=>{
  let runs=0;
  const f=await fixture(t,{dotsOperations:['read','read_task','run_task','resume_task','read_result'],worker:{run:async()=>{runs++;return {state:'failed',summary:'synthetic failure',artifacts:[]};}}});
  const candidate={operation:'run_task',project_id:f.project.project.project_id,expected_revision:1,base_digest:f.project.project_digest,request_id:'execute',source:f.source,reason:'この仕事を実行',task:{title:'調査',request:'条件を調べる',action:'research',acceptance:['出典']}};
  const draft=await f.prepare(candidate);assert.match(f.sent.at(-1).content,/実行を開始/);assert.equal(runs,0);
  assert.equal(code(await f.commit(candidate,draft)),'PROJECT_APPROVAL_REQUIRED');
  await f.confirm(draft);
  assert.equal(code(await f.commit({...candidate,task:{...candidate.task,action:'develop'}},draft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  const run=await f.commitSuccess(candidate,draft);await f.runtime.pipeline.tail;assert.equal(runs,1);
  assert.equal((await f.commitSuccess(candidate,draft)).dispatch.state,'not_repeated');assert.equal(runs,1);
  const resume={operation:'resume_task',project_id:candidate.project_id,expected_revision:2,base_digest:run.project_digest,request_id:'resume',source:f.source,reason:'同じ仕事を再開',task_id:run.task_ref.task_id,expected_task_revision:1};
  const resumeDraft=await f.prepare(resume);assert.equal(code(await f.commit(resume,resumeDraft)),'PROJECT_APPROVAL_REQUIRED');await f.confirm(resumeDraft);
  const resumed=await f.commitSuccess(resume,resumeDraft);await f.runtime.pipeline.tail;
  assert.equal(resumed.task_ref.task_id,run.task_ref.task_id);assert.equal(resumed.task_ref.revision,2);assert.equal(runs,2);
  const next={...resume,request_id:'revoked',expected_revision:3,base_digest:resumed.project_digest,expected_task_revision:2},nextDraft=await f.approved(next);
  f.runtime.projects.authorizeSource=async()=>{f.config.dots.projectOperations=[];await f.save();};
  assert.equal(code(await f.commit(next,nextDraft)),'PROJECT_OPERATION_NOT_ALLOWED');assert.equal(runs,2);
});
