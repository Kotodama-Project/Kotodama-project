import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,rm,unlink,writeFile,readFile,link,symlink,realpath} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {ArchiveAdapter} from '../src/archive-adapter.mjs';
import {createArchiveSink,createArchiveIntentRecorder} from '../src/archive-host.mjs';
import {Store} from '../src/store.mjs';
import {digest,inside,atomicJson} from '../src/common.mjs';
import {exampleConfig} from '../src/config.mjs';
import {recordRetentionReadback,retentionLocalPath,readRetentionInput} from '../src/retention-readback.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {runCommand} from '../src/command.mjs';
import {fileURLToPath} from 'node:url';

async function fixture(t){
  const root=await realpath(await mkdtemp(path.join(os.tmpdir(),'retention-readback-'))),tempRoot=await realpath(os.tmpdir()),dataDir=path.join(root,'data'),archiveRoot=path.join(root,'recordings');
  await mkdir(archiveRoot);const store=new Store(dataDir);let adapter;
  t.after(async()=>{adapter?.close();store.close();assert(inside(tempRoot,root)&&path.basename(root).startsWith('retention-readback-'));await rm(root,{recursive:true,force:true});});
  const config=exampleConfig({workspace:root}),actor=config.discord.operators[0];config.dataDir=dataDir;config.discord.voiceChannelId=config.discord.resultChannelId;config.agentBinding={agentId:'synthetic-agent',vmId:'synthetic-vm'};
  config.archive={enabled:false,archiveRoot,journalPath:path.join(dataDir,'archive.sqlite'),retentionPolicyRef:'ref/policy/synthetic',sourceRef:'ref/source/synthetic',actorId:actor,readers:[actor],whisperEndpoint:'http://127.0.0.1:1/transcribe'};
  const started=Date.parse('2026-06-01T00:00:00Z'),endFrame=48049;
  const binding={sessionId:'session-synthetic',guildId:config.discord.guildId,channelId:config.discord.voiceChannelId,startedAtMs:started,sampleRateHz:48000,channels:1,sampleFormat:'s16le',speakerIds:[actor],sourceRef:config.archive.sourceRef,retentionPolicyRef:config.archive.retentionPolicyRef,actorId:actor,readers:[actor],installation:config.installation,agentId:config.agentBinding.agentId,vmId:config.agentBinding.vmId};
  const sink=createArchiveSink({archiveRoot,authorize:()=>true,clock:()=>started+2000});
  adapter=new ArchiveAdapter({journalPath:config.archive.journalPath,authorize:()=>true,sink,asr:async()=>[{idx:0,start:0,end:1,text:'SYNTHETIC_PRIVATE_TRANSCRIPT',confidence:1}],correct:async()=>[],recordIntent:createArchiveIntentRecorder({store,analyzer:{analyze:async()=>({intents:[]})},sink,authorize:()=>true})});
  adapter.begin(binding);const pcm=Buffer.alloc(endFrame*2);pcm.writeInt16LE(50,0);adapter.append({sessionId:binding.sessionId,speakerId:actor,sourceId:'synthetic-chunk',startFrame:0,pcm});adapter.seal(binding.sessionId,endFrame);await adapter.processNext();
  const archived=JSON.parse(adapter.session(binding.sessionId).receipt),dir=archived.archiveRef;
  const retainUntil=Date.parse(new Date(started+endFrame/48).toISOString())+30*86400000,now=retainUntil+1000;
  const receipt={kind:'kotodama.retention-deletion-receipt',schema_revision:'v1',receipt_ref:'ref/deletion-receipt/synthetic',session_ref:'ref/session/synthetic',archive_binding_digest:digest(binding),policy_ref:'ref/policy/synthetic',policy_revision_ref:'ref/policy-revision/synthetic',trigger:'expiry',deadline:{retain_until:new Date(retainUntil).toISOString(),delete_by:new Date(now+60000).toISOString()},deleted_at:new Date(now-10).toISOString(),artifacts:[['RAW_AUDIO_PCM','.pcm'],['RAW_AUDIO_ENCODED','.mp3']].map(([kind,ext])=>{const files=archived.files.filter(f=>f.ref.endsWith(ext));return {kind,count:files.length,pre_delete_sha256:files.map(f=>f.sha256),manifest_entry_sha256:files.map(f=>digest(f))};}),retained_by_policy:['RAW_ASR','CORRECTED_TRANSCRIPT','SOURCE_EVIDENCE'],readback:{status:'CONFIRMED',residual_count:0,checked_at:new Date(now).toISOString()},authority_granted:false,gate_closed:false,public_beta_go:false,contains_content:false,receipt_authenticity:'UNVERIFIED'};
  const scope={archive_session_id:binding.sessionId,archive_policy_ref:binding.retentionPolicyRef,session_ref:receipt.session_ref,policy_ref:receipt.policy_ref,policy_revision_ref:receipt.policy_revision_ref,archive_binding_digest:digest(binding),delete_by:receipt.deadline.delete_by};
  const f={root,config,current:structuredClone(config),actor,store,adapter,dir,archived,binding,receipt,scope,now};
  f.verify=extra=>recordRetentionReadback({receipt:f.receipt,scope:f.scope,actor,config,store,readConfig:async()=>f.current,policy:()=>f.current,clock:()=>f.now,...extra});
  f.deleteFixtureAudio=async()=>{for(const item of archived.files){const target=path.join(dir,item.ref);assert(inside(root,target));await unlink(target);}};
  f.events=()=>store.statement("SELECT body FROM events WHERE type='retention.deletion_readback'").all();return f;
}

test('real archive output remains untouched on refusal; synthetic owner deletion yields content-free local evidence',async t=>{
  const f=await fixture(t);await assert.rejects(f.verify(),/RETENTION_RESIDUAL_AUDIO/);assert.equal(f.events().length,0);
  assert.equal((await readFile(path.join(f.dir,f.archived.files[0].ref))).length,f.archived.files[0].size);
  await f.deleteFixtureAudio();const result=await f.verify();assert.equal(result.evidence,'LOCAL_READBACK_ONLY');assert.equal(result.duplicate,false);assert.equal(result.gate_closed,false);
  const published=JSON.stringify(result);for(const secret of [f.actor,f.dir,f.binding.sessionId,'SYNTHETIC_PRIVATE_TRANSCRIPT'])assert(!published.includes(secret));
  assert.equal((await f.verify()).duplicate,true);assert.equal(f.events().length,1);
  await writeFile(path.join(f.dir,'mixed.pcm'),Buffer.from([1,0]));await assert.rejects(f.verify(),/RETENTION_RESIDUAL_AUDIO/);assert.equal(f.events().length,1);
});

test('receipt cannot choose another policy/session, omit files, swap hash pairs, claim retained text, or miss live deadline',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();const original=structuredClone(f.receipt);
  const changes=[r=>r.archive_binding_digest='f'.repeat(64),r=>r.policy_revision_ref='ref/policy-revision/other',r=>r.artifacts.pop(),r=>r.artifacts[0].manifest_entry_sha256[0]='f'.repeat(64),r=>r.artifacts[0].pre_delete_sha256[0]='e'.repeat(64),r=>r.retained_by_policy.pop(),r=>r.deadline.retain_until=new Date(f.now-2000).toISOString()];
  for(const change of changes){f.receipt=structuredClone(original);change(f.receipt);await assert.rejects(f.verify(),/RETENTION_/);}
  f.receipt=original;f.now+=60001;await assert.rejects(f.verify(),/RETENTION_LIVE_DEADLINE_EXCEEDED/);assert.equal(f.events().length,0);
});

test('residual journal PCM, unknown file and changed retained transcript fail closed',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();
  f.adapter.db.prepare('INSERT INTO archive_frames VALUES(?,?,?,?,?,?)').run(f.binding.sessionId,'residual',f.actor,0,Buffer.from([1,0]),'a'.repeat(64));await assert.rejects(f.verify(),/RETENTION_RESIDUAL_AUDIO/);
  f.adapter.db.prepare('DELETE FROM archive_frames WHERE session=?').run(f.binding.sessionId);
  await writeFile(path.join(f.dir,'renamed-audio.bin'),'{}');await assert.rejects(f.verify(),/RETENTION_UNKNOWN_RESIDUAL/);await unlink(path.join(f.dir,'renamed-audio.bin'));
  await writeFile(path.join(f.dir,'transcript.json'),'{}');await assert.rejects(f.verify(),/RETENTION_TEXT_CHANGED/);assert.equal(f.events().length,0);
});

test('missing retained metadata, unfinished journal and changed journal are refused',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();const id=f.binding.sessionId;
  f.adapter.db.prepare("UPDATE archive_sessions SET state='queued' WHERE id=?").run(id);await assert.rejects(f.verify(),/RETENTION_ARCHIVE_NOT_COMPLETE/);
  f.adapter.db.prepare("UPDATE archive_sessions SET state='done' WHERE id=?").run(id);let reads=0;
  await assert.rejects(f.verify({readConfig:async()=>{if(++reads===2)f.adapter.db.prepare('UPDATE archive_sessions SET end_frame=end_frame+1 WHERE id=?').run(id);return f.current;}}),/RETENTION_JOURNAL_CHANGED/);
  f.adapter.db.prepare('UPDATE archive_sessions SET end_frame=end_frame-1 WHERE id=?').run(id);
  await unlink(path.join(f.dir,'metadata.json'));await assert.rejects(f.verify(),/RETENTION_RETAINED_FILE_MISSING/);assert.equal(f.events().length,0);
});

test('final synchronous policy and shutdown guards run after filesystem awaits',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();
  await assert.rejects(f.verify({policy:()=>({...f.current,discord:{...f.current.discord,operators:[]}})}),/RETENTION_OWNER_REQUIRED/);
  let checks=0;await assert.rejects(f.verify({assertActive:()=>{if(++checks===3)throw new Error('RUNTIME_STOPPING');}}),/RUNTIME_STOPPING/);assert.equal(f.events().length,0);
});

test('current owner revocation, archive policy change and source mutation cannot record evidence',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();let reads=0;
  await assert.rejects(f.verify({readConfig:async()=>{if(++reads===2)f.current.discord.operators=[];return f.current;}}),/RETENTION_OWNER_REQUIRED/);
  f.current=structuredClone(f.config);f.current.archive.retentionPolicyRef='ref/policy/changed';await assert.rejects(f.verify(),/RETENTION_POLICY_CHANGED/);
  f.current=structuredClone(f.config);const ir=JSON.parse(f.adapter.session(f.binding.sessionId).intent_receipt),s=f.store.sourceInternal(ir.sourceKey);
  f.store.ingest({...s,revision:s.revision+1,text:'changed'});await assert.rejects(f.verify(),/RETENTION_SOURCE_CHANGED/);assert.equal(f.events().length,0);
});

test('hardlinks, subdirectories and network paths are refused',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();await mkdir(path.join(f.dir,'extra'));await assert.rejects(f.verify(),/RETENTION_REGULAR_FILE_REQUIRED/);
  assert(inside(f.root,path.join(f.dir,'extra')));await rm(path.join(f.dir,'extra'),{recursive:true});
  const target=path.join(f.dir,'metadata.json');await link(target,path.join(f.root,'alias'));await assert.rejects(f.verify(),/RETENTION_REGULAR_FILE_REQUIRED/);
  for(const value of ['//invalid.example/archive','\\\\invalid.example\\archive'])await assert.rejects(retentionLocalPath(value),/RETENTION_LOCAL_PATH_REQUIRED/);
});

test('symbolic ancestor and input file are refused',{skip:process.platform==='win32'?'Requires Windows symlink privilege; Linux CI covers it.':false},async t=>{
  const f=await fixture(t);const alias=path.join(f.root,'linked');await symlink(f.dir,alias);await assert.rejects(readRetentionInput(path.join(alias,'metadata.json')),/RETENTION_LINK_REFUSED/);
});

test('Windows case aliases bind the same checked canonical archive directory',{skip:process.platform!=='win32'},async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();f.config.archive.archiveRoot=f.config.archive.archiveRoot.toUpperCase();f.current=structuredClone(f.config);
  assert.equal((await f.verify()).evidence,'LOCAL_READBACK_ONLY');
});

test('same receipt ref with changed receipt content conflicts after a fresh successful readback',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();await f.verify();f.receipt.deleted_at=new Date(f.now-20).toISOString();await assert.rejects(f.verify(),/RETENTION_RECEIPT_CONFLICT/);assert.equal(f.events().length,1);
});

test('official CLI sends bounded owner inputs to the existing runtime control writer',async t=>{
  const f=await fixture(t);await f.deleteFixtureAudio();
  // Use real wall time in the command path, never a caller-supplied test clock.
  f.receipt.trigger='withdrawal';f.receipt.deleted_at=new Date().toISOString();f.receipt.readback.checked_at=f.receipt.deleted_at;f.receipt.deadline.delete_by=new Date(Date.now()+60000).toISOString();f.scope.delete_by=f.receipt.deadline.delete_by;
  const configFile=path.join(f.root,'config.json'),receiptFile=path.join(f.root,'receipt.json'),scopeFile=path.join(f.root,'scope.json');
  await atomicJson(configFile,f.config);await atomicJson(receiptFile,f.receipt);await atomicJson(scopeFile,f.scope);
  const runtime=await startRuntime(configFile,{offline:true,log:()=>{}});
  try{
    const result=await runCommand(process.execPath,['bin/kotodama.mjs','verify-deletion','--config',configFile,'--actor',f.actor,'--file',receiptFile,'--scope',scopeFile,'--json'],{cwd:fileURLToPath(new URL('..',import.meta.url)),timeoutMs:30000});
    assert.equal(result.code,0,result.stderr+result.stdout);assert.equal(JSON.parse(result.stdout).evidence,'LOCAL_READBACK_ONLY');assert.equal(f.events().length,1);
    await assert.rejects(controlCommand(f.config,{action:'verify-deletion',actor:'100000000000000099',receipt:f.receipt,scope:f.scope}),/OPERATOR_REQUIRED/);
  }finally{await runtime.close();}
});
