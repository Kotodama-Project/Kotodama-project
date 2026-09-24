import {check} from './common.mjs';

// Analysis permission is not work-execution permission. An opted-in voice
// participant may read their own scoped conversation without becoming an operator.
export function createAnalysisAuthorizer({readConfig,config,onPolicy=()=>{},voice=()=>null,discord=()=>null,owner,offline=false}){
  return async(source,principal)=>{
    const current=await readConfig();onPolicy(current);const room=voice(),adapter=discord();
    check(current.discord.operators.includes(principal)||(source.provider==='discord'&&room?.allowed(principal)),'GRANT_REVOKED');
    check(!source.withdrawn&&source.readers.includes(principal),'SOURCE_ACCESS_DENIED');
    check(current.owner.kind===config.owner.kind&&current.worker.workspace===config.worker.workspace,'WORKSPACE_BINDING_CHANGED');
    if(source.provider==='discord'){
      check(source.guildId===current.discord.guildId,'SOURCE_ACCESS_DENIED');
      if(source.metadata?.kind==='text')check(current.discord.textChannelIds.includes(source.channelId),'SOURCE_ACCESS_DENIED');
      if(source.metadata?.kind==='voice'&&room)check(room.allowed(source.actorId),'SOURCE_ACCESS_DENIED');
      if(adapter&&!offline){const channel=await adapter.client.channels.fetch(source.channelId,{force:true});check(await adapter.canRead(channel,principal),'SOURCE_ACCESS_DENIED');}
    }
    if(owner.kind==='remote'){const remote=await owner.source(source.key,principal);check(remote.revision===source.revision,'REMOTE_SOURCE_CHANGED');}
  };
}
