import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import path from 'node:path';
import os from 'node:os';
import {canonical,digest,inside} from '../src/common.mjs';
import {ledgerKeys,readLedgerPackage,writeLedgerPackage} from '../src/ledger-package.mjs';

function packageFixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'kotodama-ledger-descriptor-')),output=path.join(root,'package'),keys=ledgerKeys('d1'.repeat(32));
  t.after(()=>{assert(inside(os.tmpdir(),root)&&path.basename(root).startsWith('kotodama-ledger-descriptor-'));fs.rmSync(root,{recursive:true,force:true});});
  const payload={observed:'synthetic'},row={event_id:'ref/event/fixture',content:{payload_vault_ref:'ref/vault/fixture',vault_manifest_ref:'ref/vault-manifest/fixture',content_hash:digest(payload)}};
  writeLedgerPackage(output,keys,canonical(row)+'\n',{version:1,entries:[{event_ref:row.event_id,vault_ref:row.content.payload_vault_ref,manifest_ref:row.content.vault_manifest_ref,payload}]});
  return {root,output,keys};
}

test('a file replaced during open is refused before reading any bytes',t=>{
  const {root,output,keys}=packageFixture(t),target=path.join(output,'manifest.json'),bytes=fs.readFileSync(target),original={openSync:fs.openSync,readSync:fs.readSync};let readBytes=0,swapped=false;
  try{
    fs.openSync=(filename,...args)=>{const fd=original.openSync(filename,...args);if(filename===target&&!swapped){swapped=true;fs.renameSync(target,path.join(root,'old-manifest'));fs.writeFileSync(target,bytes);}return fd;};
    fs.readSync=(...args)=>{const n=original.readSync(...args);readBytes+=n;return n;};syncBuiltinESMExports();
    assert.throws(()=>readLedgerPackage(output,keys),/LEDGER_FILE_CHANGED/);assert.equal(readBytes,0);
  }finally{Object.assign(fs,original);syncBuiltinESMExports();}
});

test('a hardlinked payload is refused even when its bytes still match',t=>{
  const {root,output,keys}=packageFixture(t);fs.linkSync(path.join(output,'payload.aes256gcm'),path.join(root,'linked-payload'));
  assert.throws(()=>readLedgerPackage(output,keys),/LEDGER_FILE_REFUSED/);
});

test('concurrent file growth is refused after at most the original size plus one byte',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'kotodama-ledger-growth-')),output=path.join(root,'package'),keys=ledgerKeys('c9'.repeat(32));
  const payload={observed:'synthetic'},row={event_id:'ref/event/fixture',content:{payload_vault_ref:'ref/vault/fixture',vault_manifest_ref:'ref/vault-manifest/fixture',content_hash:digest(payload)}};
  writeLedgerPackage(output,keys,canonical(row)+'\n',{version:1,entries:[{event_ref:row.event_id,vault_ref:row.content.payload_vault_ref,manifest_ref:row.content.vault_manifest_ref,payload}]});
  const target=path.join(output,'manifest.json'),size=fs.statSync(target).size,original={openSync:fs.openSync,readFileSync:fs.readFileSync,readSync:fs.readSync};let selected,grew=false,readBytes=0;
  const grow=fd=>{if(fd===selected&&!grew){grew=true;fs.appendFileSync(target,' '.repeat(1024*1024));}};
  try{
    fs.openSync=(filename,...args)=>{const fd=original.openSync(filename,...args);if(filename===target)selected=fd;return fd;};
    fs.readFileSync=(fd,...args)=>{grow(fd);const bytes=original.readFileSync(fd,...args);if(fd===selected)readBytes+=bytes.length;return bytes;};
    fs.readSync=(fd,...args)=>{grow(fd);const count=original.readSync(fd,...args);if(fd===selected)readBytes+=count;return count;};syncBuiltinESMExports();
    assert.throws(()=>readLedgerPackage(output,keys),/LEDGER_FILE_CHANGED/);assert(grew);assert(readBytes<=size+1,`read ${readBytes} bytes after observing only ${size}`);
  }finally{
    Object.assign(fs,original);syncBuiltinESMExports();assert(inside(os.tmpdir(),root)&&path.basename(root).startsWith('kotodama-ledger-growth-'));fs.rmSync(root,{recursive:true,force:true});
  }
});
