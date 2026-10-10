import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {Store} from '../src/store.mjs';
import {DotsBridge} from '../src/dots.mjs';
import {JudgmentStatusReader,configuredToolApproval,formatJudgmentStatus} from '../src/judgment-status.mjs';
import {atomicJson} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {runCommand} from '../src/command.mjs';

const actor='100000000000000002',other='100000000000000004',channel='100000000000000003';
const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const event={name:'PRIVATE_EVENT_SENTINEL',description_md:'PRIVATE_DESCRIPTION_SENTINEL',start_at:'2030-01-02T09:00:00+09:00',end_at:'2030-01-02T10:00:00+09:00',timezone:'Asia/Tokyo',location:'PRIVATE_LOCATION_SENTINEL',location_visibility:'guests-only',visibility:'private',max_capacity:30,require_approval:true};

async function fixture(t,options={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-judgment-')),config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');
  config.discord.operators.push(other);config.dots={...config.dots,enabled:true,actorId:actor,channelIds:[channel]};
  const f={root,config,current:structuredClone(config),store:new Store(config.dataDir),now:Date.parse('2030-01-01T00:00:00Z')};
  f.dots=new DotsBridge({config,store:f.store,policy:()=>f.current,now:()=>f.now,authorize:options.dotsAuthorize??(async()=>{}),deliver:async()=>({id:'synthetic-review'})});
  f.reader=new JudgmentStatusReader({config,store:f.store,owner:options.owner??f.store,dots:()=>f.dots,readPolicy:async()=>f.current,now:()=>f.now,
    authorize:options.authorize??(async()=>{}),...options.reader});
  f.source=(id='one',who=actor)=>({provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:id,actorId:who,readers:[who],revision:1,final:true,text:'PRIVATE_SOURCE_SENTINEL',metadata:{kind:'text'}});
  f.task=(id='one',who=actor,result=null)=>{const source=f.source(id,who),{key}=f.store.ingest(source),task=f.store.createTask(f.store.source(key,who),{title:'PRIVATE_TITLE_SENTINEL',request:'PRIVATE_REQUEST_SENTINEL',action:'research',acceptance:['PRIVATE_ACCEPTANCE_SENTINEL']});
    if(result){f.store.claim(task.id,task.revision);f.store.finish(task.id,task.revision,result);}return f.store.taskInternal(task.id);};
  f.draft=async id=>{const request=f.dots.enqueue(f.source(id));return f.dots.prepareEvent(request.id,1,event);};
  t.after(async()=>{await f.runtime?.close();f.store.close();assert(path.basename(root).startsWith('ktdm-judgment-'));await rm(root,{recursive:true,force:true});});
  return f;
}

test('configured Codex tool approval is separate from business decisions and never prints arguments',()=>{
  for(const args of [['-a','never'],['--ask-for-approval=never'],['-c','approval_policy="never"'],['--config=approval_policy="never"']])assert.equal(configuredToolApproval({args}),'never');
  assert.equal(configuredToolApproval({args:['-c','approval_policy="PRIVATE_VALUE_SENTINEL"']}),'unknown');
  assert.equal(configuredToolApproval({args:['--model','private-model']}),'unspecified');
});

test('read-only task projection separates result review, independent review and human decision and withholds content',async t=>{
  const f=await fixture(t);f.current.worker.args=['-a','never','PRIVATE_ARGUMENT_SENTINEL'];f.config.worker.args=[...f.current.worker.args];
  const task=f.task('one',actor,{state:'needs_review',summary:'PRIVATE_RESULT_SENTINEL',artifacts:[{path:f.root}],verifiedExecution:true,independentReview:false,validations:[{exitCode:0}]});
  const changes=f.store.db.prepare('SELECT total_changes() AS n').get().n,report=await f.reader.read({actor,taskId:task.id});
  assert.equal(f.store.db.prepare('SELECT total_changes() AS n').get().n,changes);
  assert.equal(report.tasks.items[0].review,'RESULT_REVIEW_PENDING');assert.equal(report.tasks.items[0].humanDecisionRequired,'unknown');
  assert.equal(report.tasks.items[0].technical.independentReview,'unobserved');assert.equal(report.tasks.items[0].technical.checks,'reported_pass');
  assert.equal(report.humanDecision.receipt,'unobserved');assert.equal(report.codexToolApproval.configured.worker,'never');assert.equal(report.codexToolApproval.observed,'unknown');
  assert.equal(report.effective.executionAuthorized,false);assert.equal(report.mutationsEnabled,false);
  assert(!JSON.stringify(report).includes('PRIVATE_'));assert(!JSON.stringify(report).includes(f.root));assert.match(formatJudgmentStatus(report),/会社のHuman Decision: 未観測/);
  f.store.db.prepare('UPDATE tasks SET result=? WHERE id=?').run(JSON.stringify({...task.result,independentReview:true}),task.id);
  assert.equal((await f.reader.read({actor,taskId:task.id})).tasks.items[0].technical.independentReview,'reported_pass');
});

test('foreign actor, revoked operator, source access and source corrections cannot manufacture authorization',async t=>{
  const f=await fixture(t),foreign=f.task('foreign',other),own=f.task();
  const denied=await f.reader.read({actor,taskId:foreign.id});assert.equal(denied.tasks.items.length,0);assert.equal(denied.tasks.unavailable,1);assert(!JSON.stringify(denied).includes(foreign.id));
  f.store.ingest({...f.source(),revision:2,text:'PRIVATE_CORRECTION_SENTINEL'});
  const stale=await f.reader.read({actor,taskId:own.id});assert.equal(stale.tasks.items[0].sourceBinding,'mismatched');assert.equal(stale.tasks.items[0].executionEligibility,'blocked');assert.equal(stale.tasks.items[0].technical.execution,'invalidated');
  f.store.ingest({...f.source(),revision:3,readers:[other]});assert.equal((await f.reader.read({actor,taskId:own.id})).tasks.items.length,0);
  f.current.discord.operators=[other];await assert.rejects(f.reader.read({actor}),/OPERATOR_REQUIRED/);
});

test('grant removal, startup configuration drift and authority expiry report blocked eligibility',async t=>{
  const f=await fixture(t);f.current.worker.actions=[];
  let report=await f.reader.read({actor});assert.equal(report.effective.actions.find(a=>a.action==='research').eligibility,'blocked');
  f.current=structuredClone(f.config);f.current.worker.actions.push('develop');report=await f.reader.read({actor});assert(report.effective.actions.find(a=>a.action==='develop').reasons.includes('WORKER_RESTART_REQUIRED'));
  f.current.worker.workspace=path.join(f.root,'different');report=await f.reader.read({actor});assert(report.effective.configurationDrift.includes('workspace'));assert.equal(report.tasks.state,'unobserved');
  f.current=structuredClone(f.config);const settings={authorityExpiresAt:'2029-01-01T00:00:00Z'};f.config.worker.companyPack=settings;f.current.worker.companyPack=settings;f.config.worker.actions.push('create_company_pack');f.current.worker.actions.push('create_company_pack');
  report=await f.reader.read({actor});assert(report.effective.actions.find(a=>a.action==='create_company_pack').reasons.includes('COMPANY_PACK_AUTHORITY_EXPIRED'));
});

test('Company Pack grant and fresh authority remain blocked without startup verification isolation',async t=>{
  const f=await fixture(t);f.config.worker.actions.push('create_company_pack');
  f.config.worker.companyPack={authorityExpiresAt:'2030-01-02T00:00:00Z'};f.current=structuredClone(f.config);
  assert.deepEqual(f.config.worker.verify,[]);assert.equal(f.config.worker.verification,undefined);
  const report=await f.reader.read({actor}),action=report.effective.actions.find(a=>a.action==='create_company_pack');
  assert.equal(action.configured,true);assert.equal(action.runningWorkerConfigured,true);assert.equal(action.eligibility,'blocked');
  assert(action.reasons.includes('VERIFICATION_ISOLATION_REQUIRED'));assert(!action.reasons.includes('COMPANY_PACK_AUTHORITY_EXPIRED'));
});

test('Company Pack built-in verification does not require custom worker.verify commands',async t=>{
  const f=await fixture(t);f.config.worker.actions.push('create_company_pack');
  f.config.worker.companyPack={authorityExpiresAt:'2030-01-02T00:00:00Z'};
  f.config.worker.verification={kind:'docker',image:'sha256:'+'a'.repeat(64)};f.current=structuredClone(f.config);
  assert.deepEqual(f.config.worker.verify,[]);
  const report=await f.reader.read({actor}),action=report.effective.actions.find(a=>a.action==='create_company_pack');
  assert(!action.reasons.includes('VERIFICATION_ISOLATION_REQUIRED'));assert(!action.reasons.includes('WRITE_VERIFICATION_REQUIRED'));
  assert.equal(action.eligibility,process.platform==='linux'?'scope_check_required':'blocked');
  assert.equal(report.effective.technicalPreflight,'not_run');assert.equal(report.effective.executionAuthorized,false);
});

test('remote owner is unobserved and never reads the local task mirror or invokes the remote owner',async t=>{
  const f=await fixture(t);f.task();f.config.owner={kind:'remote'};f.current.owner={kind:'remote'};f.reader.owner={tasks:()=>{assert.fail('remote call');}};
  const report=await f.reader.read({actor});assert.equal(report.tasks.reason,'REMOTE_OWNER_UNOBSERVED');assert.deepEqual(report.tasks.items,[]);assert(report.effective.actions.every(a=>a.eligibility==='blocked'));
});

test('Luma missing, valid, expired and changed receipts are derived from the existing candidate and retain privacy',async t=>{
  const f=await fixture(t),draft=await f.draft('event');let report=await f.reader.read({actor}),item=report.luma.items[0];
  assert.equal(item.approvalReceipt,'missing');assert.equal(item.pendingDecision,'HUMAN_DECISION_REQUIRED');
  await f.dots.approve(draft.id,draft.digest.slice(0,16),actor);report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'valid');assert.equal(report.luma.items[0].pendingDecision,'none');
  f.now+=300001;report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'expired');assert.equal(report.luma.items[0].pendingDecision,'HUMAN_DECISION_REQUIRED');
  f.store.db.prepare('UPDATE dot_event_drafts SET event=? WHERE id=?').run(JSON.stringify({...event,max_capacity:31}),draft.id);report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'mismatched');assert.equal(report.luma.items[0].pendingDecision,'CANDIDATE_RECONCILIATION_REQUIRED');
  assert(!JSON.stringify(report).includes('PRIVATE_'));assert(!JSON.stringify(report).includes(f.root));
});

test('Luma current actor/source access and source revision remain separate from approval receipts',async t=>{
  const f=await fixture(t),draft=await f.draft('event');await f.dots.approve(draft.id,draft.digest.slice(0,16),actor);
  assert.equal((await f.reader.read({actor:other})).luma.items.length,0);
  f.store.ingest({...f.source('event'),revision:2,text:'PRIVATE_CORRECTION_SENTINEL'});let report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'mismatched');
  f.store.ingest({...f.source('event'),revision:3,readers:[other]});report=await f.reader.read({actor});assert.equal(report.luma.items.length,0);assert.equal(report.luma.unavailable,1);
  f.current.dots.enabled=false;assert.equal((await f.reader.read({actor})).luma.reason,'DOTS_DISABLED');
});

test('cancelled or expired Luma requests and future approval clocks require reconciliation',async t=>{
  const f=await fixture(t),draft=await f.draft('event');await f.dots.approve(draft.id,draft.digest.slice(0,16),actor);
  f.store.db.prepare("UPDATE dot_requests SET state='cancelled' WHERE id=?").run(draft.requestId);
  let report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'mismatched');assert.equal(report.luma.items[0].pendingDecision,'CANDIDATE_RECONCILIATION_REQUIRED');
  f.store.db.prepare("UPDATE dot_requests SET state='pending' WHERE id=?").run(draft.requestId);f.store.db.prepare('UPDATE dot_event_drafts SET approved_at=? WHERE id=?').run(f.now+1,draft.id);
  assert.equal((await f.reader.read({actor})).luma.items[0].approvalReceipt,'mismatched');
  f.store.db.prepare('UPDATE dot_event_drafts SET approved_at=? WHERE id=?').run(f.now,draft.id);f.now+=3600001;
  report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'expired');assert.equal(report.luma.items[0].pendingDecision,'CANDIDATE_RECONCILIATION_REQUIRED');
});

test('a denied provider read withholds task and draft IDs and details',async t=>{
  const f=await fixture(t),task=f.task(),draft=await f.draft('event');
  f.reader.authorize=async()=>{throw new Error('SOURCE_ACCESS_DENIED');};f.dots.authorize=async()=>{throw new Error('SOURCE_ACCESS_DENIED');};
  const report=await f.reader.read({actor});assert.equal(report.tasks.unavailable,1);assert.equal(report.luma.unavailable,1);
  assert.deepEqual(report.tasks.items,[]);assert.deepEqual(report.luma.items,[]);assert(!JSON.stringify(report).includes(task.id));assert(!JSON.stringify(report).includes(draft.id));
});

test('Luma request cancellation during a later read prevents a stale valid receipt from escaping',async t=>{
  const f=await fixture(t),one=await f.draft('one'),two=await f.draft('two');await f.dots.approve(two.id,two.digest.slice(0,16),actor);
  let calls=0;f.dots.authorize=async()=>{if(++calls===2)f.store.db.prepare("UPDATE dot_requests SET state='cancelled' WHERE id=?").run(two.requestId);};
  await assert.rejects(f.reader.read({actor}),/JUDGMENT_INPUT_CHANGED/);assert(one.id);
});

test('consumed Luma approval is never a fresh execution grant and provider readback stays unverified',async t=>{
  const f=await fixture(t),draft=await f.draft('event');await f.dots.approve(draft.id,draft.digest.slice(0,16),actor);const claim=await f.dots.claimEvent(draft.id);
  await f.dots.recordEvent(draft.id,claim.claimId,'https://luma.com/synthetic-event',event);f.now+=300001;
  const report=await f.reader.read({actor});assert.equal(report.luma.items[0].approvalReceipt,'consumed');assert.equal(report.luma.items[0].executionAuthorized,false);assert.equal(report.luma.items[0].readback,'reported_not_independently_verified');
  assert.equal(report.claims.providerVerified,false);
});

test('enumeration is actor scoped and capped without claiming a complete inbox',async t=>{
  const f=await fixture(t);for(let i=0;i<22;i++)f.task('task-'+i);f.task('foreign',other);
  for(let i=0;i<22;i++)await f.draft('event-'+i);
  const report=await f.reader.read({actor});assert.equal(report.tasks.items.length,20);assert.equal(report.tasks.truncated,true);assert.equal(report.luma.items.length,20);assert.equal(report.luma.truncated,true);
});

test('policy or input drift during another authorization prevents a partial stale report',async t=>{
  const f=await fixture(t);const one=f.task('one'),two=f.task('two');let calls=0;
  f.reader.authorize=async()=>{if(++calls===2)f.store.db.prepare("UPDATE tasks SET state='cancelled' WHERE id=?").run(two.id);};
  await assert.rejects(f.reader.read({actor}),/JUDGMENT_INPUT_CHANGED/);
  f.reader.authorize=async()=>{f.current.worker.actions=[];};await assert.rejects(f.reader.read({actor,taskId:one.id}),/JUDGMENT_POLICY_CHANGED/);
});

test('a Discord permission invalidation during authorization prevents the whole report',async t=>{
  const f=await fixture(t);f.task();let epoch=0;f.reader.accessEpoch=()=>epoch;f.reader.authorize=async()=>{epoch++;};
  await assert.rejects(f.reader.read({actor}),/JUDGMENT_ACCESS_CHANGED/);
});

test('a timed-out authorization retains its slot, prevents retries and has a bounded drain',async t=>{
  const f=await fixture(t,{reader:{timeoutMs:20}});f.task();let release;
  f.reader.authorize=()=>new Promise(resolve=>{release=resolve;});
  await assert.rejects(f.reader.read({actor}),/JUDGMENT_READ_TIMEOUT/);
  await assert.rejects(f.reader.read({actor}),/JUDGMENT_BUSY/);await assert.rejects(f.reader.drain({timeoutMs:20}),/JUDGMENT_DRAIN_UNCERTAIN/);
  release();await f.reader.drain();assert.equal(f.reader.pending,null);
});

test('judgment CLI and authenticated runtime command work end to end and obey current revocation',async t=>{
  const f=await fixture(t),file=path.join(f.root,'config.json');await atomicJson(file,f.config);const runtime=await startRuntime(file,{offline:true,log:()=>{}});
  f.runtime=runtime;
  const source=f.source('runtime'),{key}=runtime.store.ingest(source),task=runtime.store.createTask(runtime.store.source(key,actor),{title:'PRIVATE_TITLE_SENTINEL',request:'PRIVATE_REQUEST_SENTINEL',action:'research',acceptance:[]});
  const cli=await runCommand(process.execPath,[path.join(runtimeRoot,'bin/kotodama.mjs'),'judgment','--config',file,'--actor',actor,'--task',task.id,'--json'],{cwd:runtimeRoot,timeoutMs:15000});
  assert.equal(cli.code,0,cli.stderr);const report=JSON.parse(cli.stdout);assert.equal(report.tasks.items[0].id,task.id);assert.equal(report.kind,'kotodama.judgment-status');assert(!cli.stdout.includes('PRIVATE_'));
  const before=runtime.store.db.prepare('SELECT total_changes() AS n').get().n;
  await controlCommand(f.config,{action:'judgment',actor,taskId:task.id});assert.equal(runtime.store.db.prepare('SELECT total_changes() AS n').get().n,before);
  await assert.rejects(controlCommand(f.config,{action:'judgment',actor:'100000000000000009'}),/OPERATOR_REQUIRED/);
  f.config.worker.workspace=path.join(f.root,'changed');await atomicJson(file,f.config);assert((await controlCommand(f.config,{action:'judgment',actor})).effective.configurationDrift.includes('workspace'));
  f.config.discord.operators=[other];f.config.dots.enabled=false;await atomicJson(file,f.config);await assert.rejects(controlCommand(f.config,{action:'judgment',actor}),/OPERATOR_REQUIRED/);
  const rejected=await runCommand(process.execPath,[path.join(runtimeRoot,'bin/kotodama.mjs'),'judgment','--config',file,'--actor',actor,'--json'],{cwd:runtimeRoot});assert.equal(rejected.code,1);assert.match(rejected.stdout,/OPERATOR_REQUIRED/);
});
