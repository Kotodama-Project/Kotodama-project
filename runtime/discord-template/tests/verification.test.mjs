import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {DockerVerifier,verificationArgs} from '../src/verification.mjs';
import {CliWorker} from '../src/worker.mjs';
import {exampleConfig,Config} from '../src/config.mjs';
import {runCommand} from '../src/command.mjs';
const image='sha256:'+'a'.repeat(64),id='b'.repeat(64),owner='verify-00000000-0000-4000-8000-000000000000';
const config={kind:'docker',image};
function fixtureRunner({failStart=false,failCleanup=false,exitCode=0}={}){
  const calls=[];let label=null;
  return {calls,run:async(executable,args,options)=>{
    calls.push({executable,args,env:options.env,signal:options.signal});assert(!('CODEX_HOME'in options.env));assert(!('DOCKER_HOST'in options.env));
    const result=(stdout='',code=0)=>({code,stdout,stderr:''});
    if(args[0]==='image')return result(JSON.stringify([{Id:image,Os:'linux',Config:{Volumes:null}}]));
    if(args[1]==='create'){label=args[args.indexOf('--label')+1].split('=')[1];return result(id+'\n');}
    if(args[1]==='inspect')return result(JSON.stringify([{Id:id,Image:image,Config:{Labels:{'org.kotodama.verification-owner':label}},State:{Running:false,ExitCode:exitCode}}]));
    if(args[1]==='start'){if(failStart)throw Object.assign(Error('cancelled'),{code:'CANCELLED'});return result('fixture output',0);}
    if(args[1]==='rm')return result('',failCleanup?1:0);
    if(args[1]==='ls')return result('');
    assert.fail('unexpected verification command');
  }};
}
test('verifier arguments pin the image and refuse host, network, write and privilege access',()=>{
  const args=verificationArgs({image,workspace:'/fixture/candidate',owner,command:{executable:'node',args:['-e','console.log(1)']}});
  for(const flag of ['--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges=true','--log-driver=none'])assert(args.includes(flag));
  assert.equal(args.filter(a=>a==='--mount').length,1);assert(args.some(a=>a.includes('target=/workspace,readonly,')));assert(!args.includes('--privileged'));assert(!args.includes('--env-file'));assert(!args.includes('--volumes-from'));assert(!args.some(a=>a.includes('docker.sock')));
  for(const workspace of ['relative','/unsafe,other=mount','/newline\npath'])assert.throws(()=>verificationArgs({image,workspace,owner,command:{executable:'node',args:[]}}),/VERIFICATION_WORKSPACE_INVALID/);
  assert.throws(()=>verificationArgs({image:'node:latest',workspace:'/work',owner,command:{executable:'node',args:[]}}),/VERIFICATION_IMAGE_UNPINNED/);
});
test('configuration refuses a mutable verifier image but does not require Docker for research',()=>{
  const cfg=exampleConfig();assert.equal(cfg.worker.verification,undefined);cfg.worker.verification={kind:'docker',image:'node:latest'};assert.throws(()=>Config.parse(cfg));cfg.worker.verification={kind:'docker',image};assert.equal(Config.parse(cfg).worker.verification.image,image);
});
test('write preflight never falls back to ordinary host verification',{skip:process.platform!=='linux'},async()=>{
  const cfg=exampleConfig();cfg.worker.actions=['develop'];cfg.worker.verify=[{executable:'node',args:['--version']}];
  await assert.rejects(new CliWorker(cfg).run({id:'task-fixture',revision:1,action:'develop'},[]),{code:'VERIFICATION_ISOLATION_REQUIRED'});
  cfg.worker.verify=[];await assert.rejects(new CliWorker(cfg).run({id:'task-fixture',revision:1,action:'develop'},[]),{code:'VERIFICATION_COMMAND_REQUIRED'});
});
test('verification reads daemon exit status and confirms removal of the exact owned container',async()=>{
  const f=fixtureRunner({exitCode:7}),v=new DockerVerifier(config,{run:f.run});const result=await v.verify({executable:'node',args:[]},{cwd:os.tmpdir()});assert.equal(result.code,7);assert.equal(result.isolation.cleanupConfirmed,true);assert(f.calls.some(c=>c.args[1]==='rm'&&c.args.at(-1)===id));assert(f.calls.some(c=>c.args[1]==='ls'&&c.args.at(-1)==='id='+id));
});
test('cancelled verifier CLI still removes its daemon container independently of cancellation',async()=>{
  const f=fixtureRunner({failStart:true}),v=new DockerVerifier(config,{run:f.run});await assert.rejects(v.verify({executable:'node',args:[]},{cwd:os.tmpdir()}),{code:'CANCELLED'});const cleanup=f.calls.find(c=>c.args[1]==='rm');assert(cleanup);assert.equal(cleanup.signal,undefined);
});
test('a cleanup failure remains uncertain even after a successful verification exit',async()=>{
  const f=fixtureRunner({failCleanup:true}),v=new DockerVerifier(config,{run:f.run});await assert.rejects(v.verify({executable:'node',args:[]},{cwd:os.tmpdir()}),{code:'STOP_UNCONFIRMED'});
});
test('verification rechecks authorization before payload start and preserves owned cleanup',async()=>{
  const f=fixtureRunner(),v=new DockerVerifier(config,{run:f.run});let checks=0;await assert.rejects(v.verify({executable:'node',args:[]},{cwd:os.tmpdir(),authorize:async()=>{if(++checks===2)throw Error('revoked');}}),/revoked/);assert(!f.calls.some(c=>c.args[1]==='start'));assert(f.calls.some(c=>c.args[1]==='rm'));
});
test('real Linux verifier refuses outside access, credentials, network and workspace writes',{
  skip:process.platform!=='linux'||!process.env.KOTODAMA_TEST_VERIFIER_IMAGE?'requires the explicitly prepared Linux Docker fixture':false,timeout:30000
},async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-container-test-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const outside=path.join(dir,'host-only.txt'),workspace=path.join(dir,'workspace');const {mkdir}=await import('node:fs/promises');await mkdir(workspace);await writeFile(outside,'host-only fixture');await writeFile(path.join(workspace,'input.txt'),'preserve');
  const v=new DockerVerifier({kind:'docker',image:process.env.KOTODAMA_TEST_VERIFIER_IMAGE});await v.preflight();
  const code=`const fs=require('node:fs'),assert=require('node:assert/strict'),os=require('node:os');assert.throws(()=>fs.readFileSync(process.argv[1]));assert.throws(()=>fs.writeFileSync('/workspace/input.txt','changed'));assert.throws(()=>fs.writeFileSync('/outside.txt','changed'));assert.equal(process.env.HOME,'/tmp');assert.equal(process.env.CODEX_HOME,undefined);assert.equal(process.env.OPENAI_API_KEY,undefined);assert(!fs.existsSync('/var/run/docker.sock'));assert(Object.keys(os.networkInterfaces()).every(k=>k==='lo'));fs.writeFileSync('/tmp/probe','ok');assert.equal(fs.readFileSync('/workspace/input.txt','utf8'),'preserve');console.log('isolation probe passed');`;
  const result=await v.verify({executable:'node',args:['-e',code,outside]},{cwd:workspace,timeoutMs:10000});assert.equal(result.code,0,result.stderr);assert.equal(result.isolation.cleanupConfirmed,true);assert.equal(await readFile(outside,'utf8'),'host-only fixture');assert.equal(await readFile(path.join(workspace,'input.txt'),'utf8'),'preserve');
  // The receipt is useful CI evidence but contains no host paths or secrets.
  console.log(JSON.stringify({verificationFixture:result.isolation}));
  await assert.rejects(v.verify({executable:'node',args:['-e','setInterval(()=>{},1000)']},{cwd:workspace,timeoutMs:500}),e=>['COMMAND_TIMEOUT','CHILD_PROCESS_REMAINS'].includes(e.code));
  const remaining=await runCommand('docker',['container','ls','--all','--quiet','--filter','label=org.kotodama.verification-owner']);assert.equal(remaining.code,0);assert.equal(remaining.stdout.trim(),'');
});
