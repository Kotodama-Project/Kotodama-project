import http from 'node:http';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {loadConfig} from './config.mjs';
import {Store} from './store.mjs';
import {CliAnalyzer,ResponsesAnalyzer} from './llm.mjs';
import {CliWorker} from './worker.mjs';
import {Pipeline} from './pipeline.mjs';
import {DiscordAdapter} from './discord.mjs';
import {VoiceRoom} from './voice.mjs';
import {voiceCommand} from './voice-control.mjs';
import {RemoteOwner} from './remote-owner.mjs';
import {startBridge} from './bridge.mjs';
import {atomicJson,check,uid,errorCode,redact} from './common.mjs';

export async function startRuntime(filename,{offline=false,analyzer,worker,log=value=>console.log(JSON.stringify(redact(value)))}={}){
  const config=await loadConfig(filename);let current=config;const store=new Store(config.dataDir),ownerId=uid('host'),startedAt=new Date().toISOString();
  let owner,claimed=false;
  try{owner=config.owner.kind==='remote'?new RemoteOwner(config.owner):store;check(!store.lock(),'RUNTIME_ALREADY_OWNED');store.claimHost(ownerId,process.pid,startedAt);claimed=true;store.reconcileInterrupted();}catch(e){if(claimed)store.releaseHost(ownerId);store.close();throw e;}
  let discord,voice,bridge,control,policyTimer,closing=false;
  const authorize=async(task,purpose='execute')=>{const c=await loadConfig(filename);check(c.discord.operators.includes(task.actor)&&(purpose!=='execute'||[task.action,...(task.requiredActions??[])].every(action=>c.worker.actions.includes(action))),'GRANT_REVOKED');check(c.worker.workspace===config.worker.workspace&&c.owner.kind===config.owner.kind,'WORKSPACE_BINDING_CHANGED');if(discord&&!offline){await discord.member(task.actor);const keys=new Set([task.source_key,...(task.contextSources??[]).map(b=>b.key)]);for(const key of keys){const source=store.source(key,task.actor);if(source.provider==='discord'){const channel=await discord.client.channels.fetch(source.channelId);check(await discord.canRead(channel,task.actor),'SOURCE_ACCESS_DENIED');}}}if(owner.kind==='remote'){const s=await owner.source(task.source_key,task.actor);check(s.revision===task.source_revision,'REMOTE_SOURCE_CHANGED');}};
  const selectedAnalyzer=analyzer??(config.analyzer.kind==='responses'?new ResponsesAnalyzer(config):new CliAnalyzer(config));
  const pipeline=new Pipeline({store,owner,config,analyzer:selectedAnalyzer,worker:worker??new CliWorker(config),authorize,onTask:async task=>{if(discord)await discord.deliver(task);},onReply:async reply=>{if(discord)await discord.reply(reply);},onVoiceAction:async action=>{if(discord)await discord.voiceAction(action);},onError:code=>log({event:'operation_failed',code})});
  try{
    if(!offline){discord=new DiscordAdapter({config,store,pipeline,policy:()=>current,onError:code=>log({event:'discord',code})});await discord.login();if(config.discord.voiceChannelId){voice=new VoiceRoom({client:discord.client,config,store,pipeline,policy:()=>current,sourceReaders:async()=>{const channel=await discord.client.channels.fetch(config.discord.voiceChannelId,{force:true});const candidates=new Set([...current.discord.operators,...voice.audience().filter(id=>voice.allowed(id))]);const readers=[];for(const actor of candidates)if(await discord.canRead(channel,actor))readers.push(actor);return readers;},onError:code=>log({event:'voice',code})});discord.voice=voice;}}
    voice?.control.start();
    const secret=randomBytes(32).toString('hex');const secretFile=path.join(config.dataDir,'control.secret');await writeFile(secretFile,secret,{encoding:'utf8',mode:0o600});
    control=http.createServer(async(req,res)=>{
      const send=(status,body)=>{res.writeHead(status,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});res.end(JSON.stringify(body));};
      try{
        const auth=String(req.headers.authorization??''),expected='Bearer '+secret;check(auth.length===expected.length&&timingSafeEqual(Buffer.from(auth),Buffer.from(expected)),'UNAUTHORIZED');
        if(req.method==='GET'&&req.url==='/v1/status'){send(200,{ownerId,pid:process.pid,startedAt,discord:discord?'connected':'offline_fixture',voice:voice?.control.status()??null,taskOwner:config.owner.kind});return;}
        check(req.method==='POST'&&req.url==='/v1/command','ROUTE_NOT_FOUND');check(!closing,'RUNTIME_STOPPING');const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;check(size<=200000,'CONTROL_BODY_LIMIT');chunks.push(chunk);}
        const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));current=await loadConfig(filename);check(current.discord.operators.includes(input.actor),'OPERATOR_REQUIRED');
        let result;
        if(input.action==='tasks'){result=[];for(const task of await owner.tasks(input.actor))try{await authorize(task,'read_result');result.push(task);}catch{}}
        else if(input.action==='result')result=await pipeline.result(input.taskId,input.actor);
        else if(input.action==='stop'){await pipeline.stop(input.taskId,input.actor);result={state:'stop_requested'};}
        else if(input.action==='resume')result=await pipeline.resume(input.taskId,input.actor);
        else if(input.action==='voice'){check(voice,'VOICE_NOT_CONFIGURED');result=await voiceCommand(voice,input.mode);}
        else if(input.action==='request'){check(typeof input.text==='string'&&input.text.trim()&&input.text.length<=16000,'REQUEST_INVALID');const source={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:input.requestId??uid('cli'),actorId:input.actor,revision:1,final:true,readers:[input.actor],text:input.text,metadata:{kind:'trusted_cli'}};result=await pipeline.request(source,{title:input.text.slice(0,120),request:input.text,action:input.operation,acceptance:input.acceptance??[]});}
        else if(input.action==='shutdown'){result={state:'stopping'};setImmediate(()=>close());}
        else throw new Error('UNKNOWN_COMMAND');send(200,{ok:true,result});
      }catch(e){send(errorCode(e)==='UNAUTHORIZED'?401:400,{ok:false,error:errorCode(e)});}
    });
    await new Promise((resolve,reject)=>{control.once('error',reject);control.listen(0,'127.0.0.1',resolve);});
    if(config.bridge.enabled)bridge=await startBridge({config,store,pipeline,readConfig:()=>loadConfig(filename),onImported:receipt=>discord?discord.notifyLumaImport(receipt,{readConfig:()=>loadConfig(filename)}):{state:'unavailable'}});
    const runtime={ownerId,pid:process.pid,startedAt,port:control.address().port,secretFile,configFile:path.resolve(filename),offline};await atomicJson(path.join(config.dataDir,'runtime.json'),runtime);
    let checking=false;policyTimer=setInterval(async()=>{if(checking||closing)return;checking=true;try{const previous=current;try{current=await loadConfig(filename);}catch{current={...config,discord:{...config.discord,operators:[],consentingUsers:[]},voice:{...config.voice,consentMode:'owner_managed',participantIds:[]}};log({event:'policy_unavailable'});}if(JSON.stringify(previous)!==JSON.stringify(current))void voice?.control.check();for(const [id,run]of pipeline.active){try{const task=await owner.taskInternal(id);check(task.revision===run.revision&&task.state==='running','TASK_CHANGED');await owner.assertContext(id,task.actor);await authorize(task);}catch{run.controller.abort();}}}finally{checking=false;}},1000);policyTimer.unref();
    log({event:'runtime_ready',pid:process.pid,port:runtime.port,discord:offline?'offline_fixture':'connected',voice:'not_joined',taskOwner:config.owner.kind});
  }catch(e){await pipeline.close();await discord?.close();control?.close();bridge?.close();store.releaseHost(ownerId);store.close();throw e;}
  async function close(){if(closing)return;closing=true;pipeline.draining=true;clearInterval(policyTimer);await discord?.close();await pipeline.close();await new Promise(resolve=>bridge?bridge.close(resolve):resolve());await new Promise(resolve=>control?control.close(resolve):resolve());store.releaseHost(ownerId);store.close();log({event:'runtime_stopped',ownerId});}
  return {config,store,owner,pipeline,discord,voice,close};
}
export async function controlCommand(config,input){const runtime=JSON.parse(await readFile(path.join(config.dataDir,'runtime.json'),'utf8'));const token=await readFile(runtime.secretFile,'utf8');const status=await fetch(`http://127.0.0.1:${runtime.port}/v1/status`,{headers:{authorization:'Bearer '+token},signal:AbortSignal.timeout(3000)});check(status.ok,'RUNTIME_NOT_AVAILABLE');const current=await status.json();check(current.ownerId===runtime.ownerId&&current.pid===runtime.pid&&current.startedAt===runtime.startedAt,'RUNTIME_OWNER_CHANGED');if(input.action==='status')return current;const response=await fetch(`http://127.0.0.1:${runtime.port}/v1/command`,{method:'POST',headers:{authorization:'Bearer '+token,'content-type':'application/json'},body:JSON.stringify(input),signal:AbortSignal.timeout(30000)});const value=await response.json();check(response.ok&&value.ok,value.error??'CONTROL_FAILED');return value.result;}
