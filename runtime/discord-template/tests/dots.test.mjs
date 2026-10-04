import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {Store} from '../src/store.mjs';
import {exampleConfig,loadConfig} from '../src/config.mjs';
import {DotsBridge,eventPreview} from '../src/dots.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {startRuntime} from '../src/runtime.mjs';
import {createDotsServer} from '../dots-plugin/scripts/server.mjs';

const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const actor='100000000000000002',other='100000000000000004',channel='100000000000000003';
async function fixture(t,{delivery,authorize,bridgeOptions={}}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-dots-')),config=exampleConfig();config.dataDir=root;config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600};
  const store=new Store(root),sent=[],clock={now:Date.parse('2030-01-01T00:00:00Z')};
  const bridge=new DotsBridge({config,store,authorize:authorize??(async()=>{}),deliver:delivery??(async(source,body)=>{sent.push({source,body});return {id:'message-'+sent.length};}),now:()=>clock.now,...bridgeOptions});
  t.after(async()=>{store.close();assert(path.basename(root).startsWith('ktdm-dots-'));await rm(root,{recursive:true,force:true});});
  const source={provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:'message-source',actorId:actor,readers:[actor],revision:1,final:true,text:'イベントの相談をしたい',metadata:{kind:'text'}};
  const event={name:'合成イベント',description_md:'試験用の説明',start_at:'2030-01-02T09:00:00+09:00',end_at:'2030-01-02T10:00:00+09:00',timezone:'Asia/Tokyo',location:'合成テスト会場',location_visibility:'guests-only',visibility:'private',max_capacity:30,require_approval:true};
  return {root,config,store,bridge,sent,clock,source,event};
}

test('Dot inbox binds the owner and Source without creating a Task',async t=>{
  const f=await fixture(t);assert.throws(()=>f.bridge.enqueue({...f.source,actorId:other}),/DOTS_ACTOR_REQUIRED/);assert.throws(()=>f.bridge.enqueue({...f.source,channelId:'100000000000000005'}),/DOTS_ACTOR_REQUIRED/);
  const req=f.bridge.enqueue(f.source);const duplicate=f.bridge.enqueue(f.source);assert.equal(duplicate.id,req.id);assert.equal(duplicate.created,false);assert.equal(req.created,true);assert.equal((await f.bridge.list()).requests[0].text,f.source.text);assert.equal(f.store.tasks(actor).length,0);
});
test('Dot replies are once-only and edited or withdrawn Sources stop delivery',async t=>{
  const f=await fixture(t),req=f.bridge.enqueue(f.source);assert.equal((await f.bridge.send(req.id,1,'返答です')).state,'sent');assert.equal((await f.bridge.send(req.id,1,'返答です')).state,'already_sent');assert.equal(f.sent.length,1);assert.deepEqual(f.sent[0].body.allowedMentions,{parse:[]});
  await assert.rejects(f.bridge.send(req.id,1,'別の返答'),/DOTS_REPLY_CHANGED/);
  const next=f.bridge.enqueue({...f.source,sourceId:'source-2'});f.store.ingest({...f.source,sourceId:'source-2',revision:2,text:'訂正しました'});await assert.rejects(f.bridge.send(next.id,1,'古い返答'),/DOTS_SOURCE_CHANGED/);assert.equal(f.sent.length,1);
  const deleted=f.bridge.enqueue({...f.source,sourceId:'source-3'});f.store.ingest({...f.source,sourceId:'source-3',revision:2,withdrawn:true});await assert.rejects(f.bridge.send(deleted.id,1,'削除後の返答'),/SOURCE_ACCESS_DENIED/);
});
test('unconfirmed Discord sends cannot replay after retries or restart',async t=>{
  let calls=0;const f=await fixture(t,{delivery:async()=>{calls++;throw new Error('SYNTHETIC_UNCERTAIN_SEND');}}),req=f.bridge.enqueue(f.source);
  assert.equal((await f.bridge.send(req.id,1,'返答')).state,'unknown');await assert.rejects(f.bridge.send(req.id,1,'返答'),/DOTS_DELIVERY_UNCERTAIN/);assert.equal(calls,1);
  f.store.db.prepare("UPDATE dot_requests SET state='sending' WHERE id=?").run(req.id);new DotsBridge({config:f.config,store:f.store,deliver:async()=>{calls++;},now:()=>f.clock.now});assert.equal(f.store.db.prepare('SELECT state FROM dot_requests WHERE id=?').get(req.id).state,'unknown');
});
test('transient access failure keeps an inbox request, revocation and expiry stop it',async t=>{
  let failure='ACCESS_UNAVAILABLE';const f=await fixture(t,{authorize:async()=>{if(failure)throw new Error(failure);}}),req=f.bridge.enqueue(f.source);
  assert.equal((await f.bridge.list()).requests.length,0);assert.equal(f.store.db.prepare('SELECT state FROM dot_requests WHERE id=?').get(req.id).state,'pending');failure=null;assert.equal((await f.bridge.list()).requests.length,1);
  f.clock.now+=3600001;assert.equal((await f.bridge.list()).requests.length,0);await assert.rejects(f.bridge.send(req.id,1,'返答'),/DOTS_REQUEST_EXPIRED/);
});
test('Luma review includes the full candidate and requires the bound human, fresh exact approval and a single claim',async t=>{
  const f=await fixture(t),req=f.bridge.enqueue(f.source),event={...f.event,description_md:'説明'.repeat(5000)};
  const draft=await f.bridge.prepareEvent(req.id,1,event);assert.equal(draft.state,'needs_review');assert.equal(f.sent.length,1);assert(eventPreview(draft).length<=2000);assert(f.sent[0].body.files[0].attachment.toString('utf8').includes(event.description_md));assert.deepEqual(JSON.parse(f.sent[0].body.files[1].attachment.toString('utf8')),{operation:'create',targetUrl:null,event});
  await f.bridge.prepareEvent(req.id,1,event);assert.equal(f.sent.length,1);await assert.rejects(f.bridge.claimEvent(draft.id),/LUMA_APPROVAL_REQUIRED/);await assert.rejects(f.bridge.approve(draft.id,draft.digest.slice(0,16),other),/LUMA_APPROVAL_BINDING_CHANGED/);
  await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);const claim=await f.bridge.claimEvent(draft.id);assert.equal(claim.action,'create_event_once');await assert.rejects(f.bridge.claimEvent(draft.id),/LUMA_APPROVAL_REQUIRED/);
  await assert.rejects(f.bridge.recordEvent(draft.id,claim.claimId,'https://example.invalid/event',event),/LUMA_EVENT_URL_INVALID/);await assert.rejects(f.bridge.recordEvent(draft.id,claim.claimId,'https://luma.com/synthetic-event',{...event,max_capacity:31}),/LUMA_READBACK_CHANGED/);
  const reported=await f.bridge.recordEvent(draft.id,claim.claimId,'https://luma.com/synthetic-event',event);assert.equal(reported.evidence,'DOT_REPORTED_NOT_INDEPENDENTLY_VERIFIED');assert.deepEqual(await f.bridge.recordEvent(draft.id,claim.claimId,reported.url,event),reported);assert.equal(f.store.tasks(actor).length,0);
});
test('Luma candidate changes supersede old approvals and expired approval cannot start a browser write',async t=>{
  const f=await fixture(t),req=f.bridge.enqueue(f.source),first=await f.bridge.prepareEvent(req.id,1,f.event);await f.bridge.approve(first.id,first.digest.slice(0,16),actor);
  const second=await f.bridge.prepareEvent(req.id,1,{...f.event,name:'訂正したイベント'});await assert.rejects(f.bridge.claimEvent(first.id),/LUMA_APPROVAL_REQUIRED/);await f.bridge.approve(second.id,second.digest.slice(0,16),actor);f.clock.now+=300001;await assert.rejects(f.bridge.claimEvent(second.id),/LUMA_APPROVAL_EXPIRED/);
});
test('Luma interrupted browser operations remain uncertain and are not started again',async t=>{
  const f=await fixture(t),req=f.bridge.enqueue(f.source),draft=await f.bridge.prepareEvent(req.id,1,f.event);await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);const claim=await f.bridge.claimEvent(draft.id);
  new DotsBridge({config:f.config,store:f.store,now:()=>f.clock.now});assert.equal(f.bridge.draft(draft.id).state,'uncertain');await assert.rejects(f.bridge.claimEvent(draft.id),/LUMA_APPROVAL_REQUIRED/);assert.equal((await f.bridge.recordEvent(draft.id,claim.claimId,'https://luma.com/synthetic-event',f.event)).state,'reported');
});
test('Luma update approval binds the target URL and a cancelled request cannot start it',async t=>{
  const f=await fixture(t),req=f.bridge.enqueue(f.source);await assert.rejects(f.bridge.prepareEvent(req.id,1,f.event,{operation:'update'}),/LUMA_TARGET_REQUIRED/);
  const draft=await f.bridge.prepareEvent(req.id,1,f.event,{operation:'update',targetUrl:'https://luma.com/synthetic-target'});await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);const claim=await f.bridge.claimEvent(draft.id);assert.equal(claim.action,'update_event_once');
  await assert.rejects(f.bridge.recordEvent(draft.id,claim.claimId,'https://luma.com/other-target',f.event),/LUMA_TARGET_CHANGED/);
  const next=f.bridge.enqueue({...f.source,sourceId:'cancellable'});await f.bridge.cancel(next.id,actor);await assert.rejects(f.bridge.send(next.id,1,'返答'),/DOTS_DELIVERY_UNCERTAIN/);
});
test('Dot channel routing skips the analyzer and corrections do not enqueue another request',async t=>{
  const f=await fixture(t);let analyzed=0;const adapter=new DiscordAdapter({config:f.config,store:f.store,dots:f.bridge,pipeline:{ingest:async()=>{analyzed++;}}});adapter.verifiedInstallation=true;adapter.client.user={id:'100000000000000009'};adapter.source=async()=>f.source;const replies=[];
  const message={guildId:f.config.discord.guildId,channelId:channel,author:{id:actor},mentions:{users:new Map([[adapter.client.user.id,{}]])},reply:async body=>{replies.push(body);return {id:'ack'};}};
  await adapter.message(message);await adapter.message(message);assert.equal(analyzed,0);assert.equal(replies.length,1);adapter.source=async()=>({...f.source,revision:2,text:'訂正'});await adapter.message(message,{edited:true});assert.equal(replies.length,1);assert.equal((await f.bridge.list()).requests.length,0);await adapter.client.destroy();
});
test('SDK client sees seven scoped tools and no programmatic approval tool',async t=>{
  const f=await fixture(t),configFile=path.join(f.root,'bot.json');await writeFile(configFile,JSON.stringify(f.config),'utf8');let invoked;
  const {server}=await createDotsServer({runtimeRoot,configFile,call:async input=>{invoked=input;return {requests:[],taskOwnerUnchanged:true};}});const client=new Client({name:'synthetic-test',version:'1'});const [a,b]=InMemoryTransport.createLinkedPair();await server.connect(a);await client.connect(b);t.after(async()=>{await client.close();await server.close();});
  const catalog=await client.listTools();assert.equal(catalog.tools.length,7);assert(!catalog.tools.some(tool=>/approve/.test(tool.name)));const result=await client.callTool({name:'discord_requests',arguments:{}});assert.equal(result.structuredContent.taskOwnerUnchanged,true);assert.equal(invoked.operation,'list');
  const page=await client.callTool({name:'discord_read_request',arguments:{id:'dot_'+('a'.repeat(24)),revision:1,offset:128,limit:256}});assert.equal(page.isError,undefined);assert.equal(invoked.operation,'read_request');assert.equal(invoked.offset,128);
  const invalid=await client.callTool({name:'discord_reply',arguments:{id:'dot_invalid',revision:1,text:'x'}});assert.equal(invalid.isError,true);
});
test('packaged stdio server negotiates with the official SDK without leaking setup details',async t=>{
  const f=await fixture(t),configFile=path.join(f.root,'bot.json');await writeFile(configFile,JSON.stringify(f.config),'utf8');const client=new Client({name:'synthetic-test',version:'1'});
  const transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:configFile},stderr:'pipe'});await client.connect(transport);t.after(()=>client.close());assert.equal((await client.listTools()).tools.length,7);
  const result=await client.callTool({name:'discord_requests',arguments:{}});assert.equal(result.isError,true);assert(!JSON.stringify(result).includes(f.root));
});
test('packaged plugin reads the actual loopback runtime and respects a revoked configuration',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-dots-runtime-'));let runtime,client;
  t.after(async()=>{await client?.close();await runtime?.close();assert(path.basename(root).startsWith('ktdm-dots-runtime-'));await rm(root,{recursive:true,force:true});});
  const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600};const file=path.join(root,'bot.json');await writeFile(file,JSON.stringify(config),'utf8');
  runtime=await startRuntime(file,{offline:true,log:()=>{}});const request=runtime.dots.enqueue({provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:'runtime-source',actorId:actor,readers:[actor],revision:1,final:true,text:'合成の相談',metadata:{kind:'text'}});
  client=new Client({name:'synthetic-runtime-client',version:'1'});const transport=new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:file},stderr:'pipe'});await client.connect(transport);
  const result=await client.callTool({name:'discord_requests',arguments:{actor:other}});assert.equal(result.structuredContent.requests[0].id,request.id);assert.equal(runtime.store.tasks(actor).length,0);
  const malformed=await client.callTool({name:'discord_requests',arguments:{cursor:'not_json'}});assert.equal(malformed.isError,true);assert.equal(malformed.content[0].text,'DOTS_CURSOR_INVALID');
  config.dots.enabled=false;await writeFile(file,JSON.stringify(config),'utf8');const revoked=await client.callTool({name:'discord_requests',arguments:{}});assert.equal(revoked.isError,true);assert.equal(revoked.content[0].text,'DOTS_PLUGIN_SCOPE_CHANGED');
});
test('enabled Dot configuration rejects missing owner and an unbound channel',async t=>{
  const f=await fixture(t),configFile=path.join(f.root,'bot.json');f.config.dots.actorId=other;await writeFile(configFile,JSON.stringify(f.config),'utf8');await assert.rejects(loadConfig(configFile),/DOTS_ACTOR_REQUIRED/);
  f.config.dots.actorId=actor;f.config.dots.channelIds=['100000000000000005'];await writeFile(configFile,JSON.stringify(f.config),'utf8');await assert.rejects(loadConfig(configFile),/DOTS_CHANNEL_REQUIRED/);
});
test('changes during asynchronous authorization prevent reply and event claims',async t=>{
  let mutate=false,f;
  f=await fixture(t,{authorize:async source=>{if(mutate){mutate=false;f.store.ingest({...source,revision:source.revision+1,text:'処理中の訂正'});}}});
  const reply=f.bridge.enqueue(f.source);mutate=true;await assert.rejects(f.bridge.send(reply.id,1,'古い返答'),/DOTS_SOURCE_CHANGED/);assert.equal(f.sent.length,0);
  const request=f.bridge.enqueue({...f.source,sourceId:'claim-source'}),draft=await f.bridge.prepareEvent(request.id,1,f.event);await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);mutate=true;await assert.rejects(f.bridge.claimEvent(draft.id),/DOTS_SOURCE_CHANGED/);
});
test('the final send guard rejects a Source changed during Discord fetches',async t=>{
  let sent=0,f;f=await fixture(t,{delivery:async(source,_body,options)=>{f.store.ingest({...source,revision:source.revision+1,text:'送信直前の訂正'});options?.beforeSend?.();sent++;return {id:'should-not-send'};}});
  const request=f.bridge.enqueue(f.source);assert.equal((await f.bridge.send(request.id,1,'古い返答')).state,'unknown');assert.equal(sent,0);
});
test('unavailable inbox rows are distinguishable from an empty inbox',async t=>{
  const f=await fixture(t,{authorize:async()=>{throw new Error('ACCESS_UNAVAILABLE');}});f.bridge.enqueue(f.source);const result=await f.bridge.list();assert.equal(result.complete,false);assert.equal(result.unavailable,1);assert.equal(result.requests.length,0);
});
test('transport draft details expire while Source and content-free receipts remain',async t=>{
  const f=await fixture(t),request=f.bridge.enqueue(f.source),draft=await f.bridge.prepareEvent(request.id,1,f.event);f.clock.now+=8*86400000;f.bridge.prune();
  const row=f.store.db.prepare('SELECT * FROM dot_event_drafts WHERE id=?').get(draft.id);assert.equal(row.event,'{}');assert.equal(row.target_url,null);assert.equal(row.digest,draft.digest);assert.equal(f.store.sourceInternal(f.store.db.prepare('SELECT source_key FROM dot_requests WHERE id=?').get(request.id).source_key).text,f.source.text);
});
test('a human can refresh an expired unused approval, while a claimed operation cannot refresh',async t=>{
  const f=await fixture(t),request=f.bridge.enqueue(f.source),draft=await f.bridge.prepareEvent(request.id,1,f.event);await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);f.clock.now+=300001;await assert.rejects(f.bridge.claimEvent(draft.id),/LUMA_APPROVAL_EXPIRED/);
  await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);assert.equal((await f.bridge.claimEvent(draft.id)).state,'executing');await assert.rejects(f.bridge.approve(draft.id,draft.digest.slice(0,16),actor),/LUMA_DRAFT_ALREADY_DECIDED/);
});
test('startup retirement preserves compatibility with an existing NOT NULL draft table',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-dots-old-schema-')),store=new Store(root);t.after(async()=>{store.close();assert(path.basename(root).startsWith('ktdm-dots-old-schema-'));await rm(root,{recursive:true,force:true});});
  store.db.exec("CREATE TABLE dot_event_drafts(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,revision INTEGER NOT NULL,event TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,operation TEXT NOT NULL,target_url TEXT,approved_at INTEGER,claim_id TEXT,review_message_id TEXT,reported TEXT)");
  const config=exampleConfig();config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600};let now=0;const bridge=new DotsBridge({config,store,now:()=>now,deliver:async()=>({id:'preview'})});const request=bridge.enqueue({provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:'old-schema',actorId:actor,readers:[actor],revision:1,final:true,text:'old draft',metadata:{kind:'text'}});
  store.db.prepare("INSERT INTO dot_event_drafts(id,request_id,revision,event,digest,state,operation) VALUES(?,?,1,?,?,?,'create')").run('legacy-draft',request.id,'{"description_md":"old synthetic draft"}','synthetic-digest','needs_review');now=8*86400000;
  assert.doesNotThrow(()=>new DotsBridge({config,store,now:()=>now}));const row=store.db.prepare('SELECT * FROM dot_event_drafts WHERE id=?').get('legacy-draft');assert.equal(row.state,'expired');assert.equal(row.event,'{}');
});
test('an already claimed browser operation can reconcile after inbox expiry without granting another action',async t=>{
  const f=await fixture(t),request=f.bridge.enqueue(f.source),draft=await f.bridge.prepareEvent(request.id,1,f.event);f.clock.now+=3599000;await f.bridge.approve(draft.id,draft.digest.slice(0,16),actor);const claim=await f.bridge.claimEvent(draft.id);f.clock.now+=2000;
  const result=await f.bridge.recordEvent(draft.id,claim.claimId,'https://luma.com/synthetic-late',f.event);assert.equal(result.state,'reported');assert.equal(result.evidence,'DOT_REPORTED_NOT_INDEPENDENTLY_VERIFIED');await assert.rejects(f.bridge.claimEvent(draft.id),/DOTS_REQUEST_EXPIRED/);await assert.rejects(f.bridge.send(request.id,1,'期限後の新しい返答'),/DOTS_REQUEST_EXPIRED/);
  f.store.ingest({...f.source,revision:2,withdrawn:true});await assert.rejects(f.bridge.recordEvent(draft.id,claim.claimId,result.url,f.event),/SOURCE_ACCESS_DENIED/);
});
test('a remote owner outage cannot leave a deleted Dot Source locally readable',async t=>{
  const f=await fixture(t),request=f.bridge.enqueue(f.source);f.config.owner={kind:'remote',url:'https://example.invalid',tokenEnv:'FIXTURE_REMOTE_OWNER'};const adapter=new DiscordAdapter({config:f.config,store:f.store,dots:f.bridge,pipeline:{ingest:async()=>{throw new Error('SYNTHETIC_REMOTE_OUTAGE');}}});adapter.verifiedInstallation=true;
  await assert.rejects(adapter.withdraw({guildId:f.source.guildId,channelId:channel,id:f.source.sourceId}),/SYNTHETIC_REMOTE_OUTAGE/);await assert.rejects(f.bridge.send(request.id,1,'削除後の返答'),/SOURCE_ACCESS_DENIED/);await adapter.client.destroy();
});
test('the requester can reopen an undelivered review privately without changing its candidate',async t=>{
  const f=await fixture(t,{delivery:async()=>{throw new Error('SYNTHETIC_REVIEW_NOT_DELIVERED');}}),request=f.bridge.enqueue(f.source),draft=await f.bridge.prepareEvent(request.id,1,f.event);assert.equal(draft.reviewDelivery,'unknown');
  const replies=[],adapter=new DiscordAdapter({config:f.config,store:f.store,dots:f.bridge,pipeline:{}});adapter.verifiedInstallation=true;adapter.member=async()=>({});
  const i={isButton:()=>false,isChatInputCommand:()=>true,commandName:'kotodama',guildId:f.config.discord.guildId,channelId:channel,user:{id:actor},options:{getSubcommand:()=> 'luma_review',getString:()=>draft.id},deferReply:async()=>{},editReply:async body=>{replies.push(body);return {id:'private-review'};}};
  await adapter.interaction(i);assert.equal(replies[0].files.length,2);assert.equal(replies[0].components[0].components[0].custom_id,'kotodama-luma:'+draft.id+':'+draft.digest.slice(0,16));assert.equal(f.bridge.draft(draft.id).digest,draft.digest);
  await assert.rejects(f.bridge.send(request.id,1,'確認待ちのための終了返答'),/LUMA_OPERATION_PENDING/);i.options.getString=()=>null;await adapter.interaction(i);assert.equal(replies[1].files.length,2);
  i.user={id:other};f.config.discord.operators.push(other);await adapter.interaction(i);assert(!replies[2].files);assert.match(replies[2].content,/DOTS_ACTOR_REQUIRED/);await adapter.client.destroy();
});

test('inbox cursors reach later pending requests and use a finite horizon for new arrivals',async t=>{
  const f=await fixture(t),expected=[];for(let n=0;n<32;n++)expected.push(f.bridge.enqueue({...f.source,sourceId:'page-'+n}).id);
  let page=await f.bridge.list(),found=page.requests.map(r=>r.id);assert.equal(page.complete,false);assert.equal(page.uninspected,22);
  const late=f.bridge.enqueue({...f.source,sourceId:'later-arrival'});await f.bridge.cancel(expected[12],actor);
  while(page.nextCursor){page=await f.bridge.list({cursor:page.nextCursor});found.push(...page.requests.map(r=>r.id));}
  assert.equal(page.complete,true);assert.deepEqual(found,expected.filter((_,n)=>n!==12));assert(!found.includes(late.id));assert.equal(new Set(found).size,found.length);
  page=await f.bridge.list();found=page.requests.map(r=>r.id);while(page.nextCursor){page=await f.bridge.list({cursor:page.nextCursor});found.push(...page.requests.map(r=>r.id));}assert(found.includes(late.id));
});
test('unavailable older requests do not block cursor progress and remain retryable',async t=>{
  let blocked=true;const f=await fixture(t,{authorize:async source=>{if(blocked&&source.sourceId.startsWith('blocked-'))throw new Error('ACCESS_UNAVAILABLE');}});
  for(let n=0;n<20;n++)f.bridge.enqueue({...f.source,sourceId:'blocked-'+n});const later=f.bridge.enqueue({...f.source,sourceId:'available'});
  const first=await f.bridge.list();assert.equal(first.requests.length,0);assert.equal(first.unavailable,20);assert(first.nextCursor);
  const second=await f.bridge.list({cursor:first.nextCursor});assert.equal(second.requests[0].id,later.id);assert.equal(second.nextCursor,null);assert.equal(second.complete,false);assert.equal(second.unavailable,20);
  blocked=false;assert.equal((await f.bridge.list()).requests.length,10);assert.equal(f.store.db.prepare("SELECT count(*) AS n FROM dot_requests WHERE state='pending'").get().n,21);
});
test('cursor input is bounded and tied to the current owner and channel scope',async t=>{
  const f=await fixture(t);for(let n=0;n<11;n++)f.bridge.enqueue({...f.source,sourceId:'scope-'+n});const first=await f.bridge.list();
  await assert.rejects(f.bridge.list({cursor:'x'.repeat(321)}),/DOTS_CURSOR_INVALID/);await assert.rejects(f.bridge.list({cursor:'not_json'}),/DOTS_CURSOR_INVALID/);
  f.config.dots.channelIds.push('100000000000000005');await assert.rejects(f.bridge.list({cursor:first.nextCursor}),/DOTS_CURSOR_INVALID/);
  await assert.rejects(f.bridge.list({limit:11}),/DOTS_LIST_INVALID/);await assert.rejects(f.bridge.list({includeText:'false'}),/DOTS_LIST_INVALID/);
});
test('retained receipt history does not require an inbox table scan',async t=>{
  const f=await fixture(t),insert=f.store.db.prepare("INSERT INTO dot_requests(id,source_key,source_revision,actor,state,created) VALUES(?,? ,1,?,'sent',0)");
  f.store.transaction(()=>{for(let n=0;n<10000;n++)insert.run('retained-'+n,'retained-source',actor);});const req=f.bridge.enqueue(f.source);assert.equal((await f.bridge.list()).requests[0].id,req.id);
  const plan=f.store.db.prepare("EXPLAIN QUERY PLAN SELECT id,rowid AS ordinal FROM dot_requests WHERE actor=? AND state='pending' AND rowid>? AND rowid<=? ORDER BY rowid LIMIT 20").all(actor,0,20000).map(r=>r.detail).join(' ');assert.match(plan,/dot_requests_inbox/);assert(!/USE TEMP B-TREE/.test(plan));
  const admission=f.store.db.prepare("EXPLAIN QUERY PLAN SELECT count(*) AS n FROM dot_requests WHERE state='pending'").all().map(r=>r.detail).join(' ');assert.match(admission,/SEARCH.*dot_requests_inbox/);
});
test('compact discovery and bounded Unicode text pages preserve the complete request',async t=>{
  const f=await fixture(t),text='a'.repeat(127)+'🧑‍💻'+('条件。العربية e\u0301 🛰️\n'.repeat(750)),req=f.bridge.enqueue({...f.source,text});
  const listed=(await f.bridge.list({includeText:false})).requests[0];assert(!Object.hasOwn(listed,'text'));assert.equal(listed.textLength,text.length);assert.equal((await f.bridge.list()).requests[0].text,text);
  let offset=0,reconstructed='',pages=0;do{const part=await f.bridge.read(req.id,1,{offset,limit:128});assert.equal(part.textDigest,listed.textDigest);assert.equal(part.offsetEncoding,'utf-16');assert(!/^[\uDC00-\uDFFF]|[\uD800-\uDBFF]$/.test(part.text));reconstructed+=part.text;offset=part.nextOffset;pages++;}while(offset!==null);
  assert.equal(reconstructed,text);assert(pages>100);await assert.rejects(f.bridge.read(req.id,1,{offset:128}),/DOTS_TEXT_OFFSET_INVALID/);await assert.rejects(f.bridge.read(req.id,1,{offset:text.length+1}),/DOTS_TEXT_OFFSET_INVALID/);await assert.rejects(f.bridge.read(req.id,1,{limit:4097}),/DOTS_TEXT_RANGE_INVALID/);
});
test('a correction, cancellation or access loss stops subsequent request pages',async t=>{
  let denied=false;const f=await fixture(t,{authorize:async()=>{if(denied)throw new Error('SOURCE_ACCESS_DENIED');}}),req=f.bridge.enqueue({...f.source,text:'長い条件'.repeat(3000)});
  await f.bridge.read(req.id,1);f.store.ingest({...f.source,revision:2,text:'訂正'});await assert.rejects(f.bridge.read(req.id,1,{offset:4096}),/DOTS_SOURCE_CHANGED/);
  const next=f.bridge.enqueue({...f.source,sourceId:'cancelled-page'});await f.bridge.cancel(next.id,actor);await assert.rejects(f.bridge.read(next.id,1),/DOTS_REQUEST_NOT_PENDING/);
  const revoked=f.bridge.enqueue({...f.source,sourceId:'revoked-page'});denied=true;await assert.rejects(f.bridge.read(revoked.id,1),/SOURCE_ACCESS_DENIED/);
});
test('later authorization cannot emit an earlier request after it changed',async t=>{
  let f,mutate=false;f=await fixture(t,{authorize:async source=>{if(mutate&&source.sourceId==='second'){mutate=false;f.store.ingest({...f.source,revision:2,text:'後から訂正'});}}});
  f.bridge.enqueue(f.source);const second=f.bridge.enqueue({...f.source,sourceId:'second'});mutate=true;const result=await f.bridge.list();assert.deepEqual(result.requests.map(r=>r.id),[second.id]);assert.equal(result.complete,true);
});
test('authorization timeouts retain raw admission and coalesce retries until settlement',async t=>{
  const pending=[];let calls=0;const f=await fixture(t,{authorize:()=>{calls++;return new Promise(resolve=>pending.push(resolve));},bridgeOptions:{authorizationLimit:2,authorizationTimeoutMs:15}});
  const first=f.bridge.enqueue(f.source),second=f.bridge.enqueue({...f.source,sourceId:'raw-second'}),third=f.bridge.enqueue({...f.source,sourceId:'raw-third'});
  await assert.rejects(f.bridge.read(first.id,1),/DOTS_ACCESS_TIMEOUT/);await assert.rejects(f.bridge.read(first.id,1),/DOTS_ACCESS_TIMEOUT/);assert.equal(calls,1);
  await assert.rejects(f.bridge.read(second.id,1),/DOTS_ACCESS_TIMEOUT/);assert.equal(calls,2);assert.equal(f.bridge.authorizations.size,2);
  await assert.rejects(f.bridge.read(third.id,1),/DOTS_ACCESS_BUSY/);assert.equal(calls,2);
  pending.splice(0).forEach(resolve=>resolve());await new Promise(resolve=>setImmediate(resolve));assert.equal(f.bridge.authorizations.size,0);
  const fresh=f.bridge.read(third.id,1);await new Promise(resolve=>setImmediate(resolve));pending.splice(0).forEach(resolve=>resolve());assert.equal((await fresh).id,third.id);assert.equal(calls,3);
});
test('coalesced authorizations recheck current Source scope after the raw read settles',async t=>{
  let resolve,calls=0;const gate=new Promise(done=>{resolve=done;}),f=await fixture(t,{authorize:()=>{calls++;return gate;}}),req=f.bridge.enqueue(f.source);
  const first=f.bridge.read(req.id,1),second=f.bridge.read(req.id,1);f.config.dots.channelIds=[];resolve();await assert.rejects(first,/DOTS_SOURCE_SCOPE_CHANGED/);await assert.rejects(second,/DOTS_SOURCE_SCOPE_CHANGED/);assert.equal(calls,1);assert.equal(f.bridge.authorizations.size,0);
});
test('a slow inbox page stops at its wall budget and preserves the remaining cursor',async t=>{
  let release;const gate=new Promise(resolve=>{release=resolve;}),f=await fixture(t,{authorize:()=>gate,bridgeOptions:{authorizationTimeoutMs:30,listDeadlineMs:45}});
  for(let n=0;n<20;n++)f.bridge.enqueue({...f.source,sourceId:'slow-'+n});const started=performance.now(),page=await f.bridge.list();assert.equal(page.requests.length,0);assert(page.nextCursor);assert(page.uninspected>=10);assert.equal(page.unavailable+page.uninspected,20);assert.equal(page.complete,false);assert(f.bridge.authorizations.size<=f.bridge.authorizationLimit);assert(performance.now()-started<1000);
  release();await new Promise(resolve=>setImmediate(resolve));const next=await f.bridge.list({cursor:page.nextCursor});assert.equal(next.requests.length,10);assert.equal(next.unavailable,page.unavailable);assert.equal(f.store.db.prepare("SELECT count(*) AS n FROM dot_requests WHERE state='pending'").get().n,20);
});
