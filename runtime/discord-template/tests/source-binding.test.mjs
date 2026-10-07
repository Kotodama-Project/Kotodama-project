import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile,mkdir,cp,link,symlink} from 'node:fs/promises';
import {execFile,spawn} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {atomicJson,digest,inside} from '../src/common.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {SOURCE_SET,computeSourceBinding,compareParity,integrityReport} from '../src/source-binding.mjs';
import {bootstrapCLI} from '../src/source-bootstrap.mjs';

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
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-source-test-'));const runtimes=[];
  // Close every runtime before removing the tree: Windows cannot delete the open database.
  t.after(async()=>{try{for(const r of runtimes)await r.close();}finally{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});}});
  const config=exampleConfig({workspace:root,guildId:hiddenGuild});config.dataDir=path.join(root,'data');
  config.analyzer={executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};config.worker={...config.worker,executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};
  const file=path.join(root,'config.json');await atomicJson(file,config);
  const start=async options=>{const r=await startRuntime(file,{offline:true,log:()=>{},...options});runtimes.push(r);return r;};
  return {root,config,file,start};
}
const live=config=>()=>controlCommand(config,{action:'status'});
function keysOf(value,out=new Set()){if(Array.isArray(value))value.forEach(v=>keysOf(v,out));else if(value&&typeof value==='object')for(const [k,v] of Object.entries(value)){out.add(k);keysOf(v,out);}return out;}
async function copySource(from,to){for(const name of ['bin','src'])await cp(path.join(from,name),path.join(to,name),{recursive:true});for(const name of ['package.json','pnpm-lock.yaml'])await writeFile(path.join(to,name),await readFile(path.join(from,name)));}
async function cliFixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-source-cli-')),app=path.join(root,'app');await mkdir(app);await copySource(packageRoot,app);
  await symlink(path.join(packageRoot,'node_modules'),path.join(app,'node_modules'),process.platform==='win32'?'junction':'dir');
  const config=exampleConfig({workspace:root,guildId:hiddenGuild});config.dataDir=path.join(root,'data');config.analyzer={executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};config.worker={...config.worker,executable:process.execPath,args:[fixtureCli],timeoutSeconds:10};
  const file=path.join(root,'config.json');await atomicJson(file,config);const children=[];
  const stop=async child=>{if(child.exitCode!==null||child.signalCode!==null)return;child.kill('SIGTERM');await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{child.kill('SIGKILL');reject(new Error('owned CLI failed to stop'));},15000);child.once('exit',()=>{clearTimeout(timer);resolve();});});};
  t.after(async()=>{try{for(const child of children)await stop(child);}finally{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});}});
  const start=async({nodeArgs=[],extraEnv={}}={})=>{
    const env={...process.env,KOTODAMA_DEBUG:'',...extraEnv};if(!('NODE_OPTIONS' in extraEnv))delete env.NODE_OPTIONS;
    const child=spawn(process.execPath,[...nodeArgs,path.join(app,'bin/kotodama.mjs'),'start','--offline','--config',file],{env,stdio:['ignore','pipe','pipe']});children.push(child);let diagnostic='';child.stderr.on('data',bytes=>{diagnostic+=bytes;});
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('owned CLI startup timeout: '+diagnostic)),process.platform==='win32'?30000:15000);child.once('exit',()=>{clearTimeout(timer);reject(new Error('owned CLI exited before readiness: '+diagnostic));});let output='';child.stdout.on('data',bytes=>{output+=bytes;if(output.includes('"event":"runtime_ready"')){clearTimeout(timer);resolve();}});});
    return {close:()=>stop(child)};
  };
  return {root,app,config,file,start};
}
async function assertPlatformBinding(config){const status=await controlCommand(config,{action:'status'});if(process.platform==='win32'){assert.deepEqual(status.source,{set:SOURCE_SET,error:'SOURCE_BOOTSTRAP_UNSUPPORTED'});return false;}assert.equal(status.source.set,SOURCE_SET);assert.equal(status.source.error,undefined);return true;}

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

test('a large source listing stays unverified without breaking real status and command control',{timeout:90000},async t=>{
  const {app:tree,config,start}=await cliFixture(t);
  // This allowed file count would exceed the existing 1 MB control response.
  for(let first=0;first<3800;first+=50)await Promise.all(Array.from({length:50},(_,offset)=>writeFile(path.join(tree,'src',String(first+offset).padStart(4,'0')+'x'.repeat(180)+'.mjs'),'')));
  await assert.rejects(computeSourceBinding(tree),{code:'SOURCE_SET_LIMIT'});
  await start();
  const status=await controlCommand(config,{action:'status'});assert.deepEqual(status.source,{set:SOURCE_SET,error:process.platform==='win32'?'SOURCE_BOOTSTRAP_UNSUPPORTED':'SOURCE_SET_LIMIT'});
  assert(Buffer.byteLength(JSON.stringify(status))<1000000);
  const listed=await controlCommand(config,{action:'tasks',actor:config.discord.operators[0]});assert.deepEqual(listed,[]);
});

test('aggregate source bytes, directory traversal and depth have finite limits',{timeout:90000},async t=>{
  const top=await tempRoot(t);const bytes=await sourceTree(path.join(top,'bytes'));
  const block=Buffer.alloc(2000000);
  for(let i=0;i<33;i++)await writeFile(path.join(bytes,'src','block-'+i+'.mjs'),block);
  await assert.rejects(computeSourceBinding(bytes),{code:'SOURCE_SET_LIMIT'});
  await writeFile(path.join(bytes,'bin/a.mjs'),Buffer.alloc(2000001));
  await assert.rejects(computeSourceBinding(bytes),{code:'SOURCE_FILE_REFUSED'});
  const empty=await sourceTree(path.join(top,'empty'));
  for(let first=0;first<10000;first+=50)await Promise.all(Array.from({length:50},(_,offset)=>mkdir(path.join(empty,'src','empty-'+(first+offset)))));
  await assert.rejects(computeSourceBinding(empty),{code:'SOURCE_SET_LIMIT'});
  // Fewer than 10k entries, five tiny files: this isolates metadata bytes,
  // rather than the existing file/entry/binding limits.
  const metadata=await sourceTree(path.join(top,'metadata'));
  for(let first=0;first<5000;first+=50)await Promise.all(Array.from({length:50},(_,offset)=>mkdir(path.join(metadata,'src',String(first+offset).padStart(4,'0')+'m'.repeat(235)))));
  await assert.rejects(computeSourceBinding(metadata),{code:'SOURCE_SET_LIMIT'});
  const deep=await sourceTree(path.join(top,'deep'));await mkdir(path.join(deep,'src',...Array(65).fill('d')),{recursive:true});
  await assert.rejects(computeSourceBinding(deep),{code:'SOURCE_SET_LIMIT'});
});

test('an instance started from candidate A matches A on disk and as the candidate',{timeout:90000},async t=>{
  const {root,app:a,config,start}=await cliFixture(t);const candidate=path.join(root,'candidate');await mkdir(candidate);await copySource(a,candidate);
  await start();if(!await assertPlatformBinding(config))return;
  const report=await integrityReport({diskRoot:a,candidateRoot:candidate,revision:'0123456789abcdef',readStatus:live(config)});
  assert.equal(report.parity,'match');assert.deepEqual(report.reasons,[]);assert.equal(report.instance.setDigest,report.candidate.setDigest);assert.equal(report.disk.setDigest,report.candidate.setDigest);
  assert.deepEqual(report.revision,{value:'0123456789abcdef',checkedByTool:false});assert(Date.parse(report.instance.boundAt)<=Date.parse(report.readAt));
  const keys=keysOf(report);for(const key of ['pid','ownerId','port','secretFile','configFile','files'])assert(!keys.has(key),key);
  assert(!JSON.stringify(report).includes(root)&&!JSON.stringify(report).includes(JSON.stringify(root).slice(1,-1)));
});

test('an old process is not matched by new bytes on disk until it is restarted',{timeout:90000},async t=>{
  const {root,app:a,config,start}=await cliFixture(t);const b=path.join(root,'candidate-b');await mkdir(b);await copySource(a,b);const changed=await readFile(path.join(a,'src/worker.mjs'),'utf8')+'\n// owned candidate B\n';await writeFile(path.join(b,'src/worker.mjs'),changed);
  const r=await start();if(!await assertPlatformBinding(config))return;
  await writeFile(path.join(a,'src/worker.mjs'),changed);
  const old=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(old.parity,'mismatch');assert.deepEqual(old.reasons,['INSTANCE_DISK_DIFFERS','INSTANCE_CANDIDATE_DIFFERS']);assert.deepEqual(old.differingPaths,{instanceDisk:['src/worker.mjs'],instanceCandidate:['src/worker.mjs']});
  assert.equal(old.disk.setDigest,old.candidate.setDigest);assert.notEqual(old.instance.setDigest,old.disk.setDigest);
  await r.close();
  const stopped=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(stopped.parity,'unverified');assert.deepEqual(stopped.reasons,['RUNTIME_NOT_AVAILABLE']);assert.equal(stopped.instance,null);assert.equal(stopped.readAt,null);
  await start();
  const restarted=await integrityReport({diskRoot:a,candidateRoot:b,readStatus:live(config)});
  assert.equal(restarted.parity,'match');assert.equal(restarted.instance.setDigest,restarted.candidate.setDigest);
});

test('a replaced instance, a missing binding and a saved or stale report stay unverified',{timeout:90000},async t=>{
  const {app:a,config,start}=await cliFixture(t);
  await start();if(!await assertPlatformBinding(config))return;
  const saved=await controlCommand(config,{action:'status'});const disk=await computeSourceBinding(a);const now=Date.now();
  assert.equal(compareParity({candidate:disk,disk,instance:{source:saved.source,readAt:new Date(now).toISOString()},now}).parity,'match');
  for(const readAt of [new Date(now-61000).toISOString(),new Date(now+1000).toISOString(),'not-a-time',undefined]){
    const stale=compareParity({candidate:disk,disk,instance:{source:saved.source,readAt},now});assert.equal(stale.parity,'unverified');assert.deepEqual(stale.reasons,['STALE_READBACK']);assert.equal(stale.instance,null);
  }
  const tampered={...saved.source,files:saved.source.files.map((f,i)=>i===0?{...f,sha256:'0'.repeat(64)}:f)};
  assert.deepEqual(compareParity({candidate:disk,disk,instance:{source:tampered,readAt:new Date(now).toISOString()},now}).reasons,['INSTANCE_BINDING_INVALID']);
  for(const missing of ['package.json','pnpm-lock.yaml']){
    const files=saved.source.files.filter(file=>file.path!==missing),incomplete={...saved.source,files,fileCount:files.length,setDigest:digest({set:SOURCE_SET,files}),[missing==='package.json'?'packageDigest':'lockDigest']:undefined};
    assert.deepEqual(compareParity({candidate:disk,disk,instance:{source:incomplete,readAt:new Date(now).toISOString()},now}).reasons,['INSTANCE_BINDING_INVALID']);
  }
  for(const source of [undefined,{set:SOURCE_SET,error:'SOURCE_LINK_REFUSED'},{...saved.source,set:'another.set'}])assert.deepEqual(compareParity({candidate:disk,disk,instance:{source,readAt:new Date(now).toISOString()},now}).reasons,['INSTANCE_BINDING_MISSING']);
  assert.deepEqual(compareParity({candidate:disk,disk,instance:{error:'connect refused at 127.0.0.1'},now}).reasons,['RUNTIME_NOT_AVAILABLE']);
  assert.deepEqual(compareParity({disk,instance:{source:saved.source,readAt:new Date(now).toISOString()},now}),{parity:'unverified',reasons:['CANDIDATE_REQUIRED'],differingPaths:{},instance:{setDigest:disk.setDigest,packageDigest:disk.packageDigest,lockDigest:disk.lockDigest,fileCount:disk.fileCount,boundAt:saved.source.boundAt}});
  const oldRuntime=await integrityReport({diskRoot:a,candidateRoot:a,readStatus:async()=>{const {source,...rest}=saved;return rest;}});assert.equal(oldRuntime.parity,'unverified');assert.deepEqual(oldRuntime.reasons,['INSTANCE_BINDING_MISSING']);
  await assert.rejects(integrityReport({diskRoot:a,candidateRoot:a,revision:'main',readStatus:live(config)}),{code:'REVISION_INVALID'});
  const runtimeFile=path.join(config.dataDir,'runtime.json');const metadata=JSON.parse(await readFile(runtimeFile,'utf8'));await atomicJson(runtimeFile,{...metadata,ownerId:'host-another-instance'});
  const replaced=await integrityReport({diskRoot:a,candidateRoot:a,readStatus:live(config)});assert.equal(replaced.parity,'unverified');assert.deepEqual(replaced.reasons,['RUNTIME_OWNER_CHANGED']);assert.equal(replaced.instance,null);
});

test('a runtime whose source cannot be bound still starts but is never reported as matching',{timeout:90000},async t=>{
  const {root,app:broken,config,start}=await cliFixture(t);const clean=path.join(root,'clean');await mkdir(clean);await copySource(broken,clean);
  await link(path.join(broken,'src/worker.mjs'),path.join(root,'outside-link.mjs'));
  await start();
  const status=await controlCommand(config,{action:'status'});assert.deepEqual(status.source,{set:SOURCE_SET,error:process.platform==='win32'?'SOURCE_BOOTSTRAP_UNSUPPORTED':'SOURCE_FILE_REFUSED'});
  const report=await integrityReport({diskRoot:clean,candidateRoot:clean,readStatus:live(config)});assert.equal(report.parity,'unverified');assert.deepEqual(report.reasons,['INSTANCE_BINDING_MISSING']);
});

test('the integrity command reads the live instance and prints no PID, port, path or setting',{timeout:90000},async t=>{
  const {root,app,config,file,start}=await cliFixture(t);const env={...process.env,KOTODAMA_DEBUG:''};
  const run=async(...args)=>{try{const {stdout}=await exec(process.execPath,[bin,'integrity','--json','--config',file,...args],{env});return {exit:0,value:JSON.parse(stdout.trim())};}catch(e){if(typeof e.stdout!=='string'||!e.stdout.trim())throw e;return {exit:e.code,value:JSON.parse(e.stdout.trim())};}};
  const r=await start();
  const revision='0123456789abcdef0123456789abcdef01234567';const matched=await run('--candidate',app,'--revision',revision);
  if(process.platform==='win32'){assert.equal(matched.exit,1);assert.equal(matched.value.parity,'unverified');assert.deepEqual(matched.value.reasons,['INSTANCE_BINDING_MISSING']);return;}
  assert.equal(matched.exit,0);assert.equal(matched.value.parity,'match');assert.equal(matched.value.revision.value,revision);assert.equal(matched.value.instance.setDigest,matched.value.candidate.setDigest);
  const secret=(await readFile(path.join(config.dataDir,'control.secret'),'utf8')).trim();const runtime=JSON.parse(await readFile(path.join(config.dataDir,'runtime.json'),'utf8'));const text=JSON.stringify(matched.value);
  for(const hidden of [root,packageRoot,JSON.stringify(root).slice(1,-1),JSON.stringify(packageRoot).slice(1,-1),hiddenGuild,secret,runtime.ownerId])assert(!text.includes(hidden),'output must not include '+hidden);
  const keys=keysOf(matched.value);for(const key of ['pid','ownerId','port','secretFile','configFile','files'])assert(!keys.has(key),key);
  const noCandidate=await run();assert.equal(noCandidate.exit,1);assert.equal(noCandidate.value.parity,'unverified');assert.deepEqual(noCandidate.value.reasons,['CANDIDATE_REQUIRED']);
  await r.close();
  const stopped=await run('--candidate',packageRoot);assert.equal(stopped.exit,1);assert.equal(stopped.value.parity,'unverified');assert.deepEqual(stopped.value.reasons,['RUNTIME_NOT_AVAILABLE']);assert.equal(stopped.value.instance,null);
});

test('cached direct starts, arbitrary source roots and fabricated bootstrap records never claim a loaded source',async t=>{
  const {root,config,file,start}=await runtimeFixture(t),candidate=await sourceTree(path.join(root,'fake-candidate'));
  const runtime=await start({sourceRoot:candidate,sourceBootstrap:{set:SOURCE_SET,...await computeSourceBinding(candidate),boundAt:new Date().toISOString()}});
  const status=await controlCommand(config,{action:'status'});assert.deepEqual(status.source,{set:SOURCE_SET,error:'SOURCE_BOOTSTRAP_REQUIRED'});
  assert.deepEqual(await controlCommand(config,{action:'tasks',actor:config.discord.operators[0]}),[]);await runtime.close();
  const modules=await bootstrapCLI(async()=>({startRuntime}));
  const direct=await modules.startRuntime(file,{offline:true,log:()=>{},sourceBootstrap:modules.sourceBootstrap});
  try{assert.deepEqual((await controlCommand(config,{action:'status'})).source,{set:SOURCE_SET,error:'SOURCE_BOOTSTRAP_REQUIRED'});}finally{await direct.close();}
});

test('a real cold CLI refuses a source changed and restored after the different runtime module actually loaded',{timeout:90000},async t=>{
  const {root,app,config,start}=await cliFixture(t),runtimeFile=path.join(app,'src/runtime.mjs'),configFile=path.join(app,'src/config.mjs'),marker=path.join(root,'loaded-revision');
  const original=await readFile(runtimeFile,'utf8');
  const revisionB=original+'\nawait (await import("node:fs/promises")).writeFile('+JSON.stringify(marker)+',"loaded-B");\nawait (await import("node:fs/promises")).writeFile(new URL("./runtime.mjs",import.meta.url),'+JSON.stringify(original)+');\n';
  await writeFile(configFile,await readFile(configFile,'utf8')+'\nawait (await import("node:fs/promises")).writeFile(new URL("./runtime.mjs",import.meta.url),'+JSON.stringify(revisionB)+');\n');
  const before=await computeSourceBinding(app);await start();
  assert.equal(await readFile(marker,'utf8'),'loaded-B','the actual imported module executed revision B');
  assert.equal((await computeSourceBinding(app)).setDigest,before.setDigest,'disk content returned to the pre-import candidate');
  const status=await controlCommand(config,{action:'status'});assert.deepEqual(status.source,{set:SOURCE_SET,error:process.platform==='win32'?'SOURCE_BOOTSTRAP_UNSUPPORTED':'SOURCE_CHANGED_DURING_STARTUP'});
  const report=await integrityReport({diskRoot:app,candidateRoot:app,readStatus:live(config)});assert.equal(report.parity,'unverified');assert.deepEqual(report.reasons,['INSTANCE_BINDING_MISSING']);
  assert.deepEqual(await controlCommand(config,{action:'tasks',actor:config.discord.operators[0]}),[]);
});

test('an actual CLI with cached application modules and newer disk bytes keeps control usable without source proof',{timeout:90000},async t=>{
  const {root,app,config,start}=await cliFixture(t),preload=path.join(root,'preload.mjs');
  const workerFile=path.join(app,'src/worker.mjs'),original=await readFile(workerFile,'utf8');
  await writeFile(preload,'await import('+JSON.stringify(pathToFileURL(path.join(app,'src/config.mjs')).href)+');\nawait import('+JSON.stringify(pathToFileURL(path.join(app,'src/runtime.mjs')).href)+');\nawait (await import("node:fs/promises")).appendFile('+JSON.stringify(workerFile)+',"\\n// changed after actual module import\\n");\n');
  await start({nodeArgs:['--import',pathToFileURL(preload).href]});const status=await controlCommand(config,{action:'status'});
  assert.equal(await readFile(workerFile,'utf8'),original+'\n// changed after actual module import\n');
  assert.deepEqual(status.source,{set:SOURCE_SET,error:'SOURCE_BOOTSTRAP_REQUIRED'});
  assert.equal((await integrityReport({diskRoot:app,candidateRoot:app,readStatus:live(config)})).parity,'unverified');
  assert.deepEqual(await controlCommand(config,{action:'tasks',actor:config.discord.operators[0]}),[]);
});
