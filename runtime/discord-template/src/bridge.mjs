import http from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {check,digest,errorCode} from './common.mjs';
import {parseLumaCsv,lumaSource} from './integrations.mjs';

export async function startBridge({config,store,pipeline,readConfig=async()=>config,onImported}){
  check(config.bridge.enabled,'BRIDGE_DISABLED');const secret=process.env[config.bridge.tokenEnv];check(secret&&secret.length>=24,'BRIDGE_CREDENTIAL_REQUIRED');
  const notify=async receipt=>{
    if(!onImported)return {state:'not_configured'};
    try{const result=await onImported(receipt);return {state:['sent','already_sent','unknown','blocked','unavailable'].includes(result?.state)?result.state:'unknown'};}
    catch{return {state:'unknown'};}
  };
  const server=http.createServer(async(req,res)=>{
    const send=(status,value)=>{res.writeHead(status,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});res.end(JSON.stringify(value));};
    try{
      const supplied=String(req.headers.authorization??'');const expected='Bearer '+secret;
      check(supplied.length===expected.length&&timingSafeEqual(Buffer.from(supplied),Buffer.from(expected)),'UNAUTHORIZED');
      const current=await readConfig();check(current.bridge.enabled&&current.bridge.actorId===config.bridge.actorId&&process.env[current.bridge.tokenEnv]===secret,'BRIDGE_CONFIG_CHANGED');
      if(req.method==='GET'&&req.url==='/health'){send(200,{ready:true,execution:false});return;}
      check(req.method==='POST'&&req.url==='/v1/luma/import','ROUTE_NOT_FOUND');
      const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;check(size<=2200000,'BODY_TOO_LARGE');chunks.push(chunk);}
      const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));check(body&&typeof body.csv==='string'&&Object.keys(body).every(k=>['csv','eventRef','revision'].includes(k)),'IMPORT_BODY_INVALID');
      check(current.integrations.luma?.eventRef===body.eventRef,'EVENT_NOT_ALLOWED');
      const data=parseLumaCsv(body.csv,{eventRef:body.eventRef});
      const source=lumaSource(data,{guildId:current.discord.guildId,channelId:current.discord.resultChannelId,actorId:current.bridge.actorId,readers:[current.bridge.actorId],revision:body.revision??Date.now()});
      const key=digest([source.provider,source.guildId,source.channelId,source.sourceId]),old=store.sourceInternal(key);
      if(old){check(!old.withdrawn,'LUMA_SOURCE_WITHDRAWN');check(old.actorId===source.actorId&&old.readers.includes(source.actorId),'LUMA_SOURCE_BINDING_CHANGED');}
      const notifySource=revision=>notify({key,revision,eventRef:body.eventRef,sourceDigest:data.sourceDigest,actorId:source.actorId});
      if(old?.metadata?.sourceDigest===data.sourceDigest){
        if(old.readers.length===1&&old.readers[0]===source.actorId){const notification=await notifySource(old.revision);send(200,{state:'duplicate',eventRef:body.eventRef,notification});return;}
        source.revision=Math.max(source.revision,old.revision+1);
      }
      const receipt=await pipeline.ingest(source,{execute:false,reply:false});
      const notification=await notifySource(source.revision);
      send(200,{state:receipt.state,eventRef:body.eventRef,identifiedPeople:data.identifiedPeople,identifiedTickets:data.identifiedTickets,sourceDigest:data.sourceDigest,notification});
    }catch(e){const code=errorCode(e);send(code==='UNAUTHORIZED'?401:code==='ROUTE_NOT_FOUND'?404:400,{error:code});}
  });
  server.requestTimeout=15000;server.headersTimeout=10000;
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(config.bridge.port,config.bridge.host,resolve);});
  return server;
}
