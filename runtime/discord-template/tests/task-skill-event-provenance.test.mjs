import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
import {CliWorker} from '../src/worker.mjs';
import {exampleConfig} from '../src/config.mjs';
import {runCommand} from '../src/command.mjs';
import {digest,inside} from '../src/common.mjs';
import {projectSkillsDigest} from '../src/project-skill-input.mjs';
import {exportLedger} from '../src/ledger-export.mjs';
import {ledgerKeys,readLedgerPackage} from '../src/ledger-package.mjs';

// One existing local Task owner: actual CLI input -> result observation ->
// protected ledger consumer. Neither delivery nor failure grants quality/adoption.
const actor='100000000000000002',name='sum-method',key='a7'.repeat(32);
const skill=`---\nname: ${name}\ndescription: Sum the supplied finite measurements.\n---\noperation: sum\n`;
const source=(extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:'measurements',actorId:actor,revision:7,readers:[actor],text:'measurements=3,5,8',final:true,...extra});
const request={title:'Sum measurements',request:'Use the selected method on the supplied measurements.',action:'research',acceptance:['Return the sum.']};
const scope={mappingKeyEnv:'KOTODAMA_LEDGER_TEST_KEY',policyId:'fixture-policy',policyRevision:'fixture-revision',retainUntil:'2099-01-01T00:00:00Z',consentBasis:'fixture-owner-scope',knowledgeScope:'fixture-knowledge'};
const repo=fileURLToPath(new URL('../../..',import.meta.url));
const python=process.env.KOTODAMA_TEST_PYTHON??'python';
async function git(cwd,args){const result=await runCommand('git',args,{cwd,timeoutMs:15000});assert.equal(result.code,0,result.stderr);return result.stdout.trim();}
async function fixture(t,{mode='success',text='measurements=3,5,8'}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'kotodama-task-skill-event-')),workspace=path.join(root,'workspace'),data=path.join(root,'data');
  await mkdir(path.join(workspace,'.agents','skills',name),{recursive:true});
  await writeFile(path.join(workspace,'.agents','skills',name,'SKILL.md'),skill);
  await git(workspace,['init','-q']);await git(workspace,['config','core.autocrlf','false']);
  await git(workspace,['config','user.name','Synthetic']);await git(workspace,['config','user.email','synthetic@example.invalid']);
  await git(workspace,['add','.']);await git(workspace,['commit','-qm','fixture method']);
  const head=await git(workspace,['rev-parse','HEAD']),capture=path.join(root,'capture.json'),calls=path.join(root,'calls.jsonl'),cli=path.join(root,'fixture-cli.mjs');
  // This is a local child program, not an actual model/provider. Hash stdin and
  // schema bytes independently before checking the previously persisted proof.
  await writeFile(cli,`
import {readFile,writeFile,appendFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const [capture,calls,data,mode,...args]=process.argv.slice(2),chunks=[];
for await(const chunk of process.stdin)chunks.push(chunk);
const bytes=Buffer.concat(chunks),input=bytes.toString('utf8'),hash=b=>createHash('sha256').update(b).digest('hex');
const task=JSON.parse(input.split('\\nTask\\n')[1].split('\\nSOURCE_CONTEXT\\n')[0]);
const context=JSON.parse(input.split('\\nSOURCE_CONTEXT\\n')[1].split('\\nPROJECT_SKILLS\\n')[0]);
const packet=JSON.parse(input.split('\\nPROJECT_SKILLS\\n')[1].split('\\n結果はJSON')[0]);
const prepared=JSON.parse(await readFile(path.join(data,'artifacts',task.id+'-r'+task.revision,'input-receipt.json'),'utf8'));
const schema=await readFile(args[args.indexOf('--output-schema')+1]);
if(prepared.status!=='prepared'||prepared.inputBinding.stdinSha256!==hash(bytes)||prepared.inputBinding.stdinBytes!==bytes.length||prepared.inputBinding.schemaSha256!==hash(schema))throw Error('pre-input proof differs from actual stdin/schema');
if(packet.skills.length!==1||packet.skills[0].sha256!==hash(packet.skills[0].text)||!packet.skills[0].text.includes('operation: sum'))throw Error('selected method differs');
await writeFile(capture,JSON.stringify({input,task,context,packet,prepared,stdinSha256:hash(bytes),stdinBytes:bytes.length,schemaSha256:hash(schema)}));
await appendFile(calls,JSON.stringify({taskId:task.id,revision:task.revision})+'\\n');
if(mode==='failure'){process.stderr.write('Not logged in. Please run codex login.');process.exit(1);}
if(mode==='skill-drift')await writeFile('.agents/skills/${name}/SKILL.md',packet.skills[0].text+'changed\\n');
const values=context[0].text.slice('measurements='.length).split(',').map(Number);
if(!values.length||values.some(n=>!Number.isFinite(n)))throw Error('invalid measurements');
console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:JSON.stringify({summary:'sum='+values.reduce((a,b)=>a+b,0),files:[]})}}));
`);
  const config=exampleConfig({workspace});config.dataDir=data;config.worker.executable=process.execPath;
  config.worker.args=[cli,capture,calls,data,mode];config.worker.actions=['research'];config.worker.timeoutSeconds=10;
  config.worker.projectSkills={research:[name]};delete config.worker.fallback;
  const store=new Store(data),errors=[],pipeline=new Pipeline({store,config,analyzer:{},worker:new CliWorker(config,{store}),onError:code=>errors.push(code)});
  t.after(async()=>{await pipeline.close();store.close();assert(inside(os.tmpdir(),root)&&path.basename(root).startsWith('kotodama-task-skill-event-'));await rm(root,{recursive:true,force:true});});
  const input=source({text});let outputNumber=0;
  return {root,workspace,data,head,capture,calls,config,store,pipeline,errors,input,
    run:async()=>{const task=await pipeline.request(input,request);await pipeline.tail;return store.taskInternal(task.id);},
    export:()=>{const output=path.join(root,'export-'+outputNumber++),before=store.tasks(actor),result=exportLedger(store,{config,actor,scope,output,env:{[scope.mappingKeyEnv]:key}});assert.deepEqual(store.tasks(actor),before);return {output,result,...readLedgerPackage(output,ledgerKeys(key))};}};
}
function validate(output,{accepted=true}={}){
  const result=spawnSync(python,['-B',path.join(repo,'tools/validate_session_conversation_ledger.py'),'validate',path.join(output,'ledger.jsonl')],{encoding:'utf8',timeout:30000,env:{...process.env,PYTHONUTF8:'1'}});
  assert.equal(result.error,undefined);
  if(!accepted){assert.notEqual(result.status,0);return;}
  assert.equal(result.status,0,result.stderr+'\n'+result.stdout);const receipt=JSON.parse(result.stdout);
  assert.equal(receipt.result,'LEDGER_VALID');assert.equal(receipt.promotion_eligible,false);
}
async function delivered(f,task){
  const captured=JSON.parse(await readFile(f.capture,'utf8')),prepared=JSON.parse(await readFile(path.join(f.data,'artifacts',task.id+'-r'+task.revision,'input-receipt.json'),'utf8'));
  assert.deepEqual(prepared,captured.prepared);assert.deepEqual(captured.task.contextSources,task.contextSources);
  assert.deepEqual(captured.context,[f.store.source(task.source_key,actor)]);
  assert.equal(captured.task.id,task.id);assert.equal(captured.task.revision,task.revision);assert.equal(captured.task.source_key,task.source_key);assert.equal(captured.task.source_revision,task.source_revision);
  assert.deepEqual(prepared.taskBinding,{taskId:task.id,taskRevision:task.revision,sourceRevision:task.source_revision,contextSha256:digest(captured.context)});
  assert.deepEqual(prepared.inputBinding,{stdinSha256:digest(Buffer.from(captured.input)),stdinBytes:Buffer.byteLength(captured.input),schemaSha256:captured.schemaSha256});
  assert.equal(captured.packet.authority,'method_only');assert.equal(captured.packet.selection,'operator_action_config');
  assert.equal(captured.packet.action,'research');assert.deepEqual(captured.packet.selectedActions,['research']);
  assert.equal(prepared.action,'research');assert.deepEqual(prepared.selectedActions,['research']);assert.equal(prepared.configSha256,projectSkillsDigest(f.config.worker.projectSkills));
  assert.equal(captured.packet.sourceRevision,f.head);assert.equal(prepared.sourceRevision,f.head);
  assert.equal(prepared.version,1);assert.deepEqual(prepared.skills,[{name,sha256:digest(skill),bytes:Buffer.byteLength(skill)}]);
  assert.deepEqual(captured.packet.skills,[{...prepared.skills[0],text:skill}]);
  assert.equal(prepared.status,'prepared');assert.equal(prepared.modelObedience,'not_evaluated');assert.equal(prepared.hostSkillDiscovery,'not_observed');
  return {captured,prepared};
}
function assertObservation(exported,task){
  const entry=exported.payload.entries.find(e=>e.payload.store_event.type==='task.result'&&e.payload.store_event.task_id===task.id);assert(entry);
  const raw=entry.payload.store_event,body=JSON.parse(raw.body),rows=exported.ledger.toString('utf8').trim().split('\n').map(JSON.parse),row=rows.find(r=>r.event_id===entry.event_ref);
  assert.equal(raw.type,'task.result');assert.equal(entry.summary.store_event_type,raw.type);
  assert.deepEqual(body,{state:task.state,artifact_count:task.result.artifacts.length,ledgerBinding:{version:1,taskId:task.id,taskRevision:task.revision,actor,source:{key:task.source_key,revision:task.source_revision},contextSources:task.contextSources}});
  assert.equal(entry.recovery.store_sequence,raw.seq);assert.equal(entry.recovery.payload_sha256,digest(entry.payload));assert.equal(row.content.content_hash,digest(entry.payload));
  assert.equal(row.kind,'kotodama.conversation-event');assert.equal(row.schema_revision,'v1');assert.equal(row.event.kind,'agent_action');
  assert.equal(row.content.storage,'PROTECTED_PAYLOAD_VAULT');assert.equal(row.event.state,'OBSERVED');assert.equal(row.session.state,'UNASSIGNED_INBOX');
  assert.equal(row.session.governance.task_ssot_ref,null);assert.equal(row.decision.status,'NONE');assert.equal(row.decision.current_truth_ref,null);assert.equal(row.decision.execution_authority_granted,false);
  assert.equal(row.provenance.extraction.kind,'NONE');assert.equal(row.provenance.extraction.confirmation_required,true);
  const sourceEntry=exported.payload.entries.find(e=>e.payload.source?.key===task.source_key&&e.payload.source.revision===task.source_revision);assert(sourceEntry);
  assert(row.causation.caused_by_event_refs.includes(sourceEntry.event_ref));
  for(let i=0;i<rows.length;i++){const {event_hash,...body}=rows[i];assert.equal(event_hash,digest(body));assert.equal(rows[i].sequence,i+1);assert.equal(rows[i].previous_event_hash,i?rows[i-1].event_hash:'0'.repeat(64));assert.equal(rows[i].decision.status,'NONE');}
  return {entry,row,rows};
}
async function assertThrownFailure(f,task,code){
  assert.equal(task.state,'failed');assert.deepEqual(task.result,{state:'failed',summary:code,artifacts:[]});assert.deepEqual(f.errors,[code]);
  assert(!Object.hasOwn(task.result,'inputBinding'));assert(!Object.hasOwn(task.result,'skillDelivery'));assert(!Object.hasOwn(task.result,'verifiedExecution'));
  await assert.rejects(readFile(path.join(f.data,'artifacts',task.id+'-r'+task.revision,'receipt.json')),{code:'ENOENT'});
  await assert.rejects(readFile(path.join(f.data,'artifacts',task.id+'-r'+task.revision,'result.md')),{code:'ENOENT'});
  return delivered(f,task);
}

for(const [text,total] of [['measurements=3,5,8',16],['measurements=7,4',11]])test(`actual Task/Skill stdin and independently computed sum ${total} retain observational event provenance`,async t=>{
  const f=await fixture(t,{text}),task=await f.run(),{prepared}=await delivered(f,task);
  assert.equal(task.state,'needs_review');assert.equal(task.result.summary,'sum='+total);assert.equal(task.result.independentReview,false);
  assert.deepEqual(task.result.skillDelivery,{...prepared,status:'submitted_to_cli'});
  assert.deepEqual(JSON.parse(await readFile(path.join(f.data,'artifacts',task.id+'-r'+task.revision,'receipt.json'),'utf8')),task.result);
  assert.equal(digest(await readFile(task.result.artifacts[0].path)),task.result.artifacts[0].sha256);
  const exported=f.export();assertObservation(exported,task);validate(exported.output);
});

test('actual thrown CLI failure retains prepared input proof and raw task.result without verification or promotion',async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  const exported=f.export();assertObservation(exported,task);validate(exported.output);
  const bytes=await readFile(path.join(exported.output,'payload.aes256gcm'));
  assert.equal(exportLedger(f.store,{config:f.config,actor,scope,output:exported.output,env:{[scope.mappingKeyEnv]:key}}).state,'duplicate');
  assert.deepEqual(await readFile(path.join(exported.output,'payload.aes256gcm')),bytes);
  const replay=await f.run();assert.deepEqual(replay,task);assert.equal((await readFile(f.calls,'utf8')).trim().split('\n').length,1);
  const repeated=f.export();assert.deepEqual(repeated.ledger,exported.ledger);assertObservation(repeated,task);validate(repeated.output);
});

test('current selected Skill byte drift refuses the actual child result while its pre-input proof stays prepared',async t=>{
  const f=await fixture(t,{mode:'skill-drift'}),task=await f.run();await assertThrownFailure(f,task,'PROJECT_SKILL_UNCOMMITTED');
  assertObservation(f.export(),task);
});

const mutations={
  'unknown raw kind':({raw})=>{raw.type='task.failed';},
  'wrong binding version':({body})=>{body.ledgerBinding.version=2;},
  'wrong Task ID':({body})=>{body.ledgerBinding.taskId='task-unknown';},
  'invalid Task revision':({body})=>{body.ledgerBinding.taskRevision=0;},
  'unknown Source ID':({body})=>{body.ledgerBinding.source.key='unknown-source';},
};
for(const [label,mutate] of Object.entries(mutations))test(`failed Task observation with ${label} is omitted, never replaced or promoted`,async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  const raw=f.store.statement("SELECT * FROM events WHERE type='task.result' AND task_id=?").get(task.id),body=JSON.parse(raw.body);mutate({raw,body});
  f.store.statement('UPDATE events SET type=?,body=? WHERE seq=?').run(raw.type,JSON.stringify(body),raw.seq);
  const exported=f.export();assert(exported.result.omitted_events>0);
  assert(!exported.payload.entries.some(e=>e.payload.store_event.seq===raw.seq));assert.deepEqual(f.store.taskInternal(task.id),task);validate(exported.output);
});

test('an unavailable historical Source revision refuses export rather than borrowing current bytes',async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  const raw=f.store.statement("SELECT * FROM events WHERE type='task.result' AND task_id=?").get(task.id),body=JSON.parse(raw.body);body.ledgerBinding.source.revision=999;
  f.store.statement('UPDATE events SET body=? WHERE seq=?').run(JSON.stringify(body),raw.seq);
  assert.throws(()=>f.export(),{code:'LEDGER_SOURCE_HISTORY_MISSING'});assert.deepEqual(f.store.taskInternal(task.id),task);
});

test('current Source withdrawal excludes prior failed Task observations and refuses redispatch',async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  f.store.ingest(source({sourceId:'unrelated',text:'still readable'}));f.store.ingest({...f.input,revision:8,withdrawn:true});
  const exported=f.export();assert.equal(exported.result.records,1);assert(!JSON.stringify(exported.payload).includes(task.id));validate(exported.output);
  await assert.rejects(f.pipeline.request(f.input,request),{code:'SOURCE_ACCESS_DENIED'});
  assert.equal((await readFile(f.calls,'utf8')).trim().split('\n').length,1);
});

test('a Source withdrawn before admission causes zero actual child dispatch',async t=>{
  const f=await fixture(t);f.input.withdrawn=true;f.store.ingest({...f.input,metadata:{command:request}});
  await assert.rejects(f.run(),{code:'SOURCE_ACCESS_DENIED'});
  await assert.rejects(readFile(f.capture),{code:'ENOENT'});assert.equal(f.store.tasks(actor).length,0);
});

test('current operator withdrawal refuses failed observation export without changing its owner or redispatching',async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  f.config.discord.operators=[];assert.throws(()=>f.export(),{code:'OPERATOR_REQUIRED'});
  await assert.rejects(f.pipeline.request(f.input,request),{code:'OPERATOR_REQUIRED'});assert.deepEqual(f.store.taskInternal(task.id),task);
  assert.equal((await readFile(f.calls,'utf8')).trim().split('\n').length,1);
});

test('Source correction keeps historical failure provenance on its original revision and does not redispatch the stale Task',async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');
  f.store.ingest({...f.input,revision:8,text:'measurements=99'});const current=f.store.taskInternal(task.id);
  assert.equal(current.id,task.id);assert.equal(current.revision,task.revision+1);assert.equal(current.state,'stale');assert.equal(current.result,null);
  const exported=f.export(),{entry}=assertObservation(exported,task);validate(exported.output);
  assert.equal(JSON.parse(entry.payload.store_event.body).ledgerBinding.source.revision,7);
  assert.equal(exported.payload.entries.find(e=>e.payload.source?.revision===7).payload.source.text,f.input.text);
  assert.equal(exported.payload.entries.find(e=>e.payload.source?.revision===8).payload.source.text,'measurements=99');
  f.pipeline.enqueue(task.id,actor,task.revision);await f.pipeline.tail;
  assert.equal((await readFile(f.calls,'utf8')).trim().split('\n').length,1);assert.deepEqual(f.store.taskInternal(task.id),current);
});

for(const mutation of ['protected payload digest','record kind','record order'])test(`failed observation consumer refuses ${mutation} tampering without adopting the failure`,async t=>{
  const f=await fixture(t,{mode:'failure'}),task=await f.run();await assertThrownFailure(f,task,'CODEX_LOGIN_REQUIRED');const exported=f.export();assertObservation(exported,task);
  if(mutation==='protected payload digest'){
    const filename=path.join(exported.output,'payload.aes256gcm'),bytes=await readFile(filename);bytes[0]^=1;await writeFile(filename,bytes);
    assert.throws(()=>readLedgerPackage(exported.output,ledgerKeys(key)),/TAMPERED/);
  }else{
    const filename=path.join(exported.output,'ledger.jsonl'),lines=(await readFile(filename,'utf8')).trim().split('\n');
    if(mutation==='record kind'){const row=JSON.parse(lines.at(-1));row.kind='kotodama.verified-result';lines[lines.length-1]=JSON.stringify(row);}
    else [lines[0],lines[1]]=[lines[1],lines[0]];
    await writeFile(filename,lines.join('\n')+'\n');assert.throws(()=>readLedgerPackage(exported.output,ledgerKeys(key)),/TAMPERED/);validate(exported.output,{accepted:false});
  }
  assert.deepEqual(f.store.taskInternal(task.id),task);
});
