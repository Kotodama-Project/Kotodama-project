import path from 'node:path';
import {realpath,lstat} from 'node:fs/promises';
import {check,inside} from './common.mjs';
import {runCommand} from './command.mjs';

const systemRoots=['/usr','/bin','/lib','/lib64'];
const cleanEnv={PATH:'/usr/local/bin:/usr/bin:/bin',LANG:'C.UTF-8'};

// Verification code is untrusted. Never fall back to an ordinary host process.
export async function verificationPlan(command,{cwd,runtimeRoots=[]}={}){
  check(process.platform==='linux','WRITE_WORKER_REQUIRES_LINUX_HOST');
  check(typeof command?.executable==='string'&&command.executable.length>0&&
    !command.executable.includes('\0')&&Array.isArray(command.args)&&
    command.args.every(arg=>typeof arg==='string'&&!arg.includes('\0')),'COMMAND_INVALID');
  check(Array.isArray(runtimeRoots)&&runtimeRoots.length<=8,'VERIFICATION_RUNTIME_ROOT_INVALID');
  const workspace=await realpath(cwd);check(workspace!=='/'&&(await lstat(workspace)).isDirectory(),'VERIFICATION_WORKSPACE_INVALID');
  const extra=[];
  for(const root of runtimeRoots){
    // An operator may expose an installed toolchain, never HOME, data, or /.
    check(typeof root==='string'&&path.isAbsolute(root)&&root.startsWith('/opt/')&&path.normalize(root)===root,'VERIFICATION_RUNTIME_ROOT_INVALID');
    const resolved=await realpath(root);
    check(resolved===root&&(await lstat(root)).isDirectory(),'VERIFICATION_RUNTIME_ROOT_INVALID');
    check(!inside(root,workspace)&&!inside(workspace,root),'VERIFICATION_WORKSPACE_OVERLAP');extra.push(root);
  }
  for(const root of systemRoots)check(!inside(root,workspace)&&!inside(workspace,root),'VERIFICATION_WORKSPACE_OVERLAP');
  const args=['--unshare-all','--unshare-user','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv'];
  for(const root of systemRoots)args.push('--ro-bind-try',root,root);
  for(const root of extra)args.push('--ro-bind',root,root);
  args.push('--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home',
    '--setenv','HOME','/tmp','--setenv','TMPDIR','/tmp','--setenv','LANG','C.UTF-8',
    '--setenv','PATH',[...extra.map(root=>path.join(root,'bin')),cleanEnv.PATH].join(':'),
    '--ro-bind',workspace,'/workspace','--chdir','/workspace','--',command.executable,...command.args);
  return {executable:'bwrap',args,options:{cwd:'/',env:{...cleanEnv}}};
}

export async function runVerification(command,{cwd,runtimeRoots=[],signal,timeoutMs=300000,onStart=()=>{},runner=runCommand}={}){
  check(!signal?.aborted,'CANCELLED');
  const plan=await verificationPlan(command,{cwd,runtimeRoots});
  return runner(plan.executable,plan.args,{...plan.options,signal,timeoutMs,onStart:p=>onStart({...p,phase:'verification',sandbox:'bubblewrap'})});
}

export async function requireVerification(worker,{signal,onStart,runner=runCommand}={}){
  check(Array.isArray(worker.verify)&&worker.verify.length>0,'WRITE_VERIFICATION_REQUIRED');
  const result=await runVerification({executable:'/bin/true',args:[]},{cwd:worker.workspace,
    runtimeRoots:worker.verificationRuntimeRoots??[],signal,onStart,timeoutMs:15000,runner});
  check(result.code===0,'VERIFICATION_SANDBOX_UNAVAILABLE');
}
