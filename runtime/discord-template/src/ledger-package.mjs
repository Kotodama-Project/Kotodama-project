import {createCipheriv,createDecipheriv,createHmac,hkdfSync,randomBytes} from 'node:crypto';
import {mkdirSync,writeFileSync,readSync,lstatSync,realpathSync,readdirSync,openSync,closeSync,fstatSync,constants} from 'node:fs';
import path from 'node:path';
import {canonical,check,digest} from './common.mjs';

const FILES=['ledger.jsonl','manifest.json','payload.aes256gcm'];
const MAX=64*1024*1024;
const identity=s=>[s.dev,s.ino,s.birthtimeMs];
export function ledgerKeys(hex){
  check(typeof hex==='string'&&/^[a-f0-9]{64}$/i.test(hex),'LEDGER_KEY_REQUIRED');
  const derive=label=>Buffer.from(hkdfSync('sha256',Buffer.from(hex,'hex'),'kotodama-ledger-v1',label,32));
  const mapping=derive('opaque-refs');
  const opaque=(kind,value)=>`ref/${kind}/${createHmac('sha256',mapping).update(canonical(value)).digest('hex').match(/.{8}/g).join('-')}`;
  return {encryption:derive('payload-encryption'),opaque};
}
function directory(filename){
  const absolute=path.resolve(filename);check(!/^[\\/]{2}/.test(absolute),'LEDGER_LOCAL_PATH_REQUIRED');
  let current=path.parse(absolute).root;
  for(const part of path.relative(current,absolute).split(path.sep).filter(Boolean)){
    current=path.join(current,part);const s=lstatSync(current);check(s.isDirectory()&&!s.isSymbolicLink(),'LEDGER_DIRECTORY_REFUSED');
  }
  const resolved=realpathSync(absolute),s=lstatSync(resolved);
  return {path:resolved,identity:identity(s)};
}
function pinnedRead(root,name){
  const filename=path.join(root,name);
  // Open first without following the final link or blocking on a substituted
  // special file; validate and bound the actual descriptor before reading.
  const fd=openSync(filename,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));
  try{
    const before=fstatSync(fd),namedBefore=lstatSync(filename);
    check(before.isFile()&&before.nlink===1&&before.size<=MAX&&!namedBefore.isSymbolicLink(),'LEDGER_FILE_REFUSED');
    check(canonical(identity(namedBefore))===canonical(identity(before)),'LEDGER_FILE_CHANGED');
    const buffer=Buffer.alloc(before.size+1);let length=0;
    while(length<buffer.length){const count=readSync(fd,buffer,length,buffer.length-length,null);if(!count)break;length+=count;}
    const bytes=buffer.subarray(0,length),after=fstatSync(fd),named=lstatSync(filename);
    check(bytes.length===before.size&&after.mtimeMs===before.mtimeMs&&after.ctimeMs===before.ctimeMs&&named.nlink===1&&!named.isSymbolicLink()&&canonical(identity(named))===canonical(identity(before)),'LEDGER_FILE_CHANGED');
    return bytes;
  }finally{closeSync(fd);}
}
// Returns private bytes in memory. There is deliberately no CLI that prints them.
export function readLedgerPackage(output,keys){
  const root=directory(output);check(canonical(readdirSync(root.path).sort())===canonical(FILES),'LEDGER_PACKAGE_FILES_INVALID');
  const manifest=JSON.parse(pinnedRead(root.path,'manifest.json'));
  check(canonical(Object.keys(manifest).sort())===canonical(['cipher_sha256','destination_binding','format','key_ref','ledger_sha256','nonce','tag']),'LEDGER_MANIFEST_INVALID');
  check(manifest.format==='kotodama-ledger-package-v1'&&manifest.destination_binding===keys.opaque('destination',root.path)&&manifest.key_ref===keys.opaque('key','v1'),'LEDGER_PACKAGE_BINDING_MISMATCH');
  const ledger=pinnedRead(root.path,'ledger.jsonl'),ciphertext=pinnedRead(root.path,'payload.aes256gcm');
  check(digest(ledger)===manifest.ledger_sha256&&digest(ciphertext)===manifest.cipher_sha256,'LEDGER_PACKAGE_TAMPERED');
  check(/^[a-f0-9]{24}$/.test(manifest.nonce)&&/^[a-f0-9]{32}$/.test(manifest.tag),'LEDGER_MANIFEST_INVALID');
  const aad={format:manifest.format,destination_binding:manifest.destination_binding,key_ref:manifest.key_ref,ledger_sha256:manifest.ledger_sha256};
  let payload;
  try{
    const decipher=createDecipheriv('aes-256-gcm',keys.encryption,Buffer.from(manifest.nonce,'hex'));
    decipher.setAAD(Buffer.from(canonical(aad)));decipher.setAuthTag(Buffer.from(manifest.tag,'hex'));
    payload=JSON.parse(Buffer.concat([decipher.update(ciphertext),decipher.final()]));
  }catch{check(false,'LEDGER_PACKAGE_DECRYPTION_REFUSED');}
  const rows=ledger.toString('utf8').trimEnd().split('\n').map(v=>JSON.parse(v));
  check(payload.version===1&&Array.isArray(payload.entries)&&rows.length===payload.entries.length,'LEDGER_PAYLOAD_INVALID');
  for(let i=0;i<rows.length;i++){
    const event=rows[i],entry=payload.entries[i];
    check(entry.event_ref===event.event_id&&entry.vault_ref===event.content.payload_vault_ref&&entry.manifest_ref===event.content.vault_manifest_ref&&digest(entry.payload)===event.content.content_hash,'LEDGER_PAYLOAD_BINDING_MISMATCH');
  }
  check(canonical(directory(root.path))===canonical(root),'LEDGER_DIRECTORY_CHANGED');
  return {ledger,payload};
}
export function writeLedgerPackage(output,keys,ledger,payload){
  check(Buffer.byteLength(ledger)<=MAX&&Buffer.byteLength(canonical(payload))<=MAX,'LEDGER_PACKAGE_TOO_LARGE');
  const parent=directory(path.dirname(path.resolve(output))),target=path.join(parent.path,path.basename(output));
  let exists=false;try{lstatSync(target);exists=true;}catch(e){if(e.code!=='ENOENT')throw e;}
  if(exists){
    const old=readLedgerPackage(target,keys);
    check(old.ledger.toString('utf8')===ledger&&canonical(old.payload)===canonical(payload),'LEDGER_PACKAGE_CONFLICT');
    return {state:'duplicate',records:payload.entries.length,ledger_sha256:digest(ledger)};
  }
  mkdirSync(target,{mode:0o700});const root=directory(target);
  check(canonical(directory(parent.path))===canonical(parent),'LEDGER_DIRECTORY_CHANGED');
  const aad={format:'kotodama-ledger-package-v1',destination_binding:keys.opaque('destination',root.path),key_ref:keys.opaque('key','v1'),ledger_sha256:digest(ledger)};
  const nonce=randomBytes(12),cipher=createCipheriv('aes-256-gcm',keys.encryption,nonce);cipher.setAAD(Buffer.from(canonical(aad)));
  const ciphertext=Buffer.concat([cipher.update(canonical(payload),'utf8'),cipher.final()]);
  const manifest={...aad,nonce:nonce.toString('hex'),tag:cipher.getAuthTag().toString('hex'),cipher_sha256:digest(ciphertext)};
  for(const [name,bytes] of [['payload.aes256gcm',ciphertext],['ledger.jsonl',ledger],['manifest.json',canonical(manifest)+'\n']]){
    check(canonical(directory(target))===canonical(root),'LEDGER_DIRECTORY_CHANGED');
    writeFileSync(path.join(target,name),bytes,{flag:'wx',mode:0o600});
  }
  const readback=readLedgerPackage(target,keys);
  check(canonical(readback.payload)===canonical(payload)&&readback.ledger.toString('utf8')===ledger,'LEDGER_PACKAGE_READBACK_FAILED');
  return {state:'created',records:payload.entries.length,ledger_sha256:aad.ledger_sha256};
}
