import test from 'node:test';
import assert from 'node:assert/strict';
import {parseReceiptJson,validateRetentionReceipt} from '../src/retention-receipt.mjs';

export const example=()=>({kind:'kotodama.retention-deletion-receipt',schema_revision:'v1',receipt_ref:'ref/deletion-receipt/synthetic',session_ref:'ref/session/synthetic',archive_binding_digest:'a'.repeat(64),policy_ref:'ref/policy/synthetic',policy_revision_ref:'ref/policy-revision/synthetic',trigger:'expiry',deadline:{retain_until:'2026-09-01T00:00:00Z',delete_by:'2026-09-02T00:00:00Z'},deleted_at:'2026-09-01T01:00:00Z',artifacts:[{kind:'RAW_AUDIO_PCM',count:2,pre_delete_sha256:['b'.repeat(64),'b'.repeat(64)],manifest_entry_sha256:['c'.repeat(64),'d'.repeat(64)]}],retained_by_policy:['RAW_ASR','CORRECTED_TRANSCRIPT','SOURCE_EVIDENCE'],readback:{status:'CONFIRMED',residual_count:0,checked_at:'2026-09-01T01:00:01Z'},authority_granted:false,gate_closed:false,public_beta_go:false,contains_content:false,receipt_authenticity:'UNVERIFIED'});
const now=Date.parse('2026-10-07T00:00:00Z');

test('content equality does not double-count a distinct manifest entry',()=>{
  const value=example();assert.equal(validateRetentionReceipt(value,{now}),value);
  value.artifacts[0].manifest_entry_sha256[1]=value.artifacts[0].manifest_entry_sha256[0];
  assert.throws(()=>validateRetentionReceipt(value,{now}),/RETENTION_SCHEMA_INVALID/);
});

test('strict JSON rejects duplicate escaped keys, unsafe depth and invalid UTF-8 before use',()=>{
  for(const text of ['{"a":1,"a":2}','{"a":1,"\\u0061":2}','{"a":{"b":1,"b":2}}','['.repeat(33)+'0'+']'.repeat(33),'{bad}'])assert.throws(()=>parseReceiptJson(Buffer.from(text)),/RETENTION_JSON_/);
  assert.throws(()=>parseReceiptJson(Buffer.from([255])),/RETENTION_JSON_INVALID/);
  assert.throws(()=>parseReceiptJson(Buffer.alloc(262145)),/RETENTION_INPUT_LIMIT/);
  const value={text:'[{'.repeat(1000)+'\\" ]}',nested:[{a:1},{a:2}]};
  assert.deepEqual(parseReceiptJson(Buffer.from(JSON.stringify(value))),value);
});

test('schema and chronology forbid overclaims, private fields, residue, date drift and count mismatches',()=>{
  const changes=[v=>v.authority_granted=true,v=>v.private_body='SYNTHETIC_PRIVATE',v=>v.readback.residual_count=1,v=>delete v.readback,
    v=>v.artifacts[0].count=1,v=>v.retained_by_policy.push('RAW_AUDIO_PCM'),v=>v.deleted_at='2026-08-31T00:00:00Z',
    v=>v.deleted_at='2026-09-03T00:00:00Z',v=>v.readback.checked_at='2026-09-01T00:00:00Z',v=>v.readback.checked_at='2026-10-08T00:00:00Z',
    v=>v.deadline.retain_until='2026-02-30T00:00:00Z',v=>v.session_ref='ref/session/100000000000000001'];
  for(const change of changes){const value=example();change(value);assert.throws(()=>validateRetentionReceipt(value,{now}),/RETENTION_/);}
});

test('withdrawal is allowed before the original retain-until but never creates authority',()=>{
  const value=example();value.trigger='withdrawal';value.deadline.retain_until='2026-10-01T00:00:00Z';
  assert.equal(validateRetentionReceipt(value,{now}).authority_granted,false);
});
