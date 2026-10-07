import {canonical,check,digest,uid} from './common.mjs';
import {ledgerKeys,writeLedgerPackage} from './ledger-package.mjs';

const TASK_EVENTS=new Set(['task.created','task.started','task.corrected','task.context_bound','task.result','task.stop_requested','task.stop_observed','task.admission_cancelled','task.resumed','task.recovery_required']);
const MAX_EVENTS=10000,MAX_BYTES=32*1024*1024;
function validateScope(scope,now){
  const fields=['mappingKeyEnv','policyId','policyRevision','retainUntil','consentBasis','knowledgeScope'];
  check(scope&&canonical(Object.keys(scope).sort())===canonical(fields.sort()),'LEDGER_SCOPE_INVALID');
  check(fields.every(k=>typeof scope[k]==='string'&&scope[k].length>0&&scope[k].length<=256),'LEDGER_SCOPE_INVALID');
  check(/^[A-Z_][A-Z0-9_]*$/.test(scope.mappingKeyEnv)&&/^\d{4}-\d{2}-\d{2}T.*Z$/.test(scope.retainUntil)&&Date.parse(scope.retainUntil)>now,'LEDGER_SCOPE_EXPIRED_OR_INVALID');
}
function snapshot(store,actor){
  const budget=store.statement('SELECT count(*) AS count,coalesce(sum(length(CAST(body AS BLOB))),0) AS bytes FROM events').get();
  check(budget.count<=MAX_EVENTS,'LEDGER_EVENT_LIMIT');check(budget.bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');
  const rows=store.statement('SELECT seq,type,task_id,at,body FROM events ORDER BY seq LIMIT ?').all(MAX_EVENTS+1);
  check(rows.length<=MAX_EVENTS,'LEDGER_EVENT_LIMIT');let bytes=0,omitted=0;const items=[];
  const sourceCache=new Map(),taskCache=new Map();
  const current=key=>{if(!sourceCache.has(key)){const size=store.statement('SELECT length(CAST(body AS BLOB)) AS bytes FROM sources WHERE key=?').get(key);bytes+=size?.bytes??0;check(bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');sourceCache.set(key,store.sourceInternal(key));}return sourceCache.get(key);};
  const readable=s=>s?.provider==='discord'&&!s.withdrawn&&s.readers?.includes(actor);
  for(const row of rows){
    bytes+=Buffer.byteLength(row.body);check(bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');const body=JSON.parse(row.body);
    if(['source.created','source.corrected'].includes(row.type)){
      if(!readable(current(body.source_key))){omitted++;continue;}
      const size=store.statement('SELECT length(CAST(body AS BLOB)) AS bytes FROM source_versions WHERE key=? AND revision=?').get(body.source_key,body.revision);
      check(size,'LEDGER_SOURCE_HISTORY_MISSING');check(bytes+size.bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');
      const saved=store.statement('SELECT body FROM source_versions WHERE key=? AND revision=?').get(body.source_key,body.revision);
      check(saved,'LEDGER_SOURCE_HISTORY_MISSING');bytes+=Buffer.byteLength(saved.body);check(bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');
      const source=JSON.parse(saved.body);if(!readable(source)){omitted++;continue;}
      // A missing actor/track is not replaced with an invented human identity.
      if(!source.actorId||(source.metadata?.kind==='voice'&&!source.metadata?.inputAccountId)){omitted++;continue;}
      items.push({row,body,source,payload:{store_event:row,source}});
    }else if(TASK_EVENTS.has(row.type)&&row.task_id){
      if(!taskCache.has(row.task_id)){const size=store.statement('SELECT length(CAST(body AS BLOB)) AS bytes FROM tasks WHERE id=?').get(row.task_id);bytes+=size?.bytes??0;check(bytes<=MAX_BYTES,'LEDGER_SNAPSHOT_LIMIT');taskCache.set(row.task_id,store.taskInternal(row.task_id));}const task=taskCache.get(row.task_id);
      if(!task||task.actor!==actor||!readable(current(task.source_key))){omitted++;continue;}
      const references=[body.source_key,body.source,body.previousSource,...(body.bindings??[]).map(b=>b.key),...(task.contextSources??[]).map(b=>b.key)].filter(Boolean);
      if(references.some(key=>!readable(current(key)))){omitted++;continue;}
      items.push({row,body,source:null,payload:{store_event:row}});
    }else omitted++;
  }
  check(items.length,'LEDGER_NO_EXPORTABLE_EVENTS');return {items,omitted,total:rows.length};
}
function render(snapshot,keys,scope,installation,actor){
  const ref=(kind,value)=>keys.opaque(kind,[installation,value]);
  const rows=[],entries=[],sourceEvents=new Map(),taskEvents=new Map();let previous='0'.repeat(64);
  const scopeRef=ref('knowledge-scope',scope.knowledgeScope);
  for(const item of snapshot.items){
    const {row,source,body,payload}=item,reference=ref('event',[row.seq,digest(payload)]);
    const voice=source?.metadata?.kind==='voice',old=source?sourceEvents.get(source.key):taskEvents.get(row.task_id);
    const correcting=row.type==='source.corrected';check(!correcting||old,'LEDGER_CORRECTION_PARENT_MISSING');
    const caused=[old,source?null:sourceEvents.get(body.source_key??body.source)].filter(Boolean);
    const vaultRef=ref('vault',reference),manifestRef=ref('vault-manifest',reference),cursorRef=ref('cursor',row.seq),recoveryRef=ref('recovery-receipt',reference);
    const record={kind:'kotodama.conversation-event',schema_revision:'v1',event_id:reference,sequence:rows.length+1,
      session:{state:'UNASSIGNED_INBOX',session_ref:null,revision_ref:null,binding_event_ref:null,governance:{creation_mode:'UNASSIGNED_INBOX',task_ssot_ref:null,plan_ref:null,requirement_refs:[],invocation_ref:null,model_ref:null,capability_grant_refs:[],knowledge_grant_refs:[],mcp_tool_grant_refs:[],delegation_ref:null,dependency_refs:[],parallel_status_ref:null,evidence_refs:[],invalidation_refs:[]}},
      source:{type:source?(voice?'discord_voice':'discord_text'):'system',occurred_at:row.at,ingested_at:row.at,
        locator_ref:ref('source',source?.key??['event',row.seq]),source_revision_ref:ref('source-revision',source?[source.key,source.revision]:row.seq),
        actor_ref:ref(source?'actor':'system',source?.actorId??'runtime'),identity_verification:source?'UNVERIFIED_PUBLIC_CLAIM':'NOT_APPLICABLE',
        speaker_track_ref:voice?ref('track',[source.metadata.sessionId??source.sourceId,source.metadata.inputAccountId]):null,
        authority:{role:source?'HUMAN':'SYSTEM',authority_ref:ref('authority',source?.actorId??'runtime')},thread_ref:null,channel_ref:source?ref('channel',[source.guildId,source.channelId]):null,document_ref:null,repository_ref:null,evidence_ref:ref('evidence',reference),consent_ref:source?ref('consent',scope.consentBasis):null},
      content:{payload_vault_ref:vaultRef,vault_manifest_ref:manifestRef,content_hash:digest(payload),span_ref:null,storage:'PROTECTED_PAYLOAD_VAULT',raw_content_embedded:false,artifact_stage:'RAW_SOURCE_JSON',derived_from_event_refs:[]},
      causation:{caused_by_event_refs:[...new Set(caused)],correlation_ref:ref('correlation',source?['source',source.key]:['task',row.task_id]),idempotency_key_ref:ref('idempotency',reference),cursor_ref:cursorRef,replay_of_event_ref:null},
      context:{background_ref:null,knowledge_scope_ref:scopeRef,context_pack_refs:[],omission_refs:[]},ownership:{owner_ref:ref('owner',actor),assignee_ref:null},
      event:{kind:correcting?'source_update':source?(voice?'voice_segment':'human_message'):'agent_action',state:'OBSERVED',summary_ref:ref('summary',reference),correction_of_event_ref:null,withdrawal_of_event_ref:null,confirmation_of_event_ref:null,invalidation_kind:correcting?'SOURCE_UPDATED':null,invalidation_refs:correcting?[old]:[],binding:{target_event_refs:[],destination_session_ref:null,destination_revision_ref:null}},
      decision:{status:'NONE',candidate_ref:null,human_evidence_ref:null,human_decision_ref:null,human_actor_ref:null,current_truth_ref:null,execution_authority_granted:false},
      policy_deviation:{status:'NONE',rule_ref:null,reason_ref:null,approver_ref:null,expires_at:null,remediation_ref:null},
      retention:{policy_ref:ref('retention-policy',scope.policyId),policy_revision_ref:ref('retention-policy-revision',scope.policyRevision),storage_class:'PROTECTED_HOT',encryption_ref:ref('encryption','aes-256-gcm-v1'),encryption_status:'DECLARED_UNVERIFIED',retain_until:scope.retainUntil,archive_target_kind:'NONE',archive_target_ref:null,archive_target_uri_ref:null,archive_package_digest:null,snapshot_receipt_ref:null,archive_status:'NOT_REQUESTED',archive_receipt_ref:null,restore_status:'NOT_REQUESTED',restore_receipt_ref:null,deletion_trigger:'expiry_or_withdrawal',deletion_state:'NOT_REQUESTED',deletion_receipt_ref:null,deletion_readback:'NOT_REQUESTED'},
      provenance:{adapter_contract_ref:ref('adapter','discord-store-v1'),ingested_by_ref:ref('ingester','ledger-export-v1'),ingest_mode:'OFFLINE_RECOVERY',connector_ref:ref('connector',installation),extraction:{kind:'NONE',candidate_binding:'NOT_APPLICABLE',model_ref:null,confirmation_required:true},recovery:{status:'RECOVERED',cursor_ref:cursorRef,receipt_ref:recoveryRef}},
      public_safety:{record_visibility:'PUBLIC_SANITIZED_METADATA',raw_payload_embedded:false,protected_payload_ref:vaultRef,knowledge_scope_ref:scopeRef,acl_state:'AVAILABLE'},integrity:{marker:'NONE',marker_ref:null},previous_event_hash:previous};
    record.event_hash=digest(record);previous=record.event_hash;rows.push(record);
    entries.push({event_ref:reference,vault_ref:vaultRef,manifest_ref:manifestRef,summary_ref:record.event.summary_ref,summary:{store_event_type:row.type,observed_at:row.at},recovery:{receipt_ref:recoveryRef,cursor_ref:cursorRef,store_sequence:row.seq,payload_sha256:digest(payload)},payload});
    if(source)sourceEvents.set(source.key,reference);else taskEvents.set(row.task_id,reference);
  }
  return {ledger:rows.map(canonical).join('\n')+'\n',payload:{version:1,scope,entries,recovery:{total_events:snapshot.total,omitted_events:snapshot.omitted,exported_events:rows.length}}};
}
export function exportLedger(store,{config,actor,scope,output,env=process.env,now=Date.now()}){
  check(config.owner.kind==='local','LEDGER_LOCAL_OWNER_REQUIRED');check(config.discord.operators.includes(actor),'OPERATOR_REQUIRED');
  validateScope(scope,now);const keys=ledgerKeys(env[scope.mappingKeyEnv]),lockOwner=uid('ledger-export');
  let claimed=false;
  try{
    const data=store.transaction(()=>{check(!store.lock(),'STOP_RUNTIME_BEFORE_MAINTENANCE');store.claimHost(lockOwner,process.pid,new Date(now).toISOString(),'ledger-export');claimed=true;return snapshot(store,actor);});
    const rendered=render(data,keys,scope,config.installation,actor),result=writeLedgerPackage(output,keys,rendered.ledger,rendered.payload);
    return {...result,omitted_events:data.omitted,scope:'authorized_local_snapshot',task_state_changed:false,retention_enforced:false,real_data_acceptance:false};
  }finally{if(claimed)store.releaseHost(lockOwner);}
}
