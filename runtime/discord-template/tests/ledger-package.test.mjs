import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import path from 'node:path';
import os from 'node:os';
import {canonical,digest,inside} from '../src/common.mjs';
import {ledgerKeys,readLedgerPackage,writeLedgerPackage} from '../src/ledger-package.mjs';

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
