import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile,cp,symlink,mkdir} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {Store} from '../src/store.mjs';
import {exampleConfig} from '../src/config.mjs';
import {digest,inside} from '../src/common.mjs';
import {exportLedger} from '../src/ledger-export.mjs';
import {ledgerKeys,readLedgerPackage} from '../src/ledger-package.mjs';
import {startRuntime} from '../src/runtime.mjs';

const actor='100000000000000002',raw='非公開原文-機密比較用',key='a7'.repeat(32);
const source=(extra={})=>({provider:'discord',guildId:'100000000000000001',channelId:'100000000000000003',sourceId:'100000000000000004',actorId:actor,revision:1,readers:[actor],text:raw,final:true,metadata:{kind:'text',createdAt:'2026-10-01T00:00:00Z',privatePath:'C:\\private\\sample.txt',host:'private.example.test'},...extra});
const scope={mappingKeyEnv:'KOTODAMA_LEDGER_TEST_KEY',policyId:'fixture-policy',policyRevision:'fixture-revision',retainUntil:'2099-01-01T00:00:00Z',consentBasis:'fixture-owner-scope',knowledgeScope:'fixture-knowledge'};
const python=process.env.KOTODAMA_TEST_PYTHON??'python';
const repo=fileURLToPath(new URL('../../..',import.meta.url));
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'kotodama-ledger-test-')),store=new Store(path.join(root,'data'));
  t.after(async()=>{store.close();assert(inside(os.tmpdir(),root)&&path.basename(root).startsWith('kotodama-ledger-test-'));await rm(root,{recursive:true,force:true});});
  const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');const output=path.join(root,'export');
  const options={config,actor,scope,output,env:{[scope.mappingKeyEnv]:key}};
  return {root,store,options,output,run:overrides=>exportLedger(store,{...options,...overrides})};
}
function seed(store){
  const first=store.ingest(source());store.ingest(source({revision:2,text:raw+'訂正'}));
  const s=store.source(first.key,actor),task=store.createTask(s,{action:'write_file',request:'fixture-request',title:'fixture',intentIds:[],acceptance:[]},'request-1');
  store.claim(task.id,task.revision);store.finish(task.id,task.revision,{state:'needs_review',summary:raw,artifacts:[]});return task;
}
function validate(output){
  const result=spawnSync(python,['-B',path.join(repo,'tools/validate_session_conversation_ledger.py'),'validate',path.join(output,'ledger.jsonl')],{encoding:'utf8',timeout:30000,env:{...process.env,PYTHONUTF8:'1'}});
  assert.equal(result.status,0,result.stderr+'\n'+result.stdout);const receipt=JSON.parse(result.stdout);assert.equal(receipt.result,'LEDGER_VALID');assert.equal(receipt.promotion_eligible,false);return receipt;
}
test('real SQLite export passes Python ledger validator, restores exact versions and preserves Task owner',async t=>{
  const f=await fixture(t),task=seed(f.store),before=f.store.taskInternal(task.id),result=f.run();assert.equal(result.state,'created');assert.equal(result.records,5);
  const restored=readLedgerPackage(f.output,ledgerKeys(key)),rows=restored.ledger.toString('utf8').trim().split('\n').map(JSON.parse);validate(f.output);
  assert.deepEqual(f.store.taskInternal(task.id),before);assert.equal(f.store.lock(),undefined);
  assert.equal(restored.payload.entries[0].payload.source.text,raw);assert.equal(restored.payload.entries[1].payload.source.text,raw+'訂正');
  assert.equal(rows[1].event.kind,'source_update');assert.deepEqual(rows[1].event.invalidation_refs,[rows[0].event_id]);assert.deepEqual(rows[1].causation.caused_by_event_refs,[rows[0].event_id]);
  assert.equal(rows[1].event.correction_of_event_ref,null);assert.deepEqual(rows[2].causation.caused_by_event_refs,[rows[1].event_id]);
  assert.equal(rows[2].causation.correlation_ref,rows[4].causation.correlation_ref);
  for(let i=0;i<rows.length;i++){const {event_hash,...body}=rows[i];assert.equal(event_hash,digest(body));assert.equal(rows[i].sequence,i+1);assert.equal(rows[i].previous_event_hash,i?rows[i-1].event_hash:'0'.repeat(64));assert.equal(rows[i].decision.status,'NONE');}
  for(const name of ['ledger.jsonl','manifest.json']){const text=await readFile(path.join(f.output,name),'utf8');for(const secret of [raw,actor,'100000000000000001','100000000000000003','100000000000000004','private.example.test','privatePath','sample.txt',f.root,key])assert(!text.includes(secret),secret);}
  const ciphertext=await readFile(path.join(f.output,'payload.aes256gcm'));assert(!ciphertext.includes(Buffer.from(raw)));
});
test('same snapshot is idempotent and changed snapshot never overwrites a package',async t=>{
  const f=await fixture(t);seed(f.store);f.run();const before=await readFile(path.join(f.output,'payload.aes256gcm'));assert.equal(f.run().state,'duplicate');
  f.store.ingest(source({revision:3,text:'changed'}));assert.throws(()=>f.run(),/LEDGER_PACKAGE_CONFLICT/);assert.deepEqual(await readFile(path.join(f.output,'payload.aes256gcm')),before);assert.equal(f.store.lock(),undefined);
});
test('later observations extend a stable prefix when source access and scope remain the same',async t=>{
  const f=await fixture(t);seed(f.store);f.run();const first=await readFile(path.join(f.output,'ledger.jsonl'),'utf8');
  f.store.ingest(source({revision:3,text:'third revision'}));const next=path.join(f.root,'next');f.run({output:next});validate(next);
  assert((await readFile(path.join(next,'ledger.jsonl'),'utf8')).startsWith(first));
});
test('wrong key, ciphertext and ledger tampering are refused',async t=>{
  const f=await fixture(t);seed(f.store);f.run();assert.throws(()=>readLedgerPackage(f.output,ledgerKeys('b8'.repeat(32))),/BINDING_MISMATCH/);
  const cipher=path.join(f.output,'payload.aes256gcm'),original=await readFile(cipher),changed=Buffer.from(original);changed[0]^=1;await writeFile(cipher,changed);
  assert.throws(()=>readLedgerPackage(f.output,ledgerKeys(key)),/TAMPERED/);await writeFile(cipher,original);
  const ledger=path.join(f.output,'ledger.jsonl');await writeFile(ledger,(await readFile(ledger,'utf8')).replace('OBSERVED','CANDIDATE'));
  assert.throws(()=>readLedgerPackage(f.output,ledgerKeys(key)),/TAMPERED/);
});
test('manifest authentication rejects a changed ciphertext even with a recomputed public digest',async t=>{
  const f=await fixture(t);seed(f.store);f.run();const cipher=path.join(f.output,'payload.aes256gcm'),bytes=await readFile(cipher);bytes[1]^=1;await writeFile(cipher,bytes);
  const filename=path.join(f.output,'manifest.json'),manifest=JSON.parse(await readFile(filename));manifest.cipher_sha256=digest(bytes);await writeFile(filename,JSON.stringify(manifest));
  assert.throws(()=>readLedgerPackage(f.output,ledgerKeys(key)),/DECRYPTION_REFUSED/);
});
test('extra files, another destination and directory links cannot masquerade as the original package',async t=>{
  const f=await fixture(t);seed(f.store);f.run();const moved=path.join(f.root,'copied');await cp(f.output,moved,{recursive:true});assert.throws(()=>readLedgerPackage(moved,ledgerKeys(key)),/BINDING_MISMATCH/);
  const link=path.join(f.root,'link');await symlink(f.output,link,process.platform==='win32'?'junction':'dir');assert.throws(()=>readLedgerPackage(link,ledgerKeys(key)),/DIRECTORY_REFUSED/);
  await writeFile(path.join(f.output,'unexpected.txt'),'extra');assert.throws(()=>readLedgerPackage(f.output,ledgerKeys(key)),/FILES_INVALID/);
});
test('runtime lock, remote owner, nonoperator, missing key and expired scope refuse before output',async t=>{
  const f=await fixture(t);seed(f.store);f.store.claimHost('owned-runtime',process.pid,'fixture','fixture');assert.throws(()=>f.run(),/STOP_RUNTIME/);assert.equal(f.store.lock().owner,'owned-runtime');f.store.releaseHost('owned-runtime');
  assert.throws(()=>f.run({config:{...f.options.config,owner:{kind:'remote'}}}),/LOCAL_OWNER_REQUIRED/);
  assert.throws(()=>f.run({actor:'100000000000000099'}),/OPERATOR_REQUIRED/);assert.throws(()=>f.run({env:{}}),/KEY_REQUIRED/);
  assert.throws(()=>f.run({scope:{...scope,retainUntil:'2000-01-01T00:00:00Z'}}),/SCOPE_EXPIRED/);await assert.rejects(readFile(path.join(f.output,'ledger.jsonl')),/ENOENT/);
});
test('current ACL withdrawal excludes historical raw text and Task events, missing authorized version refuses',async t=>{
  const f=await fixture(t),task=seed(f.store);f.store.ingest(source({sourceId:'unrelated',text:'readable-other'}));
  f.store.ingest(source({revision:3,withdrawn:true}));const result=f.run();assert.equal(result.records,1);assert(result.omitted_events>=5);
  const restored=readLedgerPackage(f.output,ledgerKeys(key));assert(!JSON.stringify(restored.payload).includes(raw));assert(!JSON.stringify(restored.payload).includes(task.id));
  const g=await fixture(t);seed(g.store);g.store.statement('DELETE FROM source_versions WHERE revision=1').run();assert.throws(()=>g.run(),/SOURCE_HISTORY_MISSING/);assert.equal(g.store.lock(),undefined);
});
test('voice source keeps its actual track and exact payload without claiming audio recovery',async t=>{
  const f=await fixture(t);f.store.ingest(source({metadata:{kind:'voice',inputAccountId:actor,sessionId:'fixture-session',createdAt:'2026-10-01T00:00:00Z',rawText:raw,startMs:20,endMs:40}}));f.run();validate(f.output);
  const restored=readLedgerPackage(f.output,ledgerKeys(key)),row=JSON.parse(restored.ledger.toString('utf8'));assert.equal(row.source.type,'discord_voice');assert(row.source.speaker_track_ref.startsWith('ref/track/'));assert.equal(row.content.artifact_stage,'RAW_SOURCE_JSON');assert.deepEqual(row.content.derived_from_event_refs,[]);
  assert.equal(restored.payload.entries[0].payload.source.metadata.rawText,raw);
});
test('historical Task input bindings cannot borrow a revised Task current Source ACL',async t=>{
  const f=await fixture(t),task=seed(f.store),oldSource=f.store.source(task.source_key,actor);
  const fresh=f.store.ingest(source({sourceId:'new-source',text:'new-input'})),s=f.store.source(fresh.key,actor);
  const revised=f.store.reviseTask(task.id,s,{action:'write_file',title:'new',request:'new-input',intentIds:[]});
  f.store.claim(task.id,revised.revision);f.store.finish(task.id,revised.revision,{state:'needs_review',summary:'new-result',artifacts:[]});
  f.store.ingest({...oldSource,revision:oldSource.revision+1,withdrawn:true});f.run();validate(f.output);
  const exported=readLedgerPackage(f.output,ledgerKeys(key)).payload.entries.map(e=>e.payload.store_event).filter(e=>e.task_id===task.id);
  assert.deepEqual(exported.map(e=>e.type),['task.started','task.result']);
  assert(exported.every(e=>JSON.parse(e.body).ledgerBinding.source.key===fresh.key));
});
test('old context is checked at event time and legacy Task events without a binding are omitted',async t=>{
  const f=await fixture(t),task=seed(f.store),context=f.store.ingest(source({sourceId:'context',text:'context-private'})),s=f.store.source(context.key,actor);
  const revised=f.store.reviseTask(task.id,f.store.source(task.source_key,actor),{action:'write_file',title:'same',request:'fixture-request',intentIds:[]});
  f.store.claim(task.id,revised.revision);f.store.bindContext(task.id,revised.revision,[{key:s.key,revision:s.revision}]);
  f.store.event('task.result',{state:'failed',marker:'forbidden-old-context'},task.id);
  f.store.bindContext(task.id,revised.revision,[]);f.store.ingest({...s,revision:2,withdrawn:true});
  f.store.statement("UPDATE events SET body=json_remove(body,'$.ledgerBinding') WHERE type='task.created'").run();
  f.run();validate(f.output);const text=JSON.stringify(readLedgerPackage(f.output,ledgerKeys(key)).payload);
  assert(!text.includes('forbidden-old-context'));assert(!readLedgerPackage(f.output,ledgerKeys(key)).payload.entries.some(e=>e.payload.store_event.type==='task.created'));
});
test('a current voice opt-out excludes captured voice and its dependent Task events',async t=>{
  const f=await fixture(t);const voice=f.store.ingest(source({sourceId:'voice-source',metadata:{kind:'voice',inputAccountId:actor,sessionId:'voice-session'}})),s=f.store.source(voice.key,actor);
  const task=f.store.createTask(s,{action:'write_file',request:'fixture-request',title:'voice',intentIds:[]},'voice-request');f.store.claim(task.id,task.revision);f.store.finish(task.id,task.revision,{state:'needs_review',artifacts:[]});
  f.store.ingest(source({sourceId:'unrelated',text:'visible-text'}));f.store.recordConsent({guild:s.guildId,channel:s.channelId,actor,notice:'fixture',granted:false,interactionId:'100000000000000030'});
  const result=f.run();assert.equal(result.records,1);const restored=JSON.stringify(readLedgerPackage(f.output,ledgerKeys(key)).payload);assert(!restored.includes('voice-session')&&!restored.includes(task.id));validate(f.output);
});
test('retention dates must round-trip as real UTC calendar timestamps before any output',async t=>{
  const f=await fixture(t);seed(f.store);
  for(const retainUntil of ['2099-02-31T00:00:00Z','2100-02-29T00:00:00Z','2099-04-31T00:00:00Z','2099-12-31T24:00:00Z'])assert.throws(()=>f.run({scope:{...scope,retainUntil}}),/SCOPE_EXPIRED_OR_INVALID/);
  await assert.rejects(readFile(path.join(f.output,'ledger.jsonl')),/ENOENT/);
  f.run({scope:{...scope,retainUntil:'2096-02-29T01:02:03.004Z'}});validate(f.output);
});
test('a killed exporter leaves no persistent lock and normal runtime startup works',async t=>{
  const f=await fixture(t);seed(f.store);const configPath=path.join(f.root,'config.json');await writeFile(configPath,JSON.stringify(f.options.config));
  const script=`import fs from 'node:fs';import {syncBuiltinESMExports} from 'node:module';import {Store} from ${JSON.stringify(new URL('../src/store.mjs',import.meta.url).href)};import {exportLedger} from ${JSON.stringify(new URL('../src/ledger-export.mjs',import.meta.url).href)};const options=JSON.parse(process.argv[1]);const original=fs.writeFileSync;fs.writeFileSync=(file,...args)=>{if(String(file).endsWith('payload.aes256gcm'))process.kill(process.pid,'SIGKILL');return original(file,...args)};syncBuiltinESMExports();exportLedger(new Store(options.config.dataDir),options);`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script,JSON.stringify(f.options)],{timeout:15000,encoding:'utf8'});assert.notEqual(child.status,0);assert.equal(child.error,undefined);assert.equal(f.store.lock(),undefined);
  const runtime=await startRuntime(configPath,{offline:true,log:()=>{}});await runtime.close();assert.equal(f.store.lock(),undefined);
  f.run({output:path.join(f.root,'retry')});validate(path.join(f.root,'retry'));
});
test('export refuses a borrowed transaction rather than assuming it owns the writer reservation',async t=>{
  const f=await fixture(t);seed(f.store);assert.throws(()=>f.store.transaction(()=>f.run()),/REQUIRES_OWN_TRANSACTION/);assert.equal(f.store.lock(),undefined);
});
test('CLI ledger-export is distinct from document export and reports no private bytes or paths',async t=>{
  const f=await fixture(t);seed(f.store);const configPath=path.join(f.root,'config.json'),scopePath=path.join(f.root,'scope.json');await writeFile(configPath,JSON.stringify(f.options.config));await writeFile(scopePath,JSON.stringify(scope));
  const cli=fileURLToPath(new URL('../bin/kotodama.mjs',import.meta.url));const result=spawnSync(process.execPath,[cli,'ledger-export','--config',configPath,'--actor',actor,'--scope',scopePath,'--output',f.output,'--json'],{encoding:'utf8',timeout:30000,env:{...process.env,[scope.mappingKeyEnv]:key}});
  assert.equal(result.status,0,result.stderr+'\n'+result.stdout);assert.equal(JSON.parse(result.stdout).records,5);assert(!result.stdout.includes(f.root)&&!result.stdout.includes(raw)&&!result.stdout.includes(actor));validate(f.output);
});
