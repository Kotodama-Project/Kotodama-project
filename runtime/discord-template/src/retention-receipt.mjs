import {readFileSync} from 'node:fs';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import {check} from './common.mjs';

const schema=JSON.parse(readFileSync(new URL('./retention-deletion-receipt.schema.json',import.meta.url),'utf8'));
// Canonical ledger definitions inherit string types through allOf/not. Ajv's
// optional strictTypes lint cannot infer that inheritance; schema constraints
// and all other strict compilation checks remain enabled.
const ajv=new Ajv2020({strict:true,strictTypes:false,allErrors:false});addFormats(ajv);
const shape=ajv.compile(schema);
export const RECEIPT_BYTES=256*1024;

// JSON.parse discards duplicate keys. Scan containers/keys first, then let the
// standard decoder validate syntax and escapes. No schema or JSON network reads.
export function parseReceiptJson(bytes,maxBytes=RECEIPT_BYTES){
  check(Buffer.isBuffer(bytes)&&bytes.length<=maxBytes,'RETENTION_INPUT_LIMIT');
  let text;
  try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{check(false,'RETENTION_JSON_INVALID');}
  const stack=[];
  for(const match of text.matchAll(/"(?:\\[\s\S]|[^"\\])*"|[{}\[\],]/g)){
    const token=match[0],top=stack.at(-1);
    if(token==='{'||token==='['){stack.push({object:token==='{',keys:new Set(),key:true});check(stack.length<=32,'RETENTION_JSON_DEPTH');}
    else if(token==='}'||token===']')stack.pop();
    else if(token===','&&top?.object)top.key=true;
    else if(token.startsWith('"')&&top?.object&&top.key){
      let key;try{key=JSON.parse(token);}catch{check(false,'RETENTION_JSON_INVALID');}
      check(!top.keys.has(key),'RETENTION_JSON_DUPLICATE');top.keys.add(key);top.key=false;
    }
  }
  try{return JSON.parse(text);}catch{check(false,'RETENTION_JSON_INVALID');}
}

export function validateRetentionReceipt(value,{now=Date.now()}={}){
  check(shape(value),'RETENTION_SCHEMA_INVALID');check(Number.isFinite(now),'RETENTION_CLOCK_INVALID');
  const kinds=new Set(),entries=new Set();let count=0;
  for(const artifact of value.artifacts){
    check(!kinds.has(artifact.kind),'RETENTION_DUPLICATE_KIND');kinds.add(artifact.kind);
    check(artifact.count===artifact.pre_delete_sha256.length&&artifact.count===artifact.manifest_entry_sha256.length,'RETENTION_COUNT_MISMATCH');
    count+=artifact.count;
    for(const hash of artifact.manifest_entry_sha256){check(!entries.has(hash),'RETENTION_DUPLICATE_ENTRY');entries.add(hash);}
  }
  check(count<=1024,'RETENTION_ARTIFACT_LIMIT');
  check(value.retained_by_policy.every(kind=>!kinds.has(kind)),'RETENTION_RETAINED_AND_DELETED');
  const retain=Date.parse(value.deadline.retain_until),deadline=Date.parse(value.deadline.delete_by),deleted=Date.parse(value.deleted_at),checked=Date.parse(value.readback.checked_at);
  check([retain,deadline,deleted,checked].every(Number.isFinite),'RETENTION_CLOCK_INVALID');
  if(value.trigger==='expiry'){check(deadline>=retain,'RETENTION_DEADLINE_ORDER');check(deleted>=retain,'RETENTION_EARLY_DELETION');}
  check(deleted<=deadline&&checked<=deadline,'RETENTION_DEADLINE_EXCEEDED');
  check(checked>=deleted,'RETENTION_READBACK_BEFORE_DELETE');check(deleted<=now&&checked<=now,'RETENTION_FUTURE_RECEIPT');
  return value;
}
