import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,link,rm,symlink} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {readArtifact} from '../src/worker.mjs';
test('artifact reads enforce limits and file identity on the opened handle',async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-artifact-read-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const file=path.join(dir,'result.txt');await writeFile(file,'result');assert.equal((await readArtifact(file,6)).toString(),'result');
  await assert.rejects(readArtifact(file,5),{code:'ARTIFACT_SIZE_LIMIT'});
  await link(file,path.join(dir,'alias'));await assert.rejects(readArtifact(file,6),{code:'ARTIFACT_SIZE_LIMIT'});
});

test('valid archive caps larger than worker defaults remain supported',async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-archive-read-'));t.after(()=>rm(dir,{recursive:true,force:true}));const f=path.join(dir,'audio.fixture');await writeFile(f,'pcm');assert.equal((await readArtifact(f,128*1024*1024)).toString(),'pcm');
  for(const cap of [-1,NaN,Infinity,1.5])await assert.rejects(readArtifact(f,cap),{code:'ARTIFACT_SIZE_LIMIT'});
});
test('FIFO and directory are rejected without an unbounded open',{skip:process.platform==='win32'},async t=>{
  const {execFile}=await import('node:child_process'),{promisify}=await import('node:util');const exec=promisify(execFile);
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-artifact-fifo-'));t.after(()=>rm(dir,{recursive:true,force:true}));const fifo=path.join(dir,'result.pipe');await exec('mkfifo',[fifo]);
  const module=new URL('../src/artifact.mjs',import.meta.url).href;
  const script=`import {readArtifact} from ${JSON.stringify(module)};try{await readArtifact(process.argv[1],64);process.exit(2)}catch(e){if(e.code!=='ARTIFACT_SIZE_LIMIT')throw e;}`;
  await exec(process.execPath,['--input-type=module','-e',script,fifo],{timeout:2000});await assert.rejects(readArtifact(dir,64),{code:'ARTIFACT_SIZE_LIMIT'});
});
test('a final symbolic link is refused as a non-regular artifact',{skip:process.platform==='win32'},async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-artifact-link-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const target=path.join(dir,'target.txt'),alias=path.join(dir,'alias.txt');await writeFile(target,'result');await symlink(target,alias);
  await assert.rejects(readArtifact(alias,64),{code:'ARTIFACT_SIZE_LIMIT'});assert.equal((await readArtifact(target,64)).toString(),'result');
});
test('a missing artifact keeps the original filesystem error',async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-artifact-missing-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  await assert.rejects(readArtifact(path.join(dir,'absent.txt'),64),{code:'ENOENT'});
});
