import path from 'node:path';
import {mkdtemp,rm,realpath} from 'node:fs/promises';
import os from 'node:os';
import {randomUUID} from 'node:crypto';
import {runCommand} from './command.mjs';
import {check,Refused} from './common.mjs';

export const immutableImage=/^(?:sha256:[a-f0-9]{64}|[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[a-f0-9]{64})$/;
const label='org.kotodama.verification-owner';
const imageId=/^sha256:[a-f0-9]{64}$/;
const containerId=/^[a-f0-9]{64}$/;

export function verificationArgs({image,workspace,owner,command,limits={},uid=process.getuid?.()??65534,gid=process.getgid?.()??65534}){
  check(imageId.test(image),'VERIFICATION_IMAGE_UNPINNED');
  check(path.isAbsolute(workspace)&&!/[\r\n,\x00]/.test(workspace),'VERIFICATION_WORKSPACE_INVALID');
  check(/^verify-[a-f0-9-]{36}$/.test(owner),'VERIFICATION_OWNER_INVALID');
  check(typeof command?.executable==='string'&&/^[A-Za-z0-9_./+-]+$/.test(command.executable)&&!command.executable.startsWith('-')&&Array.isArray(command.args)&&command.args.every(s=>typeof s==='string'&&!s.includes('\0')),'VERIFICATION_COMMAND_INVALID');
  const memoryMb=limits.memoryMb??512,cpus=limits.cpus??1,pidsLimit=limits.pidsLimit??64;
  check(Number.isInteger(memoryMb)&&memoryMb>=128&&memoryMb<=8192&&Number.isFinite(cpus)&&cpus>=0.1&&cpus<=8&&Number.isInteger(pidsLimit)&&pidsLimit>=16&&pidsLimit<=512,'VERIFICATION_LIMIT_INVALID');
  check(Number.isSafeInteger(uid)&&uid>=0&&Number.isSafeInteger(gid)&&gid>=0,'VERIFICATION_USER_INVALID');
  return ['container','create','--pull=never','--name',owner,'--label',`${label}=${owner}`,
    '--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges=true',
    '--pids-limit',String(pidsLimit),'--memory',`${memoryMb}m`,'--memory-swap',`${memoryMb}m`,'--cpus',String(cpus),
    '--init','--no-healthcheck','--restart=no','--log-driver=none','--user',`${uid}:${gid}`,
    '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=67108864,mode=1777',
    '--mount',`type=bind,source=${workspace},target=/workspace,readonly,bind-propagation=rprivate`,
    '--workdir','/workspace','--env','HOME=/tmp','--env','TMPDIR=/tmp','--env','NO_COLOR=1',
    '--entrypoint',command.executable,image,...command.args];
}

// The Docker daemon and preinstalled image are operator-managed trusted inputs.
// Untrusted verification code sees only a read-only candidate and bounded tmpfs.
// No host-command fallback, image pulls, shell concatenation or credential mounts.
export class DockerVerifier{
  constructor(config,{run=runCommand}={}){this.config=config;this.run=run;}
  async client(fn){
    const dir=await mkdtemp(path.join(os.tmpdir(),'kotodama-verifier-client-'));
    try{
      const env={PATH:process.env.PATH??'/usr/bin:/bin',HOME:dir,DOCKER_CONFIG:dir,NO_COLOR:'1'};
      const command=(args,options={})=>this.run(this.config.executable??'docker',args,{cwd:dir,env,timeoutMs:15000,maxBytes:65536,...options});
      return await fn(command);
    }finally{await rm(dir,{recursive:true,force:true});}
  }
  async inspectImage(command,signal){
    check(this.config?.kind==='docker'&&immutableImage.test(this.config.image),'VERIFICATION_ISOLATION_REQUIRED');
    const result=await command(['image','inspect',this.config.image],{signal});check(result.code===0,'VERIFICATION_IMAGE_UNAVAILABLE');
    let image;try{[image]=JSON.parse(result.stdout);}catch{throw new Refused('VERIFICATION_IMAGE_INVALID');}
    check(image&&imageId.test(image.Id)&&image.Os==='linux'&&Object.keys(image.Config?.Volumes??{}).length===0,'VERIFICATION_IMAGE_INVALID');
    if(imageId.test(this.config.image))check(image.Id===this.config.image,'VERIFICATION_IMAGE_CHANGED');
    else check(image.RepoDigests?.includes(this.config.image),'VERIFICATION_IMAGE_CHANGED');
    return image.Id;
  }
  async preflight({signal}={}){
    check(process.platform==='linux','WRITE_WORKER_REQUIRES_LINUX_HOST');
    check(this.config?.kind==='docker'&&immutableImage.test(this.config.image),'VERIFICATION_ISOLATION_REQUIRED');
    return this.client(async command=>({imageId:await this.inspectImage(command,signal)}));
  }
  async verify(commandToRun,{cwd,signal,timeoutMs=300000,authorize=async()=>{}}={}){
    check(Number.isSafeInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=3600000,'VERIFICATION_TIMEOUT_INVALID');
    return this.client(async command=>{
      const image=await this.inspectImage(command,signal),workspace=await realpath(cwd),owner=`verify-${randomUUID()}`;
      const args=verificationArgs({image,workspace,owner,command:commandToRun,limits:this.config});
      let id=null,createAttempted=false;
      const inspect=async ref=>{const result=await command(['container','inspect',ref]);check(result.code===0,'VERIFICATION_CONTAINER_UNAVAILABLE');let value;try{[value]=JSON.parse(result.stdout);}catch{throw new Refused('VERIFICATION_CONTAINER_INVALID');}check(containerId.test(value?.Id)&&value.Config?.Labels?.[label]===owner,'VERIFICATION_OWNER_CHANGED');if(id)check(value.Id===id,'VERIFICATION_OWNER_CHANGED');return value;};
      try{
        await authorize();check(!signal?.aborted,'CANCELLED');createAttempted=true;
        // Creation never starts the payload. Ignore cancellation until its owned
        // ID is known, then recheck authority before starting any candidate code.
        const created=await command(args);check(created.code===0,'VERIFICATION_CREATE_FAILED');
        id=created.stdout.trim();check(containerId.test(id),'VERIFICATION_CONTAINER_INVALID');
        const before=await inspect(id);check(before.Image===image&&!before.State.Running,'VERIFICATION_IMAGE_CHANGED');
        await authorize();check(!signal?.aborted,'CANCELLED');
        const result=await command(['container','start','--attach',id],{signal,timeoutMs,maxBytes:4000000});
        const after=await inspect(id);check(!after.State.Running&&Number.isInteger(after.State.ExitCode),'VERIFICATION_EXIT_UNCONFIRMED');
        await authorize();
        return {...result,code:after.State.ExitCode,isolation:{kind:'docker',imageId:image,containerId:id,network:'none',workspace:'read-only',cleanupConfirmed:true}};
      }finally{
        if(createAttempted){
          // Failure of the CLI, a timeout, or cancellation does not prove that
          // the daemon stopped its container. Cleanup has a separate deadline.
          try{
            const owned=await inspect(id??owner);id=owned.Id;
            const removed=await command(['container','rm','--force','--volumes',id]);check(removed.code===0,'STOP_UNCONFIRMED');
            const remaining=await command(['container','ls','--all','--quiet','--no-trunc','--filter',`id=${id}`]);
            check(remaining.code===0&&!remaining.stdout.trim(),'STOP_UNCONFIRMED');
          }catch{throw new Refused('STOP_UNCONFIRMED');}
        }
      }
    });
  }
}
