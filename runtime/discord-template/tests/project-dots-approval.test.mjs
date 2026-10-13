import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {exampleConfig,loadConfig} from '../src/config.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {createDotsServer} from '../dots-plugin/scripts/server.mjs';

const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const actor='100000000000000002',other='100000000000000009',channel='100000000000000003';
const operations=['read','create','inspect','correct'];
const brief={outcome:'原意を失わず保存する',in_scope:[],out_of_scope:[],constraints:['既存条件を守る'],acceptance:['条件を読める'],unknowns:[]};
const code=result=>result.content?.[0]?.text;

async function fixture(t,{dotsOperations=operations}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-project-approval-')),config=exampleConfig({workspace:root});
  config.dataDir=path.join(root,'data');config.projects={operations};config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600,...(dotsOperations===null?{}:{projectOperations:dotsOperations})};
  const file=path.join(root,'bot.json'),save=()=>writeFile(file,JSON.stringify(config),'utf8');await save();
  const runtime=await startRuntime(file,{offline:true,log:()=>{}}),clock={now:Date.now()},sent=[];runtime.dots.now=()=>clock.now;
  runtime.dots.deliver=async(source,message,{beforeSend})=>{beforeSend();sent.push({source,message});return {id:'synthetic-'+sent.length};};
  const adapter=new DiscordAdapter({config,store:runtime.store,pipeline:runtime.pipeline,dots:runtime.dots,policy:()=>runtime.dots.policy()});adapter.verifiedInstallation=true;
  const client=new Client({name:'synthetic-project-approval',version:'1'}),transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:file},stderr:'pipe'});
  await client.connect(transport);t.after(async()=>{await client.close();await adapter.client.destroy();await runtime.close();assert(path.basename(root).startsWith('ktdm-project-approval-'));await rm(root,{recursive:true,force:true});});
  const call=async(name,args)=>{const result=await client.callTool({name,arguments:args});assert.equal(result.isError,undefined,code(result));return result.structuredContent;};
  const source=id=>({provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:id,actorId:actor,readers:[actor],revision:1,final:true,text:'Projectを保存したい',metadata:{kind:'text'}});
  const request=async(id='request')=>{const original=source(id),receipt=runtime.dots.enqueue(original);const read=await call('discord_read_request',{id:receipt.id,revision:receipt.revision});return {original,receipt,candidate:{operation:'create',request_id:id,name:'合成のProject',source:read.source,brief}};};
  const prepare=async r=>call('project_prepare_change',{id:r.receipt.id,revision:r.receipt.revision,candidate:r.candidate});
  const confirm=async(draft,who=actor)=>{let response;await adapter.interaction({isButton:()=>true,customId:'kotodama-project:'+draft.id+':'+draft.digest.slice(0,16),user:{id:who},deferReply:async()=>{},editReply:async message=>{response=message;}});return response;};
  const commit=async(r,draft)=>{const {operation,...payload}=r.candidate;return client.callTool({name:operation==='create'?'project_create':'project_correct',arguments:{...payload,approval_id:draft.id}});};
  const count=()=>runtime.store.db.prepare('SELECT count(*) AS n FROM project_versions').get().n;
  return {root,file,config,save,runtime,client,adapter,clock,sent,source,request,prepare,confirm,commit,call,count};
}

test('installation Project grants do not grant Dots access and Dots grants cannot expand local grants',async t=>{
  const f=await fixture(t,{dotsOperations:null});assert.deepEqual((await loadConfig(f.file)).dots.projectOperations,[]);
  assert.equal((await f.client.listTools()).tools.length,7);
  await assert.rejects(controlCommand(await loadConfig(f.file),{action:'project',surface:'dots',actor,operation:'read',project_id:'ref/project/unknown'}),/PROJECT_OPERATION_NOT_ALLOWED/);
  f.config.dots.projectOperations=['read','read'];await f.save();await assert.rejects(loadConfig(f.file));
  f.config.dots.projectOperations=['execute'];await f.save();await assert.rejects(loadConfig(f.file));
  f.config.dots.projectOperations=['read'];f.config.projects.operations=[];await f.save();
  await assert.rejects(controlCommand(await loadConfig(f.file),{action:'project',surface:'dots',actor,operation:'read',project_id:'ref/project/unknown'}),/PROJECT_OPERATION_NOT_ALLOWED/);
});

test('only the authenticated requester button authorizes exact full Project content and one owner receipt',async t=>{
  const f=await fixture(t),r=await f.request();
  const many=Array.from({length:20},(_,i)=>String(i)+'🌸'.repeat(998));r.candidate.brief={outcome:'🌸'.repeat(4000),in_scope:many,out_of_scope:many,constraints:many,acceptance:many,unknowns:many};
  const draft=await f.prepare(r);assert.equal(draft.state,'needs_review');assert.equal(f.count(),0);assert.equal(f.sent.length,1);
  const shown=JSON.parse(f.sent[0].message.files[0].attachment.toString('utf8'));assert.deepEqual(shown,{...r.candidate,actor});assert(Buffer.byteLength(JSON.stringify(shown))>200000);
  assert.equal((await f.prepare(r)).id,draft.id);assert.equal(f.sent.length,1);
  assert.equal(code(await f.commit(r,draft)),'PROJECT_APPROVAL_REQUIRED');
  assert.match((await f.confirm(draft,other)).content,/PROJECT_APPROVAL_BINDING_CHANGED/);assert.equal(f.count(),0);
  assert.match((await f.confirm(draft)).content,/Project保存を許可/);
  assert.equal((await f.call('project_read_change',{approval_id:draft.id})).state,'approved');
  const changed={...r,candidate:{...r.candidate,request_id:'changed-key'}};assert.equal(code(await f.commit(changed,draft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  assert.equal(code(await f.commit({...r,candidate:{...r.candidate,name:'未確認の名前'}},draft)),'PROJECT_APPROVAL_BINDING_CHANGED');
  const results=await Promise.all([f.commit(r,draft),f.commit(r,draft)]);assert(results.every(result=>!result.isError));assert.equal(f.count(),1);
  assert(results.some(result=>result.structuredContent.replay));assert.equal(f.runtime.store.db.prepare('SELECT count(*) AS n FROM project_requests').get().n,1);
  assert.equal(f.runtime.store.tasks(actor).length,0);
  const tools=(await f.client.listTools()).tools;assert(!tools.some(tool=>/approve/.test(tool.name)));assert.equal(tools.find(tool=>tool.name==='project_correct').annotations.destructiveHint,true);
  await f.runtime.dots.cancel(r.receipt.id,actor);
  assert.equal(code(await f.commit(r,draft)),'DOTS_REQUEST_NOT_PENDING');assert.equal(f.count(),1);
  const projectId=results[0].structuredContent.project.project_id;assert.equal((await f.call('project_read',{project_id:projectId})).project.revision,1);
});

test('candidate input is bounded before insertion, Source must match the request, and drafts retire private content',async t=>{
  const f=await fixture(t),r=await f.request(),count=()=>f.runtime.store.db.prepare('SELECT count(*) AS n FROM dot_project_drafts').get().n;
  await assert.rejects(f.runtime.dots.prepareProject(r.receipt.id,1,{...r.candidate,actor}),/PROJECT_REQUEST_INVALID/);
  await assert.rejects(f.runtime.dots.prepareProject(r.receipt.id,1,{...r.candidate,brief:{...brief,outcome:'x'.repeat(4001)}}),/PROJECT_OUTCOME_INVALID/);
  await assert.rejects(f.runtime.dots.prepareProject(r.receipt.id,1,{...r.candidate,source:{...r.candidate.source,key:'f'.repeat(64)}}),/PROJECT_APPROVAL_BINDING_CHANGED/);assert.equal(count(),0);
  const first=await f.prepare(r);await f.confirm(first);
  r.candidate={...r.candidate,name:'変更した候補'};const second=await f.prepare(r);assert.equal(code(await f.commit({...r,candidate:{...r.candidate,name:'合成のProject'}},first)),'PROJECT_APPROVAL_REQUIRED');
  for(let n=2;n<8;n++){r.candidate={...r.candidate,name:'候補'+n};await f.prepare(r);}assert.equal(count(),8);
  r.candidate={...r.candidate,name:'制限を超えた候補'};const limited=await f.client.callTool({name:'project_prepare_change',arguments:{id:r.receipt.id,revision:1,candidate:r.candidate}});assert.equal(code(limited),'PROJECT_DRAFT_LIMIT');assert.equal(count(),8);
  f.clock.now+=8*86400000;f.runtime.dots.prune();
  const row=f.runtime.store.db.prepare('SELECT payload,digest,state FROM dot_project_drafts WHERE id=?').get(second.id);assert.equal(row.payload,'{}');assert.equal(row.digest,second.digest);assert.equal(row.state,'expired');assert.equal(f.count(),0);
});

test('cancelled requests, changed Sources and expired confirmations cannot approve or commit',async t=>{
  const f=await fixture(t);
  for(const mutation of ['cancel','source','expire']){
    const r=await f.request(mutation),draft=await f.prepare(r);await f.confirm(draft);
    if(mutation==='cancel')await f.runtime.dots.cancel(r.receipt.id,actor);
    else if(mutation==='source')f.runtime.store.ingest({...r.original,revision:2,text:'訂正した依頼'});
    else f.clock.now+=300001;
    const result=await f.commit(r,draft);assert.equal(result.isError,true);assert.equal(f.count(),0);
    if(mutation==='expire'){assert.equal(code(result),'PROJECT_APPROVAL_EXPIRED');assert.match((await f.confirm(draft)).content,/PROJECT_DRAFT_ALREADY_DECIDED/);}
    else {assert.match((await f.confirm(draft)).content,/DOTS_REQUEST_NOT_PENDING|DOTS_SOURCE_CHANGED/);await assert.rejects(f.runtime.dots.prepareProject(r.receipt.id,1,r.candidate),/DOTS_SOURCE_CHANGED/);}
  }
});

test('an unknown confirmation delivery can be reopened privately without approval or automatic resend',async t=>{
  const f=await fixture(t),r=await f.request();let attempts=0;
  f.runtime.dots.deliver=async()=>{attempts++;throw new Error('SYNTHETIC_UNKNOWN_DELIVERY');};
  const draft=await f.prepare(r);assert.equal(draft.reviewDelivery,'unknown');assert.equal((await f.prepare(r)).id,draft.id);assert.equal(attempts,1);
  let message,flags;f.adapter.member=async()=>{};
  await f.adapter.interaction({isButton:()=>false,isChatInputCommand:()=>true,commandName:'kotodama',guildId:f.config.discord.guildId,user:{id:actor},options:{getSubcommand:()=> 'project_review',getString:()=>draft.id},deferReply:async input=>{flags=input.flags;},editReply:async input=>{message=input;}});
  assert.equal(flags,64);assert.deepEqual(JSON.parse(message.files[0].attachment.toString('utf8')),{...r.candidate,actor});assert.equal(f.runtime.dots.projectDraft(draft.id).state,'needs_review');assert.equal(f.count(),0);assert.equal(attempts,1);
  await f.confirm(draft);assert.equal((await f.commit(r,draft)).isError,undefined);assert.equal(f.count(),1);
});

test('cancellation, expiry and both grant revocations during owner authorization prevent the SQLite commit',async t=>{
  for(const mutation of ['cancel','expire','dots-grant','local-grant']){
    const f=await fixture(t),r=await f.request(mutation),draft=await f.prepare(r);await f.confirm(draft);
    f.runtime.projects.authorizeSource=async()=>{
      if(mutation==='cancel')await f.runtime.dots.cancel(r.receipt.id,actor);
      else if(mutation==='expire')f.clock.now+=300001;
      else {if(mutation==='dots-grant')f.config.dots.projectOperations=[];else f.config.projects.operations=[];await f.save();}
    };
    const result=await f.commit(r,draft);assert.equal(result.isError,true);assert.equal(f.count(),0);assert.equal(f.runtime.store.db.prepare('SELECT count(*) AS n FROM project_requests').get().n,0);
  }
});

test('MCP cancellation reaches the invocation signal, outside the model-controlled envelope',async t=>{
  const f=await fixture(t),started=Promise.withResolvers(),aborted=Promise.withResolvers();
  const {server}=await createDotsServer({runtimeRoot,configFile:f.file,call:async(input,{signal})=>{assert(!Object.hasOwn(input,'signal'));assert(signal instanceof AbortSignal);started.resolve();await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));aborted.resolve();signal.throwIfAborted();}});
  const client=new Client({name:'synthetic-cancel',version:'1'}),[a,b]=InMemoryTransport.createLinkedPair();await server.connect(a);await client.connect(b);t.after(async()=>{await client.close();await server.close();});
  const controller=new AbortController(),work=client.callTool({name:'project_read',arguments:{project_id:'ref/project/unused'}},undefined,{signal:controller.signal});
  const refused=assert.rejects(work);await started.promise;controller.abort();await refused;await aborted.promise;
});

test('official stdio MCP cancellation reaches pending owner authorization without saving a Project',async t=>{
  const f=await fixture(t),r=await f.request('sdk-cancel'),draft=await f.prepare(r);
  assert.match((await f.confirm(draft)).content,/Project保存を許可/);
  const controller=new AbortController();let enter,release,observeAbort;
  const started=new Promise(resolve=>{enter=resolve;}),held=new Promise(resolve=>{release=resolve;}),aborted=new Promise(resolve=>{observeAbort=resolve;});
  f.runtime.projects.authorizeSource=async(_source,_actor,{signal})=>{
    signal.addEventListener('abort',()=>observeAbort(signal.reason),{once:true});enter();await held;
  };
  const {operation,...payload}=r.candidate;
  const call=f.client.callTool({name:'project_create',arguments:{...payload,approval_id:draft.id}},undefined,{signal:controller.signal});
  const rejected=assert.rejects(call,/SDK_CALL_CANCELLED/);
  try{
    await started;controller.abort(new Error('SDK_CALL_CANCELLED'));await rejected;
    // A timeout is not proof of cancellation propagation: require the server's
    // actual socket-disconnect reason before releasing the raw authorization.
    const reason=await aborted;assert.equal(reason.code,'HTTP_CLIENT_DISCONNECTED');
  }finally{release();}
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.count(),0);
  assert.equal(f.runtime.store.db.prepare('SELECT count(*) AS n FROM project_requests').get().n,0);
  assert.equal(f.runtime.store.db.prepare("SELECT count(*) AS n FROM events WHERE type='project.created'").get().n,0);
  assert.equal((await f.call('project_read_change',{approval_id:draft.id})).state,'approved');
  assert.equal(f.runtime.store.tasks(actor).length,0);
});
