import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile,mkdir,cp,link,symlink} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson,inside} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {SOURCE_SET,computeSourceBinding,compareParity,integrityReport} from '../src/source-binding.mjs';

// Synthetic source trees and an offline runtime only; no Discord or provider.
const exec=promisify(execFile);
const packageRoot=fileURLToPath(new URL('..',import.meta.url));const fixtureCli=path.join(packageRoot,'tests/fixtures/model-cli.mjs');
const bin=path.join(packageRoot,'bin/kotodama.mjs');const hiddenGuild='100000000000000777';
async function tempRoot(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-source-test-'));t.after(async()=>{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});});return root;}
async function sourceTree(root,{b='export const b=1;\n'}={}){
  for(const dir of ['bin','src/nested'])await mkdir(path.join(root,dir),{recursive:true});
  await writeFile(path.join(root,'bin/a.mjs'),'export const a=1;\n');await writeFile(path.join(root,'src/b.mjs'),b);await writeFile(path.join(root,'src/nested/c.mjs'),'export const c=1;\n');
  await writeFile(path.join(root,'package.json'),'{"name":"fixture"}\n');await writeFile(path.join(root,'pnpm-lock.yaml'),"lockfileVersion: '9.0'\n");return root;
}
async function runtimeFixture(t){
  const root=await tempRoot(t);const config=exampleConfig({workspace:root,guildId:hiddenGuild});config.dataDir=path.join(root,'data');
  config.analyzer={executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};config.worker={...config.worker,executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};
  const file=path.join(root,'config.json');await atomicJson(file,config);return {root,config,file};
}
const live=config=>()=>controlCommand(config,{action:'status'});
function keysOf(value,out=new Set()){if(Array.isArray(value))value.forEach(v=>keysOf(v,out));else if(value&&typeof value==='object')for(const [k,v] of Object.entries(value)){out.add(k);keysOf(v,out);}return out;}

test('the source set is bin, src and the package files, and nothing outside it changes the digest',async t=>{
  const root=await sourceTree(path.join(await tempRoot(t),'a'));const base=await computeSourceBinding(root);
  assert.equal(base.set,SOURCE_SET);assert.deepEqual(base.files.map(f=>f.path),['bin/a.mjs','package.json','pnpm-lock.yaml','src/b.mjs','src/nested/c.mjs']);assert.equal(base.fileCount,5);
  assert(Object.isFrozen(base)&&Object.isFrozen(base.files));const text=JSON.stringify(base);assert(!text.includes(root)&&!text.includes(JSON.stringify(root).slice(1,-1)));
  for(const [name,value] of [['docs/NOTE.md','note'],['.env','KOTODAMA_FIXTURE=outside-the-set'],['.kotodama/config.json','{}'],['tests/x.test.mjs','x'],['node_modules/dep/index.js','x']]){await mkdir(path.dirname(path.join(root,name)),{recursive:true});await writeFile(path.join(root,name),value);}
  assert.equal((await computeSourceBinding(root)).setDigest,base.setDigest);
  await writeFile(path.join(root,'src/nested/c.mjs'),'export const c=2;\n');const changed=await computeSourceBinding(root);assert.notEqual(changed.setDigest,base.setDigest);assert.equal(changed.packageDigest,base.packageDigest);
  await writeFile(path.join(root,'pnpm-lock.yaml'),"lockfileVersion: '9.1'\n");const lock=await computeSourceBinding(root);assert.notEqual(lock.lockDigest,base.lockDigest);assert.notEqual(lock.setDigest,changed.setDigest);
  await writeFile(path.join(root,'src/extra.mjs'),'');assert.equal((await computeSourceBinding(root)).fileCount,6);
});

test('missing package files and hard-linked source files are refused',async t=>{
  const top=await tempRoot(t);const root=await sourceTree(path.join(top,'a'));
  await rm(path.join(root,'pnpm-lock.yaml'));await assert.rejects(computeSourceBinding(root),{code:'SOURCE_FILE_MISSING'});
  const noSrc=await sourceTree(path.join(top,'b'));await rm(path.join(noSrc,'src'),{recursive:true});await assert.rejects(computeSourceBinding(noSrc),{code:'SOURCE_FILE_MISSING'});
  const linked=await sourceTree(path.join(top,'c'));await link(path.join(linked,'src/b.mjs'),path.join(linked,'src/b-link.mjs'));await assert.rejects(computeSourceBinding(linked),{code:'SOURCE_FILE_REFUSED'});
  await assert.rejects(computeSourceBinding(path.join(top,'absent')),{code:'SOURCE_FILE_MISSING'});
});

test('a symbolic link inside the source set is refused',{skip:process.platform==='win32'?'Symlink creation requires a separate Windows privilege; Linux CI covers this refusal.':false},async t=>{
  const top=await tempRoot(t);const root=await sourceTree(path.join(top,'a'));await writeFile(path.join(top,'outside.mjs'),'export const outside=1;\n');
  await symlink(path.join(top,'outside.mjs'),path.join(root,'src/linked.mjs'),'file');await assert.rejects(computeSourceBinding(root),{code:'SOURCE_LINK_REFUSED'});
  await rm(path.join(root,'src/linked.mjs'));await symlink(path.join(top),path.join(root,'src/dir-link'),'dir');await assert.rejects(computeSourceBinding(root),{code:'SOURCE_LINK_REFUSED'});
});

test('an instance started from candidate A matches A on disk and as the candidate',async t=>{
  const {root,config,file}=await runtimeFixture(t);const a=await sourceTree(path.join(root,'deployed'));const candidate=path.join(root,'candidate');await cp(a,candidate,{recursive:true});
  const r=await startRuntime(file,{offline:true,sourceRoot:a,log:()=>{}});t.after(()=>r.close());
  const report=await integrityReport({diskRoot:a,candidateRoot:candidate,revision:'0123456789abcdef',readStatus:live(config)});
  assert.equal(report.parity,'match');assert.deepEqual(report.reasons,[]);assert.equal(report.instance.setDigest,report.candidate.setDigest);assert.equal(report.disk.setDigest,report.candidate.setDigest);
  assert.deepEqual(report.revision,{value:'0123456789abcdef',checkedByTool:false});assert(Date.parse(report.instance.boundAt)<=Date.parse(report.readAt));
  const keys=keysOf(report);for(const key of ['pid','ownerId','port','secretFile','configFile','files'])assert(!keys.has(key),key);
  assert(!JSON.stringify(report).includes(root)&&!JSON.stringify(report).includes(JSON.stringify(root).slice(1,-1)));
});

test('an old process is not matched by new bytes on disk until it is restarted',async t=>{
  const {root,config,file}=await runtimeFixture(t);const a=await sourceTree(path.join(root,'deployed'));const b=await sourceTree(path.join(root,'candidate-b'),{b:'export const b=2;\n'});
  let r=await startRuntime(file,{offline:true,sourceRoot:a,log:()=>{}});t.after(()=>r.close());
  await writeFile(path.join(a,'src/b.mjs'),'export const b=2;\n');
  const old=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(old.parity,'mismatch');assert.deepEqual(old.reasons,['INSTANCE_DISK_DIFFERS','INSTANCE_CANDIDATE_DIFFERS']);assert.deepEqual(old.differingPaths,{instanceDisk:['src/b.mjs'],instanceCandidate:['src/b.mjs']});
  assert.equal(old.disk.setDigest,old.candidate.setDigest);assert.notEqual(old.instance.setDigest,old.disk.setDigest);
  await r.close();
  const stopped=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(stopped.parity,'unverified');assert.deepEqual(stopped.reasons,['RUNTIME_NOT_AVAILABLE']);assert.equal(stopped.instance,null);assert.equal(stopped.readAt,null);
  r=await startRuntime(file,{offline:true,sourceRoot:a,log:()=>{}});
  const restarted=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(restarted.parity,'match');assert.equal(restarted.instance.setDigest,restarted.candidate.setDigest);
});

test('a replaced instance, a missing binding and a saved or stale report stay unverified',async t=>{
  const {root,config,file}=await runtimeFixture(t);const a=await sourceTree(path.join(root,'deployed'));
  const r=await startRuntime(file,{offline:true,sourceRoot:a,log:()=>{}});t.after(()=>r.close());
  const saved=await controlCommand(config,{action:'status'});const disk=await computeSourceBinding(a);const now=Date.now();
  assert.equal(compareParity({candidate:disk,disk,instance:{source:saved.source,readAt:new Date(now).toISOString()},now}).parity,'match');
  for(const readAt of [new Date(now-61000).toISOString(),new Date(now+1000).toISOString(),'not-a-time',undefined]){
    const stale=compareParity({candidate:disk,disk,instance:{source:saved.source,readAt},now});assert.equal(stale.parity,'unverified');assert.deepEqual(stale.reasons,['STALE_READBACK']);assert.equal(stale.instance,null);
  }
  const tampered={...saved.source,files:saved.source.files.map((f,i)=>i===0?{...f,sha256:'0'.repeat(64)}:f)};
  assert.deepEqual(compareParity({candidate:disk,disk,instance:{source:tampered,readAt:new Date(now).toISOString()},now}).reasons,['INSTANCE_BINDING_INVALID']);
  for(const source of [undefined,{set:SOURCE_SET,error:'SOURCE_LINK_REFUSED'},{...saved.source,set:'another.set'}])assert.deepEqual(compareParity({candidate:disk,disk,instance:{source,readAt:new Date(now).toISOString()},now}).reasons,['INSTANCE_BINDING_MISSING']);
  assert.deepEqual(compareParity({candidate:disk,disk,instance:{error:'connect refused at 127.0.0.1'},now}).reasons,['RUNTIME_NOT_AVAILABLE']);
  assert.deepEqual(compareParity({disk,instance:{source:saved.source,readAt:new Date(now).toISOString()},now}),{parity:'unverified',reasons:['CANDIDATE_REQUIRED'],differingPaths:{},instance:{setDigest:disk.setDigest,packageDigest:disk.packageDigest,lockDigest:disk.lockDigest,fileCount:disk.fileCount,boundAt:saved.source.boundAt}});
  const oldRuntime=await integrityReport({diskRoot:a,candidateRoot:a,readStatus:async()=>{const {source,...rest}=saved;return rest;}});assert.equal(oldRuntime.parity,'unverified');assert.deepEqual(oldRuntime.reasons,['INSTANCE_BINDING_MISSING']);
  await assert.rejects(integrityReport({diskRoot:a,candidateRoot:a,revision:'main',readStatus:live(config)}),{code:'REVISION_INVALID'});
  const runtimeFile=path.join(config.dataDir,'runtime.json');const metadata=JSON.parse(await readFile(runtimeFile,'utf8'));await atomicJson(runtimeFile,{...metadata,ownerId:'host-another-instance'});
  const replaced=await integrityReport({diskRoot:a,candidateRoot:a,readStatus:live(config)});assert.equal(replaced.parity,'unverified');assert.deepEqual(replaced.reasons,['RUNTIME_OWNER_CHANGED']);assert.equal(replaced.instance,null);
});

test('a runtime whose source cannot be bound still starts but is never reported as matching',async t=>{
  const {root,config,file}=await runtimeFixture(t);const broken=await sourceTree(path.join(root,'broken'));const clean=await sourceTree(path.join(root,'clean'));
  await link(path.join(broken,'src/b.mjs'),path.join(root,'outside-link.mjs'));
  const r=await startRuntime(file,{offline:true,sourceRoot:broken,log:()=>{}});t.after(()=>r.close());
  const status=await controlCommand(config,{action:'status'});assert.deepEqual(status.source,{set:SOURCE_SET,error:'SOURCE_FILE_REFUSED'});
  const report=await integrityReport({diskRoot:clean,candidateRoot:clean,readStatus:live(config)});assert.equal(report.parity,'unverified');assert.deepEqual(report.reasons,['INSTANCE_BINDING_MISSING']);
});

test('the integrity command reads the live instance and prints no PID, port, path or setting',{timeout:90000},async t=>{
  const {root,config,file}=await runtimeFixture(t);const env={...process.env,KOTODAMA_DEBUG:''};
  const run=async(...args)=>{try{const {stdout}=await exec(process.execPath,[bin,'integrity','--json','--config',file,...args],{env});return {exit:0,value:JSON.parse(stdout.trim())};}catch(e){if(typeof e.stdout!=='string'||!e.stdout.trim())throw e;return {exit:e.code,value:JSON.parse(e.stdout.trim())};}};
  const r=await startRuntime(file,{offline:true,log:()=>{}});let closed=false;t.after(async()=>{if(!closed)await r.close();});
  const revision='0123456789abcdef0123456789abcdef01234567';const matched=await run('--candidate',packageRoot,'--revision',revision);
  assert.equal(matched.exit,0);assert.equal(matched.value.parity,'match');assert.equal(matched.value.revision.value,revision);assert.equal(matched.value.instance.setDigest,matched.value.candidate.setDigest);
  const secret=(await readFile(path.join(config.dataDir,'control.secret'),'utf8')).trim();const runtime=JSON.parse(await readFile(path.join(config.dataDir,'runtime.json'),'utf8'));const text=JSON.stringify(matched.value);
  for(const hidden of [root,packageRoot,JSON.stringify(root).slice(1,-1),JSON.stringify(packageRoot).slice(1,-1),hiddenGuild,secret,runtime.ownerId])assert(!text.includes(hidden),'output must not include '+hidden);
  const keys=keysOf(matched.value);for(const key of ['pid','ownerId','port','secretFile','configFile','files'])assert(!keys.has(key),key);
  const noCandidate=await run();assert.equal(noCandidate.exit,1);assert.equal(noCandidate.value.parity,'unverified');assert.deepEqual(noCandidate.value.reasons,['CANDIDATE_REQUIRED']);
  await r.close();closed=true;
  const stopped=await run('--candidate',packageRoot);assert.equal(stopped.exit,1);assert.equal(stopped.value.parity,'unverified');assert.deepEqual(stopped.value.reasons,['RUNTIME_NOT_AVAILABLE']);assert.equal(stopped.value.instance,null);
});
