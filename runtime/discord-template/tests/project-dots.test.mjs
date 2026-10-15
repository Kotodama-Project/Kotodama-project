import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {randomBytes} from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {exampleConfig} from '../src/config.mjs';
import {Store} from '../src/store.mjs';
import {DotsBridge} from '../src/dots.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {startRuntime} from '../src/runtime.mjs';
import {createDotsServer} from '../dots-plugin/scripts/server.mjs';

const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const actor='100000000000000002',channel='100000000000000003';
const operations=['read','create','inspect','correct'];
const source={key:'a'.repeat(64),revision:1};
const brief={outcome:'依頼の原意を保持する',in_scope:[],out_of_scope:[],constraints:['既存の条件を守る'],acceptance:['成果を確認する'],unknowns:[]};
const project_id='ref/project/synthetic';
const approval_id='project_'+('c'.repeat(24));
const change={project_id,expected_revision:1,base_digest:'b'.repeat(64),source,reason:'条件の訂正',brief};
const inputs={project_read:{project_id},project_create:{request_id:'create-1',name:'合成Project',source,brief,approval_id},project_inspect_change:change,project_correct:{...change,request_id:'correct-1',approval_id}};
const candidateFor=(operation,args)=>{const {approval_id,...payload}=args;return {operation,...payload};};

async function fixture(t,selected=operations){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-dots-')),config=exampleConfig({workspace:root});
  config.dataDir=path.join(root,'data');config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600,projectOperations:[...selected]};config.projects={operations:selected};
  const file=path.join(root,'bot.json'),save=()=>writeFile(file,JSON.stringify(config),'utf8');await save();
  const cleanups=[];t.after(async()=>{for(const cleanup of cleanups.reverse())await cleanup();assert(path.basename(root).startsWith('ktdm-project-dots-'));await rm(root,{recursive:true,force:true});});
  return {root,config,file,save,cleanups};
}
async function clientFor(t,f,call){
  const {server}=await createDotsServer({runtimeRoot,configFile:f.file,call});
  const client=new Client({name:'synthetic-project-client',version:'1'}),[a,b]=InMemoryTransport.createLinkedPair();
  await server.connect(a);await client.connect(b);f.cleanups.push(async()=>{await client.close();await server.close();});return client;
}
const errorCode=result=>result.content?.[0]?.text;
async function confirmedCandidate(runtime,client,request,candidate){
  const prepared=await client.callTool({name:'project_prepare_change',arguments:{id:request.id,revision:request.revision,candidate}});
  assert.equal(prepared.isError,undefined,errorCode(prepared));const draft=prepared.structuredContent;
  assert.equal(draft.state,'needs_review');assert.equal(draft.projectWritePerformed,false);
  // Feed a synthetic authenticated Discord button through the real handler.
  // MCP has no approval operation; this fixture does not call one indirectly.
  const adapter=new DiscordAdapter({config:runtime.config,store:runtime.store,pipeline:runtime.pipeline,dots:runtime.dots});adapter.verifiedInstallation=true;
  const replies=[];let deferred=false;
  try{await adapter.interaction({isButton:()=>true,customId:runtime.dots.projectReviewMessage(draft).components[0].components[0].custom_id,user:{id:actor},
    deferReply:async()=>{deferred=true;},editReply:async body=>{replies.push(body);}});}finally{await adapter.client.destroy();}
  assert.equal(deferred,true);assert.equal(replies.length,1);assert.match(replies[0].content,/Project保存を許可しました/);
  const read=await client.callTool({name:'project_read_change',arguments:{approval_id:draft.id}});
  assert.equal(read.isError,undefined,errorCode(read));assert.equal(read.structuredContent.state,'approved');return draft.id;
}

test('Project tools are opt-in per operation and preserve the existing seven tools',async t=>{
  const disabled=await fixture(t,[]),disabledClient=await clientFor(t,disabled,async()=>({}));
  assert.equal((await disabledClient.listTools()).tools.length,7);
  const operatorOnly=await fixture(t);delete operatorOnly.config.dots.projectOperations;await operatorOnly.save();
  assert.equal((await (await clientFor(t,operatorOnly,async()=>({}))).listTools()).tools.length,7);
  const limited=await fixture(t);limited.config.dots.projectOperations=['read','inspect'];await limited.save();const client=await clientFor(t,limited,async()=>({}));
  const catalog=(await client.listTools()).tools.filter(tool=>tool.name.startsWith('project_'));
  assert.deepEqual(catalog.map(tool=>tool.name),['project_read','project_inspect_change']);
  assert(catalog.every(tool=>tool.annotations.readOnlyHint===true));
});

test('Project tools send fixed action and configured actor with closed argument schemas',async t=>{
  const f=await fixture(t),received=[],client=await clientFor(t,f,async input=>{received.push(input);return {task_state_changed:false};});
  const catalog=(await client.listTools()).tools;assert.equal(catalog.length,13);
  for(const [index,[name,args]] of Object.entries(inputs).entries()){
    const result=await client.callTool({name,arguments:args});assert.equal(result.isError,undefined);
    assert.deepEqual(received[index],{operation:operations[index],...args,action:'project',surface:'dots',actor});
    assert.equal(catalog.find(tool=>tool.name===name).annotations.readOnlyHint,['read','inspect'].includes(operations[index]));
    assert.equal(catalog.find(tool=>tool.name===name).annotations.destructiveHint,operations[index]==='correct');
  }
  for(const extra of [{actor:'100000000000000009'},{path:'/tmp/not-an-input'},{url:'https://example.invalid'},{operation:'create'},{surface:'operator'}]){
    assert.equal((await client.callTool({name:'project_read',arguments:{project_id,...extra}})).isError,true);
  }
  assert.equal((await client.callTool({name:'project_create',arguments:{...inputs.project_create,source:{...source,path:'file'}}})).isError,true);
  for(const name of ['project_create','project_correct']){
    const {approval_id,...unapproved}=inputs[name];assert.equal((await client.callTool({name,arguments:unapproved})).isError,true);
  }
  assert.equal(received.length,4);
  const prepare={id:'dot_'+('d'.repeat(24)),revision:1,candidate:candidateFor('create',inputs.project_create)};
  assert.equal((await client.callTool({name:'project_prepare_change',arguments:prepare})).isError,undefined);
  assert.deepEqual(received[4],{operation:'prepare',...prepare,action:'project',surface:'dots',actor});
  assert.equal((await client.callTool({name:'project_read_change',arguments:{approval_id}})).isError,undefined);
  assert.deepEqual(received[5],{operation:'read_approval',approval_id,action:'project',surface:'dots',actor});
  assert.equal((await client.callTool({name:'project_prepare_change',arguments:{...prepare,candidate:{...prepare.candidate,actor}}})).isError,true);
  assert.equal(received.length,6);assert(!catalog.some(tool=>/approve/.test(tool.name)));
});

test('Project transport preserves Unicode and multiline text and refuses oversized or duplicate requirements',async t=>{
  const f=await fixture(t),received=[],client=await clientFor(t,f,async input=>{received.push(input);return {task_state_changed:false};});
  const valid={...inputs.project_create,name:'🌸'.repeat(200),brief:{...brief,outcome:'🌸'.repeat(4000),constraints:['条件\nと補足\tです']}};
  assert.equal((await client.callTool({name:'project_create',arguments:valid})).isError,undefined);assert.deepEqual(received[0].brief,valid.brief);
  for(const next of [{...valid,name:'🌸'.repeat(201)},{...valid,brief:{...brief,outcome:'🌸'.repeat(4001)}},
    {...valid,brief:{...brief,constraints:['条件','条件']}},{...valid,brief:{...brief,outcome:'\u0085'}},
    {...valid,brief:{...brief,outcome:'bad\0text'}},{...valid,brief:{...brief,outcome:'\ud800'}},
    {...valid,source:{...source,revision:Number.MAX_SAFE_INTEGER+1}},{...valid,request_id:'../path'}]){
    assert.equal((await client.callTool({name:'project_create',arguments:next})).isError,true);
  }
  assert.equal(received.length,1);
});

test('Project calls recheck current operation and installation scope before forwarding',async t=>{
  const f=await fixture(t),received=[],client=await clientFor(t,f,async input=>{received.push(input);return {task_state_changed:false};});
  await client.callTool({name:'project_read',arguments:inputs.project_read});
  f.config.projects.operations=[];await f.save();
  assert.equal(errorCode(await client.callTool({name:'project_read',arguments:inputs.project_read})),'PROJECT_OPERATION_NOT_ALLOWED');
  f.config.projects.operations=operations;f.config.dots.projectOperations=[];await f.save();
  assert.equal(errorCode(await client.callTool({name:'project_read',arguments:inputs.project_read})),'PROJECT_OPERATION_NOT_ALLOWED');
  f.config.dots.projectOperations=operations;f.config.installation='changed-installation';await f.save();
  assert.equal(errorCode(await client.callTool({name:'project_read',arguments:inputs.project_read})),'DOTS_PLUGIN_SCOPE_CHANGED');
  f.config.installation='my-kotodama';f.config.dots.enabled=false;await f.save();
  assert.equal(errorCode(await client.callTool({name:'project_read',arguments:inputs.project_read})),'DOTS_PLUGIN_SCOPE_CHANGED');
  assert.equal(received.length,1);
});

test('Discord source bindings are returned only for the exact accessible current request',async t=>{
  const f=await fixture(t),store=new Store(f.config.dataDir);f.cleanups.push(()=>store.close());
  const bridge=new DotsBridge({config:f.config,store,authorize:async()=>{},deliver:async()=>({id:'synthetic'})});
  const original={provider:'discord',guildId:f.config.discord.guildId,channelId:channel,sourceId:'synthetic-message',actorId:actor,readers:[actor],revision:1,final:true,text:'Projectを作成して',metadata:{kind:'text'}};
  const request=bridge.enqueue(original),bound=store.db.prepare('SELECT source_key FROM dot_requests WHERE id=?').get(request.id).source_key;
  const expected={key:bound,revision:1};assert.deepEqual((await bridge.list()).requests[0].source,expected);
  assert.deepEqual((await bridge.read(request.id,1)).source,expected);
  store.ingest({...original,revision:2,text:'訂正'});
  await assert.rejects(bridge.read(request.id,1),/DOTS_SOURCE_CHANGED/);assert.deepEqual((await bridge.list()).requests,[]);
  const second=bridge.enqueue({...original,sourceId:'withdrawn-message'});
  store.ingest({...original,sourceId:'withdrawn-message',revision:2,withdrawn:true});
  await assert.rejects(bridge.read(second.id,1),/SOURCE_ACCESS_DENIED/);assert.deepEqual((await bridge.list()).requests,[]);
});

test('packaged stdio Project tools use the owner-bound loopback and preserve exact retry keys',async t=>{
  const f=await fixture(t),received=[],token=randomBytes(32).toString('hex');await mkdir(f.config.dataDir,{recursive:true});
  const identity={ownerId:'synthetic-owner',pid:process.pid,startedAt:'2030-01-01T00:00:00Z'};
  const server=createServer(async(req,res)=>{
    assert.equal(req.headers.authorization,'Bearer '+token);res.setHeader('content-type','application/json');
    if(req.method==='GET'&&req.url==='/v1/status'){res.end(JSON.stringify(identity));return;}
    assert.equal(req.method,'POST');assert.equal(req.url,'/v1/project');const chunks=[];for await(const chunk of req)chunks.push(chunk);
    const input=JSON.parse(Buffer.concat(chunks));received.push(input);
    const value=input.expected_revision===2?{ok:false,error:'PROJECT_REVISION_STALE'}:{ok:true,result:{received:input,task_state_changed:false}};
    res.end(JSON.stringify(value));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));f.cleanups.push(()=>new Promise(resolve=>server.close(resolve)));
  await writeFile(path.join(f.config.dataDir,'control.secret'),token);await writeFile(path.join(f.config.dataDir,'runtime.json'),JSON.stringify({...identity,port:server.address().port}));
  const client=new Client({name:'synthetic-project-stdio',version:'1'}),transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:f.file},stderr:'pipe'});
  await client.connect(transport);f.cleanups.push(()=>client.close());
  for(const [index,[name,args]] of Object.entries(inputs).entries()){
    const result=await client.callTool({name,arguments:args});assert.equal(result.isError,undefined);assert.deepEqual(result.structuredContent.received,{operation:operations[index],...args,action:'project',surface:'dots',actor});
  }
  await client.callTool({name:'project_create',arguments:inputs.project_create});assert.deepEqual(received[4],received[1]);
  const stale=await client.callTool({name:'project_correct',arguments:{...inputs.project_correct,expected_revision:2}});assert.equal(stale.isError,true);assert.equal(errorCode(stale),'PROJECT_REVISION_STALE');
  f.config.projects.operations=[];await f.save();
  assert.equal(errorCode(await client.callTool({name:'project_read',arguments:inputs.project_read})),'PROJECT_OPERATION_NOT_ALLOWED');assert.equal(received.length,6);
});

test('packaged stdio creates and corrects one Project through the real owner without executing a Task',async t=>{
  const f=await fixture(t),projectChannel='100000000000000005';f.config.discord.textChannelIds.push(projectChannel);await f.save();
  const runtime=await startRuntime(f.file,{offline:true,log:()=>{}});f.cleanups.push(()=>runtime.close());
  const original={provider:'discord',guildId:f.config.discord.guildId,channelId:channel,sourceId:'project-request',actorId:actor,readers:[actor],revision:1,final:true,text:'依頼をProjectとして保存して',metadata:{kind:'text'}};
  const request=runtime.dots.enqueue(original);
  const client=new Client({name:'synthetic-project-owner',version:'1'}),transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:f.file},stderr:'pipe'});
  await client.connect(transport);f.cleanups.push(()=>client.close());
  const call=async(name,args)=>{const result=await client.callTool({name,arguments:args});assert.equal(result.isError,undefined,errorCode(result));return result.structuredContent;};
  const readSource=await call('discord_read_request',{id:request.id,revision:1});
  const create={...inputs.project_create,source:readSource.source};
  create.approval_id=await confirmedCandidate(runtime,client,request,candidateFor('create',create));
  const created=await call('project_create',create),id=created.project.project_id;
  assert.equal(created.project.revision,1);assert.deepEqual(created.project.brief,brief);assert.equal(created.task_state_changed,false);
  const replay=await call('project_create',create);assert.equal(replay.project.project_id,id);assert.equal(replay.replay,true);
  const initial=await call('project_read',{project_id:id});assert.equal(initial.project_digest,created.project_digest);
  const correction=runtime.dots.enqueue({...original,sourceId:'project-correction',text:'費用条件を追加して'});
  const correctionSource=await call('discord_read_request',{id:correction.id,revision:1});
  const proposal={...change,project_id:id,base_digest:initial.project_digest,source:correctionSource.source,brief:{...brief,constraints:[...brief.constraints,'追加費用は使わない']}};
  const inspected=await call('project_inspect_change',proposal);assert.equal(inspected.applied,false);assert.deepEqual(inspected.changed_fields,['constraints']);
  const correct={...proposal,request_id:'correct-1'};
  correct.approval_id=await confirmedCandidate(runtime,client,correction,candidateFor('correct',correct));
  const corrected=await call('project_correct',correct);assert.equal(corrected.project.revision,2);
  const final=await call('project_read',{project_id:id});assert.equal(final.project_digest,corrected.project_digest);assert.deepEqual(final.project.brief.constraints,proposal.brief.constraints);
  assert.equal((await call('project_correct',correct)).replay,true);
  const staleCandidate={...proposal,request_id:'stale-new-id'};
  staleCandidate.approval_id=await confirmedCandidate(runtime,client,correction,candidateFor('correct',staleCandidate));
  const stale=await client.callTool({name:'project_correct',arguments:staleCandidate});assert.equal(stale.isError,true);assert.equal(errorCode(stale),'PROJECT_REVISION_STALE');
  assert.equal(runtime.store.tasks(actor).length,0);assert.equal(runtime.store.db.prepare('SELECT count(*) AS n FROM project_versions').get().n,2);
  // The explicit read grant covers operator-created Projects outside the inbox;
  // write approval remains bound to a pending request from the Dot inbox.
  const outsideInbox={...original,channelId:projectChannel,sourceId:'operator-selected-project-source'};
  assert.throws(()=>runtime.dots.enqueue(outsideInbox),/DOTS_ACTOR_REQUIRED/);
  const outsideSource=runtime.store.ingest(outsideInbox);
  const outsideCreate={request_id:'outside-inbox',name:'別channelのProject',source:{key:outsideSource.key,revision:1},brief};
  const refused=await client.callTool({name:'project_prepare_change',arguments:{id:request.id,revision:1,candidate:{operation:'create',...outsideCreate}}});
  assert.equal(refused.isError,true);assert.equal(errorCode(refused),'PROJECT_APPROVAL_BINDING_CHANGED');
  const outsideProject=await runtime.projects.handle({actor,operation:'create',...outsideCreate});
  assert.equal((await call('project_read',{project_id:outsideProject.project.project_id})).project_digest,outsideProject.project_digest);
  runtime.store.ingest({...original,revision:2,withdrawn:true});
  const revoked=await client.callTool({name:'project_read',arguments:{project_id:id}});assert.equal(revoked.isError,true);assert.equal(errorCode(revoked),'SOURCE_ACCESS_DENIED');
});

test('in-flight Dots disable and actor replacement prevent Project commit and read emission',async t=>{
  for(const revoke of ['disabled','actor'])for(const operation of ['create','read']){
    const f=await fixture(t),other='100000000000000009';f.config.discord.operators.push(other);await f.save();
    const runtime=await startRuntime(f.file,{offline:true,log:()=>{}});f.cleanups.push(()=>runtime.close());
    const original={provider:'discord',guildId:f.config.discord.guildId,channelId:channel,sourceId:'in-flight-request',actorId:actor,readers:[actor],revision:1,final:true,text:'明示的なProject作成依頼',metadata:{kind:'text'}};
    const request=runtime.dots.enqueue(original),selected=runtime.store.ingest(original),create={...inputs.project_create,source:{key:selected.key,revision:1}};
    const client=await clientFor(t,f);
    create.approval_id=await confirmedCandidate(runtime,client,request,candidateFor('create',create));
    let project;
    if(operation==='read'){
      const created=await client.callTool({name:'project_create',arguments:create});assert.equal(created.isError,undefined,errorCode(created));project=created.structuredContent.project;
    }
    runtime.projects.authorizeSource=async()=>{
      if(revoke==='disabled')f.config.dots.enabled=false;else f.config.dots.actorId=other;
      await f.save();
    };
    const result=await client.callTool({name:operation==='read'?'project_read':'project_create',arguments:operation==='read'?{project_id:project.project_id}:create});
    assert.equal(result.isError,true);assert.match(errorCode(result),/^DOTS_[A-Z_]+$/);assert.equal(result.structuredContent,undefined);
    assert.equal(runtime.store.db.prepare('SELECT count(*) AS n FROM projects').get().n,operation==='read'?1:0);
    assert.equal(runtime.store.tasks(actor).length,0);
  }
});
