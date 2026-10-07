import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Store} from '../src/store.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
import {ChannelWorkspaceWorker,workspaceSnapshot} from '../src/channel-workspaces.mjs';
import {runCommand} from '../src/command.mjs';
import {digest,roomKey,Refused,inside} from '../src/common.mjs';
import {fileURLToPath} from 'node:url';
import {startRuntime,controlCommand} from '../src/runtime.mjs';

const channels=['100000000000000003','100000000000000005'];
async function git(cwd,args){const result=await runCommand('git',args,{cwd,timeoutMs:15000});assert.equal(result.code,0,result.stderr);return result.stdout.trim();}
async function fixture(t){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-channel-work-')),repo=path.join(root,'repo'),data=path.join(root,'data');await mkdir(repo);
  await git(repo,['init','-q']);await git(repo,['config','core.autocrlf','false']);await git(repo,['config','user.name','Synthetic']);await git(repo,['config','user.email','synthetic@example.invalid']);
  await writeFile(path.join(repo,'source.txt'),'initial\n');await git(repo,['add','source.txt']);await git(repo,['commit','-qm','initial']);
  const config=Config.parse({...exampleConfig({workspace:repo}),dataDir:data,worker:{...exampleConfig({workspace:repo}).worker,channelWorkspaces:{channelIds:channels,maxAgeSeconds:60}}});
  const store=new Store(data);store.claimHost('workspace-owner',process.pid,new Date().toISOString());let clock=0;
  const timers=[],seen=[],behavior={run:async()=>({state:'needs_review',summary:'fixture',artifacts:[]})};
  const factory=scoped=>({run:async(task,context,options)=>{seen.push({scoped,task,options});return behavior.run(task,context,options,scoped);}});
  const manager=new ChannelWorkspaceWorker({config,store,ownerId:'workspace-owner',now:()=>clock,workerFactory:factory,
    schedule:(fn,delay)=>{const timer={fn,delay,unref(){}};timers.push(timer);return timer;},cancel:timer=>{timer.cancelled=true;}});
  const source=channel=>({key:'source-'+channel,provider:'discord',guildId:config.discord.guildId,channelId:channel,actorId:config.discord.operators[0]});
  let serial=0;
  const run=(channel=channels[0],options={})=>{const input=source(channel);return manager.run({id:'task-'+(++serial),revision:1,room:roomKey(input.guildId,channel),source_key:input.key,action:'research'},[input],{authorize:async()=>{},...options});};
  t.after(async()=>{await manager.close();store.close();assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});});
  return {root,repo,data,store,config,manager,timers,seen,behavior,source,run,advance:ms=>{clock+=ms;}};
}

test('channels receive different real worktrees and keep the existing Task result owner',async t=>{
  const f=await fixture(t),first=await f.run(channels[0]),second=await f.run(channels[1]);
  const [a,b]=f.seen.map(row=>row.scoped.worker.workspace);assert.notEqual(a,b);assert.notEqual(a,f.repo);
  assert.equal(await readFile(path.join(a,'source.txt'),'utf8'),'initial\n');assert.equal(await git(a,['rev-parse','HEAD']),await git(f.repo,['rev-parse','HEAD']));
  assert.equal(first.channelWorkspace.directoryIsSandbox,false);assert.equal(second.channelWorkspace.kind,'git_worktree');
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS count FROM tasks').get().count,0);
  assert.equal(f.config.worker.workspace,f.repo);assert.equal(f.seen[0].scoped.dataDir,f.data);
});

test('a live lease does not slide its expiry and an expired lease reconciles before reuse',async t=>{
  const f=await fixture(t);const first=await f.run();f.advance(30000);const second=await f.run();
  assert.equal(first.channelWorkspace.expiresAt,second.channelWorkspace.expiresAt);
  f.advance(31000);assert.equal(f.manager.status()[0].state,'closed');const resumed=await f.run();
  assert.notEqual(resumed.channelWorkspace.expiresAt,first.channelWorkspace.expiresAt);assert.equal(f.seen[0].scoped.worker.workspace,f.seen[2].scoped.worker.workspace);
});

test('expiry cancels only the owned active worker and prevents a late successful result',async t=>{
  const f=await fixture(t);let started;const ready=new Promise(resolve=>{started=resolve;});
  f.behavior.run=async(_task,_context,options)=>new Promise((resolve,reject)=>{started();options.signal.addEventListener('abort',()=>reject(new Refused('CANCELLED')),{once:true});});
  const running=f.run(),rejected=assert.rejects(running,{code:'CANCELLED'});await ready;f.advance(61000);f.timers[0].fn();await rejected;
  assert.equal(f.manager.active.size,0);assert.equal(f.manager.status()[0].active,false);
  f.behavior.run=async()=>({state:'needs_review',artifacts:[]});await f.run(channels[1]);
});

test('expiry during final checkpoint readback does not return a successful result',async t=>{
  const f=await fixture(t);let completed=false;
  f.behavior.run=async()=>{completed=true;return {state:'needs_review',artifacts:[]};};
  const snapshot=f.manager.snapshot;
  f.manager.snapshot=async(...args)=>{const value=await snapshot(...args);if(completed)f.advance(61000);return value;};
  await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_EXPIRED'});
});

test('a changed base or dirty channel worktree blocks resume without resetting files',async t=>{
  const f=await fixture(t);await f.run();const directory=f.seen[0].scoped.worker.workspace;
  await writeFile(path.join(directory,'source.txt'),'user change\n');f.advance(61000);
  await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_CHANGED'});assert.equal(await readFile(path.join(directory,'source.txt'),'utf8'),'user change\n');
  assert.equal(f.seen.length,1);await writeFile(path.join(directory,'source.txt'),'initial\n');
  await writeFile(path.join(f.repo,'source.txt'),'new base\n');await git(f.repo,['add','source.txt']);await git(f.repo,['commit','-qm','new base']);
  await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_BASE_CHANGED'});assert.equal(f.seen.length,1);
});

test('candidate checkpoints include untracked bytes and reject changes before another run',async t=>{
  const f=await fixture(t);let candidate;
  f.behavior.run=async task=>{candidate=path.join(f.data,'worktrees',`${task.id}-r${task.revision}`);await mkdir(path.dirname(candidate),{recursive:true});await git(f.repo,['worktree','add','--detach',candidate,'HEAD']);await writeFile(path.join(candidate,'draft.txt'),'first\n');return {state:'needs_review',workspace:candidate,artifacts:[]};};
  await f.run();const before=await workspaceSnapshot(candidate);await writeFile(path.join(candidate,'draft.txt'),'second\n');const after=await workspaceSnapshot(candidate);
  assert.equal(before.statusSha256,after.statusSha256);assert.notEqual(before.untrackedSha256,after.untrackedSha256);
  f.advance(61000);await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_CANDIDATE_CHANGED'});assert.equal(f.seen.length,1);
});

test('uncertain process shutdown stays blocked across manager restart',async t=>{
  const f=await fixture(t);f.behavior.run=async()=>{throw new Refused('STOP_UNCONFIRMED');};
  await assert.rejects(f.run(),{code:'STOP_UNCONFIRMED'});assert.equal(f.manager.status()[0].state,'uncertain');
  const restarted=new ChannelWorkspaceWorker({config:f.config,store:f.store,ownerId:'workspace-owner'}),source=f.source(channels[0]);
  await assert.rejects(restarted.run({id:'task-restart',revision:1,room:roomKey(source.guildId,source.channelId),source_key:source.key,action:'research'},[source]),{code:'CHANNEL_WORKSPACE_RECOVERY_REQUIRED'});
  f.config.worker.channelWorkspaces.generation='fresh';
  const fresh=new ChannelWorkspaceWorker({config:f.config,store:f.store,ownerId:'workspace-owner'});
  await assert.rejects(fresh.run({id:'task-fresh',revision:1,room:roomKey(source.guildId,source.channelId),source_key:source.key,action:'research'},[source]),{code:'CHANNEL_WORKSPACE_RECOVERY_REQUIRED'});
});

test('an explicit new generation preserves prior work while using the approved new base',async t=>{
  const f=await fixture(t);await f.run();const old=f.seen[0].scoped.worker.workspace;
  await writeFile(path.join(old,'source.txt'),'preserved candidate\n');
  await writeFile(path.join(f.repo,'source.txt'),'new approved base\n');await git(f.repo,['add','source.txt']);await git(f.repo,['commit','-qm','new base']);
  f.config.worker.channelWorkspaces.generation='next';let directory;
  const fresh=new ChannelWorkspaceWorker({config:f.config,store:f.store,ownerId:'workspace-owner',workerFactory:scoped=>({run:async()=>{directory=scoped.worker.workspace;return {state:'needs_review',artifacts:[]};}})});
  const source=f.source(channels[0]);await fresh.run({id:'task-next',revision:1,room:roomKey(source.guildId,source.channelId),source_key:source.key,action:'research'},[source]);
  assert.notEqual(directory,old);assert.equal(await readFile(path.join(old,'source.txt'),'utf8'),'preserved candidate\n');
  assert.equal(await readFile(path.join(directory,'source.txt'),'utf8'),'new approved base\n');assert.equal(fresh.status().length,2);
});

test('in-progress work cannot be borrowed by another run and policy changes stop use',async t=>{
  const f=await fixture(t);let complete,started;const ready=new Promise(resolve=>{started=resolve;});
  f.behavior.run=async(_task,_context,options)=>{started();await new Promise(resolve=>{complete=resolve;});await options.authorize();return {state:'needs_review',artifacts:[]};};
  const running=f.run(),rejected=assert.rejects(running,{code:'CHANNEL_WORKSPACE_CONFIG_CHANGED'});await ready;
  await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_BUSY'});f.config.worker.channelWorkspaces.channelIds=[channels[1]];complete();await rejected;
});

test('unconfigured channels, task path injection and dirty base are refused before a worker starts',async t=>{
  const f=await fixture(t);assert.equal(exampleConfig().worker.channelWorkspaces,undefined);
  await assert.rejects(f.run('100000000000000099'),{code:'CHANNEL_WORKSPACE_SCOPE_REQUIRED'});
  const source=f.source(channels[0]);await assert.rejects(f.manager.run({id:'../escape',revision:1,room:roomKey(source.guildId,source.channelId),source_key:source.key},[source]),{code:'CHANNEL_WORKSPACE_TASK_PATH'});
  await writeFile(path.join(f.repo,'uncommitted.txt'),'preserve\n');await assert.rejects(f.run(),{code:'CHANNEL_WORKSPACE_BASE_DIRTY'});assert.equal(f.seen.length,0);
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS count FROM channel_workspaces').get().count,0);
});

test('a channel cannot reuse a different channel path recorded in a corrupted lease',async t=>{
  const f=await fixture(t);await f.run(channels[0]);await f.run(channels[1]);
  const a=roomKey(f.config.discord.guildId,channels[0]),b=roomKey(f.config.discord.guildId,channels[1]);
  const value=f.manager.read(a);value.path=f.manager.read(b).path;f.manager.save(a,value);
  await assert.rejects(f.run(channels[0]),{code:'CHANNEL_WORKSPACE_BINDING_CHANGED'});assert.equal(f.seen.length,2);
  assert.notEqual(digest(a),digest(b));
});

test('offline HTTP Task execution reaches the real scoped CLI worker and existing result API',async t=>{
  const f=await fixture(t);f.store.releaseHost('workspace-owner');
  const executable=fileURLToPath(new URL('./fixtures/model-cli.mjs',import.meta.url));
  f.config.analyzer={kind:'codex_cli',executable:process.execPath,args:[executable],timeoutSeconds:10};
  Object.assign(f.config.worker,{executable:process.execPath,args:[executable],timeoutSeconds:10});
  const file=path.join(f.root,'runtime-config.json');await writeFile(file,JSON.stringify(f.config));
  const runtime=await startRuntime(file,{offline:true,log:()=>{}});
  try{
    const task=await controlCommand(f.config,{action:'request',actor:f.config.discord.operators[0],operation:'research',text:'合成資料を確認する',requestId:'workspace-fixture'});
    await runtime.pipeline.tail;
    const result=await controlCommand(f.config,{action:'result',actor:f.config.discord.operators[0],taskId:task.id});
    assert.equal(result.state,'needs_review');assert.equal(result.channelWorkspace.kind,'git_worktree');
    assert.equal(result.channelWorkspace.generation,'initial');assert.equal(result.channelWorkspace.directoryIsSandbox,false);
    const status=await controlCommand(f.config,{action:'status'});assert.equal(status.channelWorkspaces.length,1);
    assert.equal(status.taskOwner,'local');assert.equal(runtime.store.tasks(f.config.discord.operators[0]).length,1);
  }finally{await runtime.close();}
});
