import path from 'node:path';
import {mkdir,lstat} from 'node:fs/promises';
import {runCommand} from './command.mjs';
import {readArtifact} from './artifact.mjs';
import {CliWorker} from './worker.mjs';
import {check,digest,inside,roomKey,uid,errorCode,Refused,safePath} from './common.mjs';

async function exists(file){try{await lstat(file);return true;}catch(error){if(error.code==='ENOENT')return false;throw error;}}
async function git(cwd,args,signal){
  const result=await runCommand('git',['-c','core.fsmonitor=false',...args],{cwd,signal,timeoutMs:30000,maxBytes:4000000});
  check(result.code===0,'CHANNEL_WORKSPACE_GIT_FAILED');return result.stdout;
}
export async function workspaceSnapshot(cwd,{signal,maxBytes=20000000}={}){
  const head=(await git(cwd,['rev-parse','HEAD'],signal)).trim();
  const status=await git(cwd,['status','--porcelain=v1','--untracked-files=all','-z'],signal);
  const diff=await git(cwd,['diff','--no-ext-diff','--no-textconv','--binary','HEAD'],signal);
  const unpublished=await git(cwd,['rev-list','HEAD','--not','--remotes'],signal);
  const names=(await git(cwd,['ls-files','--others','--exclude-standard','-z'],signal)).split('\0').filter(Boolean).sort();
  check(names.length<=2000,'CHANNEL_WORKSPACE_INSPECTION_LIMIT');let total=0;const untracked=[];
  for(const name of names){
    const file=await safePath(cwd,name),bytes=await readArtifact(file,Math.min(maxBytes-total,5000000));
    total+=bytes.length;check(total<=maxBytes,'CHANNEL_WORKSPACE_INSPECTION_LIMIT');untracked.push({name,sha256:digest(bytes)});
  }
  return {head,dirty:Boolean(status),statusSha256:digest(status),diffSha256:digest(diff),untrackedSha256:digest(untracked),unpublishedSha256:digest(unpublished)};
}

// These are local resource leases. Task state remains in the configured owner.
export class ChannelWorkspaceWorker {
  constructor({config,store,ownerId,policy=()=>config,now=()=>Date.now(),workerFactory=cfg=>new CliWorker(cfg),
    schedule=setTimeout,cancel=clearTimeout,snapshot=workspaceSnapshot}){
    Object.assign(this,{config,store,ownerId,policy,now,workerFactory,schedule,cancel,snapshot});
    this.config=structuredClone(config);
    this.binding=digest({workspace:config.worker.workspace,channels:config.worker.channelWorkspaces});this.active=new Map();
    check(store.lock()?.owner===ownerId,'CHANNEL_WORKSPACE_OWNER_REQUIRED');
    store.db.exec('CREATE TABLE IF NOT EXISTS channel_workspaces(room TEXT PRIMARY KEY,body TEXT NOT NULL)');
  }
  scope(source){
    const current=this.policy();check(this.store.lock()?.owner===this.ownerId,'CHANNEL_WORKSPACE_OWNER_CHANGED');
    check(digest({workspace:current.worker.workspace,channels:current.worker.channelWorkspaces})===this.binding,'CHANNEL_WORKSPACE_CONFIG_CHANGED');
    check(source?.provider==='discord'&&source.guildId===current.discord.guildId&&current.worker.channelWorkspaces.channelIds.includes(source.channelId),'CHANNEL_WORKSPACE_SCOPE_REQUIRED');
    return roomKey(source.guildId,source.channelId);
  }
  key(room){return JSON.stringify([room,this.config.worker.channelWorkspaces.generation]);}
  read(room){const row=this.store.db.prepare('SELECT body FROM channel_workspaces WHERE room=?').get(this.key(room));return row?JSON.parse(row.body):null;}
  save(room,value){this.store.db.prepare('INSERT INTO channel_workspaces VALUES(?,?) ON CONFLICT(room) DO UPDATE SET body=excluded.body').run(this.key(room),JSON.stringify(value));}
  status(){
    return this.store.db.prepare('SELECT room,body FROM channel_workspaces ORDER BY room').all().map(row=>{
      const value=JSON.parse(row.body);
      return {roomRef:digest(value.room),generation:value.generation,state:value.state==='ready'&&this.now()>=value.expiresAt?'closed':value.state,
        expiresAt:new Date(value.expiresAt).toISOString(),active:Boolean(value.activeRun),reason:value.reason??null};
    });
  }
  async reconcile(room,{signal,authorize=async()=>{}}={}){
    let value=this.read(room);
    signal=AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(30000)]);
    try{
    const source=await this.snapshot(this.config.worker.workspace,{signal});
    check(!source.dirty,'CHANNEL_WORKSPACE_BASE_DIRTY');
    const expectedPath=await safePath(this.config.dataDir,path.join('channel-workspaces',digest(this.key(room))),{mustExist:false});
    if(value){
      check(['ready','needs_reconciliation'].includes(value.state)&&!value.activeRun,'CHANNEL_WORKSPACE_RECOVERY_REQUIRED');
      check(value.path===expectedPath,'CHANNEL_WORKSPACE_BINDING_CHANGED');
      check(digest(source)===digest(value.source),'CHANNEL_WORKSPACE_BASE_CHANGED');
      await safePath(this.config.dataDir,path.relative(this.config.dataDir,value.path));
      check(digest(await this.snapshot(value.path,{signal}))===digest(value.checkpoint),'CHANNEL_WORKSPACE_CHANGED');
      for(const previous of value.candidates){
        await safePath(this.config.dataDir,path.relative(this.config.dataDir,previous.path));
        check(digest(await this.snapshot(previous.path,{signal}))===digest(previous.checkpoint),'CHANNEL_WORKSPACE_CANDIDATE_CHANGED');
      }
    }else{
      const target=expectedPath;
      for(const row of this.store.db.prepare('SELECT body FROM channel_workspaces').all()){
        const previous=JSON.parse(row.body);
        check(previous.room!==room||!previous.activeRun&&!['creating','uncertain'].includes(previous.state),'CHANNEL_WORKSPACE_RECOVERY_REQUIRED');
      }
      check(!await exists(target),'CHANNEL_WORKSPACE_PATH_OCCUPIED');
      await authorize();check(!signal.aborted,'CANCELLED');
      await mkdir(path.dirname(target),{recursive:true,mode:0o700});
      value={room,generation:this.config.worker.channelWorkspaces.generation,path:target,source,state:'creating',activeRun:null,candidates:[],expiresAt:this.now(),checkpoint:null};
      this.store.transaction(()=>{check(!this.read(room),'CHANNEL_WORKSPACE_BUSY');this.save(room,value);});
      await git(this.config.worker.workspace,['worktree','add','--detach',target,source.head],signal);
      value.checkpoint=await this.snapshot(target,{signal});check(!value.checkpoint.dirty&&value.checkpoint.head===source.head,'CHANNEL_WORKSPACE_CREATE_UNCONFIRMED');
      value.state='ready';this.save(room,value);
    }
    check(value.candidates.length<128,'CHANNEL_WORKSPACE_CAPACITY');
    await authorize();check(!signal.aborted,'CANCELLED');
    if(this.now()>=value.expiresAt)value.expiresAt=this.now()+this.config.worker.channelWorkspaces.maxAgeSeconds*1000;
    value.state='ready';value.reason=null;
    this.save(room,value);return value;
    }catch(error){if(value&&value.state==='ready'){value.state='needs_reconciliation';value.reason=errorCode(error);this.save(room,value);}throw error;}
  }
  async run(task,context,options={}){
    const source=context.find(item=>item.key===task.source_key)??context[0],room=this.scope(source);
    check(task.room===room&&source.key===task.source_key,'CHANNEL_WORKSPACE_TASK_MISMATCH');
    check(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(task.id)&&Number.isSafeInteger(task.revision)&&task.revision>0,'CHANNEL_WORKSPACE_TASK_PATH');
    check(!this.active.has(room),'CHANNEL_WORKSPACE_BUSY');
    const active={id:uid('workspace-run'),controller:new AbortController(),value:null};this.active.set(room,active);
    let timer,uncertain=false,failureCode=null;
    const signal=options.signal?AbortSignal.any([options.signal,active.controller.signal]):active.controller.signal;
    try{
      await options.authorize?.();check(!signal.aborted,'CANCELLED');
      const value=await this.reconcile(room,{signal,authorize:async()=>{this.scope(source);await options.authorize?.();}});active.value=value;value.activeRun=active.id;this.save(room,value);
      const guard=async()=>{
        this.scope(source);check(!signal.aborted,'CANCELLED');
        check(this.active.get(room)===active&&this.read(room)?.activeRun===active.id,'CHANNEL_WORKSPACE_LEASE_CHANGED');
        check(this.now()<value.expiresAt,'CHANNEL_WORKSPACE_EXPIRED');await options.authorize?.();
        check(this.now()<value.expiresAt&&!signal.aborted,'CHANNEL_WORKSPACE_EXPIRED');
      };
      timer=this.schedule(()=>active.controller.abort(new Refused('CHANNEL_WORKSPACE_EXPIRED')),Math.max(0,Math.min(this.config.worker.channelWorkspaces.maxAgeSeconds*1000,value.expiresAt-this.now())));timer?.unref?.();
      await guard();
      const scoped={...this.config,worker:{...this.config.worker,workspace:value.path}};
      const result=await this.workerFactory(scoped).run(task,context,{...options,signal,authorize:guard});
      await guard();
      check(digest(await this.snapshot(value.path,{signal}))===digest(value.checkpoint),'CHANNEL_WORKSPACE_CHANGED');
      await guard();
      return {...result,channelWorkspace:{roomRef:digest(room),generation:value.generation,kind:'git_worktree',baseRevision:value.source.head,expiresAt:new Date(value.expiresAt).toISOString(),directoryIsSandbox:false}};
    }catch(error){failureCode=errorCode(error);uncertain=failureCode==='STOP_UNCONFIRMED';throw error;}
    finally{
      if(timer)this.cancel(timer);
      const value=active.value;
      if(value){
        try{
          const candidate=path.join(this.config.dataDir,'worktrees',`${task.id}-r${task.revision}`);
          check(inside(path.join(this.config.dataDir,'worktrees'),candidate),'CHANNEL_WORKSPACE_TASK_PATH');
          if(await exists(candidate)){
            await safePath(this.config.dataDir,path.relative(this.config.dataDir,candidate));
            const checkpoint=await this.snapshot(candidate);
            if(!value.candidates.some(item=>item.path===candidate))value.candidates.push({path:candidate,checkpoint});
          }
          if(!uncertain)value.activeRun=null;
          value.state=uncertain?'uncertain':failureCode?.startsWith('CHANNEL_WORKSPACE_')?'needs_reconciliation':'ready';value.reason=failureCode;this.save(room,value);
        }catch{value.state='uncertain';value.reason='WORKSPACE_CHECKPOINT_UNCONFIRMED';this.save(room,value);}
      }
      this.active.delete(room);
    }
  }
  async close(){for(const active of this.active.values())active.controller.abort();}
}
