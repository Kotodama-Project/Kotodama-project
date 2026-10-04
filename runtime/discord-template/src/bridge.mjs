import http from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {check,digest,errorCode,Refused} from './common.mjs';
import {parseLumaCsv,lumaSource} from './integrations.mjs';
import {awaitWithSignal,deadlineScope,readHttpBody,sendHttpJson} from './http-limits.mjs';

const defaults={maxRequests:8,maxConnections:32,maxBodyBytes:2200000,requestTimeoutMs:15000,notificationTimeoutMs:3000,maxNotifications:4,drainTimeoutMs:15000};

export async function startBridge({config,store,pipeline,readConfig=async()=>config,onImported,limits={}}){
  check(config.bridge.enabled,'BRIDGE_DISABLED');const secret=process.env[config.bridge.tokenEnv];check(secret&&secret.length>=24,'BRIDGE_CREDENTIAL_REQUIRED');
  const settings={...defaults,...limits};for(const value of Object.values(settings))check(Number.isSafeInteger(value)&&value>0,'BRIDGE_LIMIT_INVALID');
  const actorId=config.bridge.actorId,active=new Set(),notifications=new Map();let stopping=false,importTail=Promise.resolve(),closed;
  const currentConfig=async scope=>{
    const current=await scope.wait(readConfig());
    check(current.bridge.enabled&&current.bridge.actorId===actorId&&process.env[current.bridge.tokenEnv]===secret,'BRIDGE_CONFIG_CHANGED');return current;
  };
  const notify=async(receipt,parentSignal)=>{
    if(!onImported)return {state:'not_configured'};
    const key=digest([receipt.key,receipt.sourceDigest,receipt.actorId]);
    if(notifications.has(key))return {state:'unknown'};
    if(stopping||notifications.size>=settings.maxNotifications)return {state:'unavailable'};
    const deadline=deadlineScope(settings.notificationTimeoutMs,'BRIDGE_NOTIFICATION_TIMEOUT',parentSignal);
    const work=Promise.resolve().then(()=>{deadline.signal.throwIfAborted();return onImported(receipt,{signal:deadline.signal});});
    const pending={work,deadline};notifications.set(key,pending);
    work.then(()=>{notifications.delete(key);deadline.dispose();},()=>{notifications.delete(key);deadline.dispose();});
    try{const result=await awaitWithSignal(work,deadline.signal);return {state:['sent','already_sent','unknown','blocked','unavailable','deferred'].includes(result?.state)?result.state:'unknown'};}
    catch{return {state:'unknown'};}
  };
  const server=http.createServer((req,res)=>{
    if(stopping||active.size>=settings.maxRequests){sendHttpJson(res,503,{error:stopping?'BRIDGE_STOPPING':'BRIDGE_BUSY'},{close:true});return;}
    const deadline=deadlineScope(settings.requestTimeoutMs,'BRIDGE_REQUEST_TIMEOUT'),pending=new Set();
    const scope={...deadline,writing:false,done:false,wait:value=>{
      const work=Promise.resolve(value);pending.add(work);
      const finish=()=>{pending.delete(work);if(scope.done&&pending.size===0)active.delete(scope);};work.then(finish,finish);
      return awaitWithSignal(work,scope.signal);
    }};
    active.add(scope);
    const disconnected=()=>{if(!res.writableFinished)scope.abort(new Refused('HTTP_CLIENT_DISCONNECTED'));};res.once('close',disconnected);
    void (async()=>{
      try{
        const supplied=Buffer.from(String(req.headers.authorization??'')),expected=Buffer.from('Bearer '+secret);
        check(supplied.length===expected.length&&timingSafeEqual(supplied,expected),'UNAUTHORIZED');
        const current=await currentConfig(scope);
        if(req.method==='GET'&&req.url==='/health'){sendHttpJson(res,200,{ready:true,execution:false});return;}
        check(req.method==='POST'&&req.url==='/v1/luma/import','ROUTE_NOT_FOUND');
        const bytes=await readHttpBody(req,{maxBytes:settings.maxBodyBytes,signal:scope.signal});
        const body=JSON.parse(bytes.toString('utf8'));check(body&&typeof body.csv==='string'&&Object.keys(body).every(k=>['csv','eventRef','revision'].includes(k)),'IMPORT_BODY_INVALID');
        check(current.integrations.luma?.eventRef===body.eventRef,'EVENT_NOT_ALLOWED');
        // A bounded admission set feeds one writer. Cancelled queued requests
        // cannot run later, and a timed-out dispatched ingest holds this lane.
        const operation=importTail.then(async()=>{
          scope.signal.throwIfAborted();check(!stopping,'BRIDGE_STOPPING');const latest=await currentConfig(scope);
          check(latest.integrations.luma?.eventRef===body.eventRef,'EVENT_NOT_ALLOWED');
          const data=parseLumaCsv(body.csv,{eventRef:body.eventRef});
          const source=lumaSource(data,{guildId:latest.discord.guildId,channelId:latest.discord.resultChannelId,actorId,readers:[actorId],revision:body.revision??Date.now()});
          const key=digest([source.provider,source.guildId,source.channelId,source.sourceId]),old=store.sourceInternal(key);
          if(old){check(!old.withdrawn,'LUMA_SOURCE_WITHDRAWN');check(old.actorId===source.actorId&&old.readers.includes(source.actorId),'LUMA_SOURCE_BINDING_CHANGED');}
          let result,revision=source.revision;
          if(old?.metadata?.sourceDigest===data.sourceDigest&&old.readers.length===1&&old.readers[0]===source.actorId){result={state:'duplicate',eventRef:body.eventRef};revision=old.revision;}
          else{
            if(old?.metadata?.sourceDigest===data.sourceDigest)source.revision=Math.max(source.revision,old.revision+1);
            scope.signal.throwIfAborted();check(!stopping,'BRIDGE_STOPPING');scope.writing=true;
            const receipt=await pipeline.ingest(source,{execute:false,reply:false});scope.writing=false;
            scope.signal.throwIfAborted();
            result={state:receipt.state,eventRef:body.eventRef,identifiedPeople:data.identifiedPeople,identifiedTickets:data.identifiedTickets,sourceDigest:data.sourceDigest};revision=source.revision;
          }
          return {result,receipt:{key,revision,eventRef:body.eventRef,sourceDigest:data.sourceDigest,actorId:source.actorId}};
        });
        importTail=operation.then(()=>{},()=>{});
        const imported=await scope.wait(operation),notification=await notify(imported.receipt,scope.signal);
        sendHttpJson(res,200,{...imported.result,notification});
      }catch(error){
        const code=scope.writing&&(scope.signal.aborted||error?.code==='OWNER_RESULT_UNCERTAIN')?'BRIDGE_IMPORT_UNCERTAIN':errorCode(error);
        const status=code==='UNAUTHORIZED'?401:code==='ROUTE_NOT_FOUND'?404:code==='BODY_TOO_LARGE'?413:code==='BRIDGE_IMPORT_UNCERTAIN'?504:code==='BRIDGE_REQUEST_TIMEOUT'?408:code==='BRIDGE_STOPPING'?503:400;
        sendHttpJson(res,status,{error:code},{close:true});
      }finally{
        scope.done=true;scope.dispose();res.removeListener('close',disconnected);if(pending.size===0)active.delete(scope);
      }
    })();
  });
  server.maxConnections=settings.maxConnections;server.requestTimeout=settings.requestTimeoutMs;server.headersTimeout=Math.min(10000,settings.requestTimeoutMs);server.timeout=settings.requestTimeoutMs+1000;server.keepAliveTimeout=1000;
  server.drain=async()=>{
    stopping=true;for(const scope of active)scope.abort(new Refused('BRIDGE_STOPPING'));for(const {deadline} of notifications.values())deadline.abort(new Refused('BRIDGE_STOPPING'));
    closed??=new Promise(resolve=>server.close(resolve));server.closeIdleConnections();server.closeAllConnections();
    const deadline=deadlineScope(settings.drainTimeoutMs,'BRIDGE_DRAIN_UNCERTAIN');
    try{await awaitWithSignal(Promise.all([closed,importTail,...[...notifications.values()].map(({work})=>work.catch(()=>{}))]),deadline.signal);}finally{deadline.dispose();}
  };
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(config.bridge.port,config.bridge.host,resolve);});
  return server;
}
