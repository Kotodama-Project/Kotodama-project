import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,mkdir,symlink,link} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
import {readArtifact} from '../src/artifact.mjs';

async function fixture(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-artifact-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}
test('artifact reads preserve exact bytes including empty files',async t=>{const root=await fixture(t),file=path.join(root,'result');await writeFile(file,Buffer.from([0,1,255]));assert.deepEqual(await readArtifact(file,3),Buffer.from([0,1,255]));await writeFile(file,'');assert.equal((await readArtifact(file,0)).length,0);});
test('artifact cap rejects oversized files and invalid bounds',async t=>{const root=await fixture(t),file=path.join(root,'result');await writeFile(file,'abcd');for(const cap of [3,-1,NaN,Infinity,50000001])await assert.rejects(readArtifact(file,cap),/ARTIFACT_SIZE_LIMIT/);});
test('artifact read rejects a directory',async t=>{const root=await fixture(t);await assert.rejects(readArtifact(root,1000),/ARTIFACT_SIZE_LIMIT/);});
test('artifact read refuses a symlink rather than following it',async t=>{const root=await fixture(t),file=path.join(root,'result'),alias=path.join(root,'alias');await writeFile(file,'fixture');try{await symlink(file,alias);}catch(e){if(process.platform==='win32'&&e.code==='EPERM'){t.skip('Windows symlink privilege unavailable');return;}throw e;}await assert.rejects(readArtifact(alias,100),/ARTIFACT_SIZE_LIMIT/);});
test('artifact read refuses hard-linked files',async t=>{const root=await fixture(t),file=path.join(root,'result');await writeFile(file,'fixture');await link(file,path.join(root,'alias'));await assert.rejects(readArtifact(file,100),/ARTIFACT_SIZE_LIMIT/);});
test('artifact FIFO refusal returns without waiting for a writer',{skip:process.platform!=='linux'},async t=>{
  const root=await fixture(t),file=path.join(root,'fifo');assert.equal(spawnSync('mkfifo',[file]).status,0);
  const module=new URL('../src/artifact.mjs',import.meta.url).href;
  const script=`import {readArtifact} from ${JSON.stringify(module)};try{await readArtifact(process.argv[1],100);process.exitCode=2;}catch(error){if(error.code!=='ARTIFACT_SIZE_LIMIT')throw error;}`;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script,file],{timeout:2000,encoding:'utf8'});
  assert.equal(result.error,undefined);assert.equal(result.status,0,result.stderr);
});
