import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,mkdir} from 'node:fs/promises';
import {createServer} from 'node:net';
import path from 'node:path';
import os from 'node:os';
import {verificationPlan,runVerification,requireVerification} from '../src/verification.mjs';

const linux={skip:process.platform!=='linux'};
async function workspace(t){const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-verification-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}
const command={executable:'/bin/true',args:[]};
test('verification uses fixed namespace and mount policy',linux,async t=>{
  const cwd=await workspace(t),plan=await verificationPlan(command,{cwd});assert.equal(plan.executable,'bwrap');
  for(const flag of ['--unshare-all','--unshare-user','--die-with-parent','--new-session','--clearenv'])assert(plan.args.includes(flag));
  assert(!plan.args.includes('--share-net'));assert(!plan.args.includes('--bind'));
  assert.deepEqual(Object.keys(plan.options.env).sort(),['LANG','PATH']);assert.equal(plan.options.cwd,'/');
  assert(plan.args.includes('/workspace'));assert(!plan.args.includes(process.env.HOME));
});
test('verification refuses ambient host mounts and invalid commands',linux,async t=>{
  const cwd=await workspace(t);for(const root of ['/',os.homedir(),'/etc','/opt/../tmp'])await assert.rejects(verificationPlan(command,{cwd,runtimeRoots:[root]}),/VERIFICATION_RUNTIME_ROOT_INVALID/);
  await assert.rejects(verificationPlan(command,{cwd:'/usr'}),/VERIFICATION_WORKSPACE_OVERLAP/);
  await assert.rejects(verificationPlan({executable:'a\0b',args:[]},{cwd}),/COMMAND_INVALID/);
});
test('write preflight requires actual verification commands',async()=>{let ran=0;await assert.rejects(requireVerification({verify:[],workspace:'.'},{runner:async()=>{ran++;}}),/WRITE_VERIFICATION_REQUIRED/);assert.equal(ran,0);});
test('failed sandbox preflight never switches to a host command',linux,async t=>{
  const cwd=await workspace(t),calls=[];await assert.rejects(requireVerification({workspace:cwd,verify:[command]},{runner:async(executable)=>{calls.push(executable);return {code:1};}}),/VERIFICATION_SANDBOX_UNAVAILABLE/);assert.deepEqual(calls,['bwrap']);
});
test('unavailable sandbox command never retries the untrusted command directly',linux,async t=>{
  const cwd=await workspace(t),calls=[];
  await assert.rejects(runVerification(command,{cwd,runner:async(executable)=>{calls.push(executable);throw Error('fixture unavailable');}}),/fixture unavailable/);
  assert.deepEqual(calls,['bwrap']);
});
test('verification propagates failure and owned-process observation',linux,async t=>{
  const cwd=await workspace(t),events=[];const result=await runVerification(command,{cwd,onStart:e=>events.push(e),runner:async(executable,args,options)=>{assert.equal(executable,'bwrap');options.onStart({pid:123,groupOwned:true});return {code:7,stdout:'',stderr:''};}});
  assert.equal(result.code,7);assert.equal(events[0].phase,'verification');assert.equal(events[0].sandbox,'bubblewrap');
});
test('already cancelled verification cannot start a process',async()=>{
  const c=new AbortController();c.abort();let ran=false;await assert.rejects(runVerification(command,{signal:c.signal,runner:async()=>{ran=true;}}),/CANCELLED/);assert.equal(ran,false);
});
test('real Linux verification isolation with a disposable workspace',{
  skip:process.platform!=='linux'||process.env.KOTODAMA_REQUIRE_SANDBOX_TEST!=='1'
},async t=>{
  const root=await workspace(t),cwd=path.join(root,'work');await mkdir(cwd);await writeFile(path.join(cwd,'input'),'fixture');
  const outside=path.join(root,'outside');await writeFile(outside,'synthetic private fixture');
  const server=createServer(socket=>socket.end());await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
  const script=[
    'import os, socket, sys',
    'assert open("/workspace/input").read() == "fixture"',
    'assert not os.path.exists(sys.argv[1])',
    'assert os.environ["HOME"] == "/tmp"',
    'try:\n open("/workspace/changed", "w"); raise AssertionError("workspace was writable")\nexcept OSError: pass',
    's=socket.socket(); s.settimeout(0.2)',
    'try:\n s.connect(("127.0.0.1",int(sys.argv[2]))); raise AssertionError("host network reachable")\nexcept OSError: pass\nfinally: s.close()',
    'open("/tmp/scratch", "w").write("scratch")'
  ].join('\n');
  const result=await runVerification({executable:'/usr/bin/python3',args:['-c',script,outside,String(server.address().port)]},{cwd,timeoutMs:15000});
  assert.equal(result.code,0,result.stderr);
});

test('write worker refuses an unconfigured verifier before creating work state',linux,async t=>{
  const {CliWorker}=await import('../src/worker.mjs');const root=await workspace(t),dataDir=path.join(root,'data');
  const worker=new CliWorker({dataDir,worker:{workspace:root,actions:['develop'],verify:[]}});
  await assert.rejects(worker.run({id:'fixture-task',revision:1,action:'develop'},[]),/WRITE_VERIFICATION_REQUIRED/);
  const {access}=await import('node:fs/promises');await assert.rejects(access(dataDir),{code:'ENOENT'});
});
