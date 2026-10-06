import path from 'node:path';
import {lstat,opendir,realpath} from 'node:fs/promises';
import {DatabaseSync} from 'node:sqlite';
import {check,digest,inside} from './common.mjs';
import {readArtifact} from './worker.mjs';
import {parseReceiptJson,validateRetentionReceipt} from './retention-receipt.mjs';

const MAX_JSON=8*1024*1024;
const retained=['RAW_ASR','CORRECTED_TRANSCRIPT','SOURCE_EVIDENCE'];
const same=(a,b)=>digest(a)===digest(b);
const identity=s=>[s.dev,s.ino,s.birthtimeMs];
const json=bytes=>parseReceiptJson(bytes,MAX_JSON);

// Reject network paths before any filesystem probe. Check every ancestor;
// readArtifact pins each regular file and rejects hard links/changed bytes.
export async function retentionLocalPath(value,{directory=false}={}){
  check(typeof value==='string'&&path.isAbsolute(value)&&!value.includes('\0')&&!/^[\\/]{2}/.test(value),'RETENTION_LOCAL_PATH_REQUIRED');
  const absolute=path.resolve(value),root=path.parse(absolute).root;let current=root,info=await lstat(root);
  check(info.isDirectory()&&!info.isSymbolicLink(),'RETENTION_LINK_REFUSED');
  const parts=path.relative(root,absolute).split(path.sep).filter(Boolean);
  for(let i=0;i<parts.length;i++){
    current=path.join(current,parts[i]);info=await lstat(current);
    check(!info.isSymbolicLink(),'RETENTION_LINK_REFUSED');
    if(i<parts.length-1||directory)check(info.isDirectory(),'RETENTION_DIRECTORY_REQUIRED');
    else check(info.isFile()&&info.nlink===1,'RETENTION_REGULAR_FILE_REQUIRED');
  }
  // The archive sink stores realpath (including Windows 8.3/case expansion).
  // Canonicalize only after ancestor checks, then pin the same file identity.
  const resolved=await realpath(absolute),canonical=await lstat(resolved);
  check(same(identity(info),identity(canonical))&&!canonical.isSymbolicLink(),'RETENTION_PATH_CHANGED');
  return {path:resolved,identity:identity(canonical)};
}

export async function readRetentionInput(filename,maxBytes=256*1024){
  const checked=await retentionLocalPath(filename);return parseReceiptJson(await readArtifact(checked.path,maxBytes),maxBytes);
}

function scopeBinding(scope,receipt){
  check(scope&&typeof scope==='object'&&!Array.isArray(scope),'RETENTION_SCOPE_REQUIRED');
  const keys=['archive_session_id','archive_policy_ref','session_ref','policy_ref','policy_revision_ref','archive_binding_digest','delete_by'];
  check(Object.keys(scope).length===keys.length&&keys.every(k=>typeof scope[k]==='string'&&scope[k].length>0&&scope[k].length<=1000),'RETENTION_SCOPE_INVALID');
  check(/^session-[A-Za-z0-9_-]{1,88}$/.test(scope.archive_session_id),'RETENTION_SESSION_INVALID');
  for(const k of ['session_ref','policy_ref','policy_revision_ref','archive_binding_digest'])check(scope[k]===receipt[k],'RETENTION_SCOPE_MISMATCH');
  check(scope.delete_by===receipt.deadline.delete_by,'RETENTION_DEADLINE_MISMATCH');
}

/** Check current local absence and record evidence. Never deletes or promotes a ledger. */
export async function recordRetentionReadback({receipt,scope,actor,config,store,readConfig,policy:readPolicy,assertActive=()=>{},clock=Date.now}){
  validateRetentionReceipt(receipt,{now:clock()});scopeBinding(scope,receipt);
  check(typeof readConfig==='function'&&typeof readPolicy==='function'&&typeof actor==='string','RETENTION_OWNER_REQUIRED');
  const a=config.archive;
  const policy=p=>{
    assertActive();check(p.owner?.kind==='local'&&p.discord.operators.includes(actor)&&actor===p.archive?.actorId,'RETENTION_OWNER_REQUIRED');
    check(a&&same(p.archive,a)&&p.dataDir===config.dataDir&&a.retentionPolicyRef===scope.archive_policy_ref,'RETENTION_POLICY_CHANGED');
    check(p.installation===config.installation&&same(p.agentBinding,config.agentBinding)&&p.discord.guildId===config.discord.guildId&&p.discord.voiceChannelId===config.discord.voiceChannelId,'RETENTION_INSTALLATION_CHANGED');
  };
  policy(await readConfig());
  const root=await retentionLocalPath(a.archiveRoot,{directory:true});
  check(inside(config.dataDir,a.journalPath),'RETENTION_JOURNAL_SCOPE');
  const journal=await retentionLocalPath(a.journalPath);
  const dir=await retentionLocalPath(path.join(root.path,scope.archive_session_id),{directory:true});
  const db=new DatabaseSync(journal.path,{readOnly:true});
  try{
    db.exec('PRAGMA query_only=ON; PRAGMA busy_timeout=1000;');
    const readRow=()=>db.prepare('SELECT * FROM archive_sessions WHERE id=?').get(scope.archive_session_id);
    const row=readRow();check(row&&row.state==='done','RETENTION_ARCHIVE_NOT_COMPLETE');
    const b=json(Buffer.from(row.binding)),saved=json(Buffer.from(row.receipt??'null'));
    check(saved&&b.sessionId===scope.archive_session_id&&saved.sessionId===b.sessionId&&saved.bindingDigest===digest(b)&&receipt.archive_binding_digest===digest(b)&&saved.archiveRef===dir.path,'RETENTION_ARCHIVE_BINDING');
    check(b.retentionPolicyRef===a.retentionPolicyRef&&b.sourceRef===a.sourceRef&&b.actorId===actor&&b.installation===config.installation&&b.agentId===config.agentBinding?.agentId&&b.vmId===config.agentBinding?.vmId&&b.guildId===config.discord.guildId&&b.channelId===config.discord.voiceChannelId,'RETENTION_ARCHIVE_BINDING');
    check(b.sampleRateHz===48000&&Number.isSafeInteger(b.startedAtMs)&&Number.isSafeInteger(row.end_frame)&&row.end_frame>0,'RETENTION_ARCHIVE_BINDING');
    check(Array.isArray(b.speakerIds)&&b.speakerIds.length>0&&b.speakerIds.length<=32&&new Set(b.speakerIds).size===b.speakerIds.length&&b.speakerIds.every(id=>/^[A-Za-z0-9_-]{1,96}$/.test(id)&&id!=='mixed'),'RETENTION_ARCHIVE_BINDING');
    const names=['mixed',...b.speakerIds].flatMap(id=>[id+'.pcm',id+'.mp3']);
    check(Array.isArray(saved.files)&&saved.files.length===names.length&&new Set(saved.files.map(f=>f.ref)).size===names.length,'RETENTION_MANIFEST_INVALID');
    for(const f of saved.files)check(names.includes(f.ref)&&Object.keys(f).sort().join(',')==='ref,sha256,size'&&Number.isSafeInteger(f.size)&&f.size>0&&/^[a-f0-9]{64}$/.test(f.sha256),'RETENTION_MANIFEST_INVALID');
    check(receipt.artifacts.length===2&&same([...receipt.retained_by_policy].sort(),[...retained].sort()),'RETENTION_POLICY_UNSUPPORTED');
    for(const [kind,ext]of [['RAW_AUDIO_PCM','.pcm'],['RAW_AUDIO_ENCODED','.mp3']]){
      const group=receipt.artifacts.find(item=>item.kind===kind),files=saved.files.filter(f=>f.ref.endsWith(ext));
      const expected=files.map(f=>[digest(f),f.sha256]).sort();
      const actual=group?.manifest_entry_sha256.map((hash,i)=>[hash,group.pre_delete_sha256[i]]).sort();
      check(group&&group.count===files.length&&same(actual,expected),'RETENTION_MANIFEST_MISMATCH');
    }
    const ended=Date.parse(new Date(b.startedAtMs+row.end_frame/48).toISOString()),retainUntil=ended+30*86400000;
    check(Date.parse(receipt.deadline.retain_until)===retainUntil,'RETENTION_POLICY_DEADLINE');
    const raw=json(Buffer.from(row.raw??'null')),corrected=json(Buffer.from(row.corrected??'null')),intent=json(Buffer.from(row.intent_receipt??'null'));
    check(raw&&Array.isArray(raw.individual)&&Array.isArray(raw.mixed)&&Array.isArray(corrected)&&intent?.sourceKey,'RETENTION_TEXT_BASELINE_MISSING');
    const transcript=Buffer.from(JSON.stringify({sessionId:b.sessionId,status:'succeeded',individual:raw.individual,mixed:raw.mixed,...(raw.mixedDerivedFromIndividual?{mixedDerivedFromIndividual:true}:{})},null,2)+'\n');
    const expectedText=new Map([['transcript.json',transcript],['knowledge-source-transcript-'+digest(transcript)+'.json',transcript],['fused.json',Buffer.from(JSON.stringify({sessionId:b.sessionId,segments:corrected},null,2)+'\n')]]);
    function assertBaseline(){
      check(same(readRow(),row),'RETENTION_JOURNAL_CHANGED');
      check(db.prepare('SELECT count(*) AS n FROM archive_frames WHERE session=?').get(b.sessionId).n===0,'RETENTION_RESIDUAL_AUDIO');
      const source=store.sourceInternal(intent.sourceKey);
      check(source?.metadata?.sessionId===b.sessionId&&source.metadata.rawDigest===digest(transcript)&&source.metadata.correctionDigest===digest(corrected)&&source.text===corrected.map(s=>`[${s.start}-${s.end}] ${s.speaker_id}: ${s.text}`).join('\n'),'RETENTION_SOURCE_CHANGED');
    }
    async function readback(){
      const currentRoot=await retentionLocalPath(root.path,{directory:true}),currentDir=await retentionLocalPath(dir.path,{directory:true}),currentJournal=await retentionLocalPath(journal.path);
      check(same(root.identity,currentRoot.identity)&&same(dir.identity,currentDir.identity)&&same(journal.identity,currentJournal.identity),'RETENTION_PATH_CHANGED');
      assertBaseline();
      const found=new Set();let markers=0;
      const handle=await opendir(dir.path);
      for await(const entry of handle){
        check(found.size<128,'RETENTION_DIRECTORY_LIMIT');found.add(entry.name);
        check(!names.includes(entry.name),'RETENTION_RESIDUAL_AUDIO');
        const target=await retentionLocalPath(path.join(dir.path,entry.name));
        const bytes=await readArtifact(target.path,MAX_JSON);
        if(expectedText.has(entry.name)){check(bytes.equals(expectedText.get(entry.name)),'RETENTION_TEXT_CHANGED');continue;}
        const value=json(bytes);
        if(entry.name==='archive-receipt.json')check(same(value,saved),'RETENTION_MANIFEST_CHANGED');
        else if(entry.name==='archive-intent-receipt.json')check(same(value,intent),'RETENTION_INTENT_CHANGED');
        else if(entry.name==='metadata.json'){
          check(Array.isArray(value.sourceChunks)&&value.sourceChunks.length<=10000&&value.sourceChunks.every(c=>Object.keys(c).sort().join(',')==='frames,sha256,sourceId,speakerId,startFrame'&&typeof c.sourceId==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(c.sourceId)&&b.speakerIds.includes(c.speakerId)&&Number.isSafeInteger(c.startFrame)&&c.startFrame>=0&&Number.isSafeInteger(c.frames)&&c.frames>0&&c.startFrame+c.frames<=row.end_frame&&/^[a-f0-9]{64}$/.test(c.sha256)),'RETENTION_METADATA_CHANGED');
          check(same(value,{sessionId:b.sessionId,guildId:b.guildId,channelId:b.channelId,channelName:b.channelName??b.channelId,startedAt:new Date(b.startedAtMs).toISOString(),endedAt:new Date(ended).toISOString(),participants:b.speakerIds.map(userId=>({userId,name:userId,joinedAt:new Date(b.startedAtMs).toISOString()})),rotationIntervalSeconds:row.end_frame/48000,timeline:{alignment:'session_start_silence_padded',sampleRateHz:48000,source:'per_speaker_and_mixed'},sourceRef:b.sourceRef,retention:{schemaVersion:'kotodama.voice-retention/v2',rawAudioDays:30,transcriptDays:null,derivedTextDays:null,policyRef:b.retentionPolicyRef},sourceChunks:value.sourceChunks}),'RETENTION_POLICY_CHANGED');
        }
        else if(entry.name==='speakers.json')check(same(value,Object.fromEntries(['mixed',...b.speakerIds].map((id,i)=>['file'+i,{id}]))),'RETENTION_SPEAKERS_CHANGED');
        // The private owner's marker name is deliberately not part of this contract.
        else{check(++markers===1&&Object.keys(value).sort().join(',')==='artifact_manifest,authorityGranted,schemaVersion'&&value.schemaVersion==='kotodama.archive-retention-manifest/v1'&&value.authorityGranted===false&&same(value.artifact_manifest,saved.files),'RETENTION_UNKNOWN_RESIDUAL');}
      }
      for(const name of [...expectedText.keys(),'archive-receipt.json','archive-intent-receipt.json','metadata.json','speakers.json'])check(found.has(name),'RETENTION_RETAINED_FILE_MISSING');
      check(markers===1,'RETENTION_MANIFEST_MISSING');
    }
    await readback();policy(await readConfig());await readback();
    // Policy polling and shutdown may revoke access across any of the awaits.
    policy(readPolicy());assertBaseline();const now=clock();
    validateRetentionReceipt(receipt,{now});check(now<=Date.parse(receipt.deadline.delete_by),'RETENTION_LIVE_DEADLINE_EXCEEDED');
    const receiptDigest=digest(receipt),scopeDigest=digest(scope);
    return store.transaction(()=>{
      const prior=store.statement("SELECT body FROM events WHERE type='retention.deletion_readback' AND json_extract(body,'$.receipt_ref')=? LIMIT 1").get(receipt.receipt_ref);
      if(prior){const value=JSON.parse(prior.body);check(value.receipt_sha256===receiptDigest&&value.scope_sha256===scopeDigest,'RETENTION_RECEIPT_CONFLICT');return {...value,duplicate:true,current_checked_at:new Date(now).toISOString()};}
      const result={receipt_ref:receipt.receipt_ref,session_ref:receipt.session_ref,receipt_sha256:receiptDigest,scope_sha256:scopeDigest,archive_binding_digest:digest(b),artifacts:receipt.artifacts.map(({kind,count})=>({kind,count})),retained_by_policy:receipt.retained_by_policy,checked_at:new Date(now).toISOString(),residual_count:0,evidence:'LOCAL_READBACK_ONLY',receipt_authenticity:'UNVERIFIED',authority_granted:false,gate_closed:false,public_beta_go:false,contains_content:false};
      store.event('retention.deletion_readback',result);return {...result,duplicate:false};
    });
  }finally{db.close();}
}
