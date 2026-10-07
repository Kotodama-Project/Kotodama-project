import {ArchiveRuntime} from './archive-runtime.mjs';
import {recordRetentionReadback} from './retention-readback.mjs';
import http from 'node:http';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import path from 'node:path';
import {loadConfig} from './config.mjs';
import {Store} from './store.mjs';
import {CliAnalyzer,ResponsesAnalyzer} from './llm.mjs';
import {CliWorker,readArtifact} from './worker.mjs';
import {AccessMonitor} from './access-grace.mjs';
import {debugRequested,enableDebugLog,disableDebugLog} from './debug-log.mjs';
import {Pipeline} from './pipeline.mjs';
import {createAnalysisAuthorizer} from './analysis-policy.mjs';
import {DiscordAdapter} from './discord.mjs';
import {VoiceRoom} from './voice.mjs';
import {createVoicePool} from './voice-pool.mjs';
import {VoiceRotation} from './voice-rotation.mjs';
import {deliverRotation} from './rotation-delivery.mjs';
import {voiceCommand} from './voice-control.mjs';
import {RemoteOwner} from './remote-owner.mjs';
import {startBridge} from './bridge.mjs';
import {awaitWithSignal,deadlineScope,readHttpBody,sendHttpJson} from './http-limits.mjs';
import {DotsBridge} from './dots.mjs';
import {atomicJson,atomicText,check,uid,errorCode,redact,Refused} from './common.mjs';
import {consumeBootstrapBinding,registerRuntimeModule} from './source-bootstrap.mjs';
registerRuntimeModule(startRuntime,import.meta.url);

function pidRunning(pid){
  if(!Number.isSafeInteger(pid)||pid<=0)return true;
  try{process.kill(pid,0);return true;}catch(error){return error.code!=='ESRCH';}
}

export async function startRuntime(filename,{offline=false,analyzer,worker,runtimeDomain=process.env.KOTODAMA_RUNTIME_DOMAIN,debug=debugRequested(),sourceBootstrap,log=value=>console.log(JSON.stringify(redact(value)))}={}){
  // Only the cold official CLI can supply a bootstrap-owned one-use record.
  // Direct/cached imports have already loaded code and stay unverified.
  const source=consumeBootstrapBinding(sourceBootstrap,startRuntime);
  if(runtimeDomain==='')runtimeDomain=undefined;
  if(runtimeDomain!==undefined)check(typeof runtimeDomain==='string'&&/^[A-Za-z0-9._:-]{1,128}$/.test(runtimeDomain),'RUNTIME_DOMAIN_INVALID');
  const config=await loadConfig(filename);let current=config;const store=new Store(config.dataDir),ownerId=uid('host'),startedAt=new Date().toISOString();
  if(debug){enableDebugLog(config.dataDir);log({event:'debug_log',state:'enabled',file:'debug.log'});}
  const stopDebug=()=>{if(debug)disableDebugLog();};
  let owner,claimed=false;
  try{owner=config.owner.kind==='remote'?new RemoteOwner(config.owner):store;const stale=store.lock();if(stale){check(Boolean(runtimeDomain)&&stale.domain===runtimeDomain,'RUNTIME_RECOVERY_DOMAIN_MISMATCH');check(!pidRunning(stale.pid),'RUNTIME_ALREADY_OWNED');store.replaceStaleHost(stale,ownerId,process.pid,startedAt,runtimeDomain);}else store.claimHost(ownerId,process.pid,startedAt,runtimeDomain??null);claimed=true;store.reconcileInterrupted();}catch(e){if(claimed)store.releaseHost(ownerId);store.close();stopDebug();throw e;}
  let discord,voice,rotation,archive,archiveTimer,bridge,control,policyTimer,policyWork,dots,closing=false,closePromise,controlClosed,shutdownKeepAlive;
  const controlOperations=new Set(),controlReads=new Set();
  const accessMonitor=new AccessMonitor();
  const stopControl=()=>{
    if(!control)return Promise.resolve();
    // A failed listen leaves no server to drain; other close errors still retain ownership.
    controlClosed??=new Promise((resolve,reject)=>control.close(error=>error&&error.code!=='ERR_SERVER_NOT_RUNNING'?reject(error):resolve()));
    for(const scope of controlReads)scope.abort(new Refused('RUNTIME_STOPPING'));
    control.closeIdleConnections();return controlClosed;
  };
  const authorize=async(task,purpose='execute',{monitor=false}={})=>{const c=await loadConfig(filename);check(!monitor||!closing,'RUNTIME_STOPPING');check(c.discord.operators.includes(task.actor)&&(purpose!=='execute'||[task.action,...(task.requiredActions??[])].every(action=>c.worker.actions.includes(action))),'GRANT_REVOKED');check(c.worker.workspace===config.worker.workspace&&c.owner.kind===config.owner.kind,'WORKSPACE_BINDING_CHANGED');if(discord&&!offline){const channels=[];for(const key of new Set([task.source_key,...(task.contextSources??[]).map(b=>b.key)])){const source=store.source(key,task.actor);if(source.provider==='discord')channels.push(source.channelId);}const access=await discord.actorAccess(task.actor,channels,{cached:monitor});check(!monitor||!closing,'RUNTIME_STOPPING');check(access!=='unavailable','ACCESS_UNAVAILABLE');check(access==='allowed','SOURCE_ACCESS_DENIED');}if(owner.kind==='remote'){const s=await owner.source(task.source_key,task.actor);check(s.revision===task.source_revision,'REMOTE_SOURCE_CHANGED');}};
  const authorizeAnalysis=createAnalysisAuthorizer({readConfig:()=>loadConfig(filename),config,onPolicy:value=>{current=value;},voice:source=>voice?.forSource?voice.forSource(source):voice,discord:()=>discord,owner,offline});
  const selectedAnalyzer=analyzer??(config.analyzer.kind==='responses'?new ResponsesAnalyzer(config):new CliAnalyzer(config));
  const pipeline=new Pipeline({store,owner,config,policy:()=>current,readPolicy:async()=>{current=await loadConfig(filename);return current;},analyzer:selectedAnalyzer,worker:worker??new CliWorker(config),authorize,authorizeAnalysis,onTask:async task=>{if(discord)await discord.deliver(task);},onTaskQueued:async(task,options)=>{if(discord)await discord.acknowledgeTask(task,options);},onReply:async reply=>{if(discord)await discord.reply(reply);},onVoiceAction:async action=>{if(discord)await discord.voiceAction(action);},onError:code=>log({event:'operation_failed',code})});
  try{
    if(config.dots.enabled){
      const refreshDotsPolicy=async source=>{
        current=await loadConfig(filename);
        check(current.discord.guildId===config.discord.guildId&&current.discord.applicationId===config.discord.applicationId,'DOTS_INSTALLATION_CHANGED');
        check(current.dots.enabled&&current.dots.actorId===source.actorId&&current.discord.operators.includes(source.actorId)&&current.dots.channelIds.includes(source.channelId),'DOTS_SOURCE_SCOPE_CHANGED');
      };
      dots=new DotsBridge({config,store,policy:()=>current,authorize:async source=>{
        await refreshDotsPolicy(source);
        if(!offline){const access=await discord.actorAccess(source.actorId,[source.channelId]);check(access!=='unavailable','ACCESS_UNAVAILABLE');check(access==='allowed','SOURCE_ACCESS_DENIED');}
        await refreshDotsPolicy(source);
      },deliver:async(source,message,{purpose='reply',beforeSend}={})=>{
        check(discord?.verifiedInstallation,'DISCORD_NOT_CONNECTED');await discord.member(source.actorId);
        const channel=await discord.client.channels.fetch(source.channelId);check(await discord.canRead(channel,source.actorId),'SOURCE_ACCESS_DENIED');
        const user=await discord.client.users.fetch(source.actorId);await refreshDotsPolicy(source);beforeSend();
        if(purpose==='reply'&&source.metadata?.kind==='text'&&current.dots.replyMode==='channel')return channel.send({...message,reply:{messageReference:source.sourceId,failIfNotExists:true}});
        return user.send(message);
      }});
    }
    if(!offline){
      discord=new DiscordAdapter({config,store,pipeline,dots,policy:()=>current,onError:code=>log({event:'discord',code})});await discord.login();
      const readers=async room=>{const channel=await discord.client.channels.fetch(room.target.voiceChannelId,{force:true});const candidates=new Set([...current.discord.operators,...room.audience().filter(id=>room.allowed(id))]);const allowed=[];for(const actor of candidates)if(await discord.canRead(channel,actor))allowed.push(actor);return allowed;};
      const options={client:discord.client,config,store,pipeline,policy:()=>current,onError:code=>log({event:'voice',code})};
      if(config.voicePool)voice=await createVoicePool({...options,ownerId,readers});
      else if(config.discord.voiceChannelId)voice=new VoiceRoom({...options,sourceReaders:()=>readers(voice)});
      discord.voice=voice;
    }
    if(config.archive?.enabled){
      check(voice&&config.voice.storeAudio,'ARCHIVE_RECORDING_CONFIG_REQUIRED');let failures=0,retryAt=0;
      const archivePolicy=()=>({...current,archive:{...current.archive,speakerIds:voice.audience().filter(id=>voice.allowed(id)),canProcess:!closing&&!voice.connectionReady()&&failures<3&&Date.now()>=retryAt}});
      archive=new ArchiveRuntime({config:archivePolicy(),policy:archivePolicy,store,analyzer:selectedAnalyzer,authorize:b=>b.readers.every(id=>current.discord.operators.includes(id))&&b.speakerIds.every(id=>voice.allowed(id)),onUsage:usage=>store.event('archive.model_usage',usage),onError:code=>{if(code==='ARCHIVE_SCOPE_REVOKED'&&voice.connectionReady())return;failures++;retryAt=Date.now()+60000;log({event:'archive',code,failures});}});
      voice.archive=archive;archiveTimer=setInterval(()=>{void archive.processPending().catch(()=>{if(voice.connectionReady())return;failures++;retryAt=Date.now()+60000;log({event:'archive',code:'ARCHIVE_PROCESSING_FAILED',failures});});},10000);archiveTimer.unref();
    }
    if(voice&&!config.voicePool){rotation=new VoiceRotation({store,config,policy:()=>current,deliver:batch=>deliverRotation(discord,batch,{voice,isActive:()=>!closing&&!rotation.stopped,readConfig:async()=>{check(!closing,'RUNTIME_STOPPING');current=await loadConfig(filename);return current;}}),onError:code=>log({event:'voice_rotation',code})});voice.rotation=rotation;rotation.start();}
    voice?.control.start();
    const secret=randomBytes(32).toString('hex');const secretFile=path.join(config.dataDir,'control.secret');await atomicText(secretFile,secret);
    const handleControl=async(req,res)=>{
      const send=(status,body,close=false)=>sendHttpJson(res,status,body,{close});
      let scope;
      try{
        const auth=Buffer.from(String(req.headers.authorization??'')),expected=Buffer.from('Bearer '+secret);check(auth.length===expected.length&&timingSafeEqual(auth,expected),'UNAUTHORIZED');
        if(req.method==='GET'&&req.url==='/v1/status'){send(200,{ownerId,pid:process.pid,startedAt,discord:discord?'connected':'offline_fixture',voice:voice?.control.status()??null,taskOwner:config.owner.kind,analysis:pipeline.analysisAdmission.status(),source});return;}
        check(req.method==='POST'&&req.url==='/v1/command','ROUTE_NOT_FOUND');check(!closing,'RUNTIME_STOPPING');check(controlOperations.size<8,'CONTROL_BUSY');
        scope=deadlineScope(10000,'CONTROL_BODY_TIMEOUT');controlReads.add(scope);
        const body=await readHttpBody(req,{maxBytes:200000,signal:scope.signal,limitCode:'CONTROL_BODY_LIMIT',invalidCode:'CONTROL_BODY_INVALID'});
        const input=JSON.parse(body.toString('utf8'));current=await awaitWithSignal(loadConfig(filename),scope.signal);check(!closing,'RUNTIME_STOPPING');check(current.discord.operators.includes(input.actor),'OPERATOR_REQUIRED');
        controlReads.delete(scope);scope.dispose();scope=null;
        let result;
        if(input.action==='tasks')result=await pipeline.tasks(input.actor);
        else if(input.action==='result')result=await pipeline.result(input.taskId,input.actor);
        else if(input.action==='stop'){await pipeline.stop(input.taskId,input.actor);result={state:'stop_requested'};}
        else if(input.action==='resume')result=await pipeline.resume(input.taskId,input.actor);
        else if(input.action==='voice'){check(voice,'VOICE_NOT_CONFIGURED');result=await voiceCommand(voice,input.mode,{actor:input.actor,channelId:input.channelId});}
        else if(input.action==='verify-deletion')result=await recordRetentionReadback({receipt:input.receipt,scope:input.scope,actor:input.actor,config,store,policy:()=>current,readConfig:async()=>{current=await loadConfig(filename);return current;},assertActive:()=>check(!closing&&store.lock()?.owner===ownerId,'RUNTIME_STOPPING')});
        else if(input.action==='dots'){
          check(dots&&current.dots.actorId===input.actor,'DOTS_ACTOR_REQUIRED');
          if(input.operation==='list')result=await dots.list({cursor:input.cursor,includeText:input.includeText,limit:input.limit});
          else if(input.operation==='read_request')result=await dots.read(input.id,input.revision,{offset:input.offset,limit:input.limit});
          else if(input.operation==='reply')result=await dots.send(input.id,input.revision,input.text);
          else if(input.operation==='draft_event')result=await dots.prepareEvent(input.id,input.revision,input.event,{operation:input.eventOperation,targetUrl:input.targetUrl});
          else if(input.operation==='read_event')result=await dots.readDraft(input.id);
          else if(input.operation==='claim_event')result=await dots.claimEvent(input.id);
          else if(input.operation==='record_event')result=await dots.recordEvent(input.id,input.claimId,input.url,input.event);
          else throw new Error('UNKNOWN_DOTS_OPERATION');
        }
        else if(input.action==='request'){check(typeof input.text==='string'&&input.text.trim()&&input.text.length<=16000,'REQUEST_INVALID');const source={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:input.requestId??uid('cli'),actorId:input.actor,revision:1,final:true,readers:[input.actor],text:input.text,metadata:{kind:'trusted_cli'}};result=await pipeline.request(source,{title:input.text.slice(0,120),request:input.text,action:input.operation,acceptance:input.acceptance??[]});}
        else if(input.action==='shutdown'){result={state:'stopping'};setImmediate(()=>{void close().catch(e=>log({event:'runtime_shutdown_failed',code:errorCode(e)}));});}
        else throw new Error('UNKNOWN_COMMAND');send(200,{ok:true,result});
      }catch(e){const code=errorCode(e);send(code==='UNAUTHORIZED'?401:code==='CONTROL_BUSY'||code==='RUNTIME_STOPPING'?503:code==='CONTROL_BODY_LIMIT'?413:code==='CONTROL_BODY_TIMEOUT'?408:400,{ok:false,error:code},true);}
      finally{if(scope){controlReads.delete(scope);scope.dispose();}}
    };
    control=http.createServer({maxHeaderSize:16384,requestTimeout:15000,headersTimeout:10000},(req,res)=>{
      const operation=handleControl(req,res);controlOperations.add(operation);void operation.finally(()=>controlOperations.delete(operation)).catch(()=>{});
    });
    control.maxConnections=32;control.setTimeout(15000,socket=>socket.destroy());
    await new Promise((resolve,reject)=>{control.once('error',reject);control.listen(0,'127.0.0.1',resolve);});
    if(config.bridge.enabled)bridge=await startBridge({config,store,pipeline,readConfig:()=>loadConfig(filename),onImported:(receipt,{signal}={})=>discord?discord.notifyLumaImport(receipt,{readConfig:()=>loadConfig(filename),signal}):{state:'unavailable'}});
    const runtime={ownerId,pid:process.pid,startedAt,port:control.address().port,secretFile,configFile:path.resolve(filename),offline};await atomicJson(path.join(config.dataDir,'runtime.json'),runtime);
    // Keep polling during an outage; log only its start and recovery.
    let policyAvailable=true,policyFailed=false;
    const pollPolicy=async()=>{
      const previous=current;
      try{
        const next=await loadConfig(filename);if(closing)return;current=next;
        if(!policyAvailable){policyAvailable=true;log({event:'policy_restored'});}
      }catch{
        if(closing)return;
        current={...config,voicePool:undefined,discord:{...config.discord,operators:[],consentingUsers:[]},voice:{...config.voice,consentMode:'owner_managed',participantIds:[]}};
        if(policyAvailable){policyAvailable=false;log({event:'policy_unavailable'});}
      }
      dots?.prune();if(JSON.stringify(previous)!==JSON.stringify(current))void voice?.control.check();
      await Promise.all([...pipeline.active].map(async([id,run])=>{
        const kept=await accessMonitor.check(id,async()=>{
          check(!closing,'RUNTIME_STOPPING');const task=await owner.taskInternal(id);check(!closing,'RUNTIME_STOPPING');
          check(task.revision===run.revision&&task.state==='running','TASK_CHANGED');await owner.assertContext(id,task.actor);check(!closing,'RUNTIME_STOPPING');
          await authorize(task,'execute',{monitor:true});
        });
        if(!kept)run.controller.abort();else if(accessMonitor.grace.pending.has(id))log({event:'task_access',code:'ACCESS_UNAVAILABLE'});
      }));
      accessMonitor.retain(pipeline.active.keys());policyFailed=false;
    };
    policyTimer=setInterval(()=>{
      if(policyWork||closing)return;
      policyWork=pollPolicy().catch(error=>{
        for(const run of pipeline.active.values())run.controller.abort();
        if(!closing&&!policyFailed){policyFailed=true;try{log({event:'policy_check_failed',code:errorCode(error)});}catch{}}
      });
      const finished=()=>{policyWork=null;};policyWork.then(finished,finished);
    },1000);policyTimer.unref();
    log({event:'runtime_ready',pid:process.pid,port:runtime.port,discord:offline?'offline_fixture':'connected',voice:'not_joined',taskOwner:config.owner.kind});
  }catch(e){await close();throw e;}
  function close(){
    if(closePromise)return closePromise;closing=true;pipeline.draining=true;
    // A later uncertain drain must not leave workers running without their monitor.
    for(const run of pipeline.active.values())run.controller.abort();
    clearInterval(policyTimer);clearInterval(archiveTimer);accessMonitor.stop();
    const stopped=stopControl();
    closePromise=(async()=>{
      // Keep the store and host lock if a dispatched import has an uncertain drain.
      await bridge?.drain();await rotation?.close();await discord?.close();await archive?.close();await pipeline.close();
      await Promise.allSettled([...controlOperations]);await stopped;await accessMonitor.drain({pending:policyWork?[policyWork]:[]});if(owner.kind==='remote')await owner.close();
      store.releaseHost(ownerId);store.close();clearInterval(shutdownKeepAlive);log({event:'runtime_stopped',ownerId});stopDebug();
    })().catch(error=>{closePromise=null;if(errorCode(error).endsWith('_DRAIN_UNCERTAIN'))shutdownKeepAlive??=setInterval(()=>{},1000);throw error;});
    return closePromise;
  }
  return {config,store,owner,pipeline,discord,voice,dots,close};
}
async function localControlRequest(port,route,token,payload){
  return new Promise((resolve,reject)=>{
    const body=payload===undefined?null:JSON.stringify(payload);
    const request=http.request({hostname:'127.0.0.1',port,path:route,method:body===null?'GET':'POST',headers:{authorization:'Bearer '+token,...(body===null?{}:{'content-type':'application/json','content-length':Buffer.byteLength(body)})}},response=>{
      const chunks=[];let size=0;response.on('data',chunk=>{size+=chunk.length;if(size>1000000){request.destroy(new Error('CONTROL_RESPONSE_LIMIT'));return;}chunks.push(chunk);});
      response.on('error',reject);response.on('end',()=>{try{const value=JSON.parse(Buffer.concat(chunks).toString('utf8'));check(response.statusCode===200,typeof value.error==='string'&&/^[A-Z_]+$/.test(value.error)?value.error:'RUNTIME_NOT_AVAILABLE');resolve(value);}catch(error){reject(error);}});
    });
    request.setTimeout(body===null?3000:30000,()=>request.destroy(new Error('CONTROL_TIMEOUT')));request.on('error',reject);request.end(body);
  });
}
export async function controlCommand(config,input){
  const runtime=JSON.parse((await readArtifact(path.join(config.dataDir,'runtime.json'),65536)).toString('utf8'));
  const port=Number(runtime.port);check(Number.isInteger(port)&&port>=1&&port<=65535,'RUNTIME_PORT_INVALID');
  const token=(await readArtifact(path.join(config.dataDir,'control.secret'),64)).toString('utf8');check(/^[a-f0-9]{64}$/.test(token),'CONTROL_TOKEN_INVALID');
  const current=await localControlRequest(port,'/v1/status',token);
  check(current.ownerId===runtime.ownerId&&current.pid===runtime.pid&&current.startedAt===runtime.startedAt,'RUNTIME_OWNER_CHANGED');
  if(input.action==='status')return current;
  const value=await localControlRequest(port,'/v1/command',token,input);check(value.ok,value.error??'CONTROL_FAILED');return value.result;
}
