import {ChannelType,PermissionFlagsBits as P} from 'discord.js';
import {check,digest} from './common.mjs';
import {voiceNotice} from './consent.mjs';

const has=(value,flag)=>(BigInt(value?.bitfield??value??0)&flag)===flag;
const ownBotRole=(role,botId)=>role?.managed===true&&role.tags?.botId===botId;
const idPattern=/^\d{5,24}$/;

// With no GuildMembers intent, role-wide access cannot be enumerated safely.
export function rotationViewers(channel,guild,roles,botId){
  check(channel?.type===ChannelType.GuildText&&channel.guildId===guild.id&&idPattern.test(guild.ownerId),'ROTATION_PRIVATE_CHANNEL_REQUIRED');
  const overwrites=channel.permissionOverwrites?.cache;
  check(overwrites&&overwrites.size<=100&&roles?.size>0&&roles.size<=1000&&roles.has(guild.id),'ROTATION_AUDIENCE_UNAVAILABLE');
  const everyone=overwrites.get(guild.id);
  check(everyone?.type===0&&has(everyone.deny,P.ViewChannel)&&!has(everyone.allow,P.ViewChannel),'ROTATION_PUBLIC_CHANNEL_REFUSED');
  for(const role of roles.values())check(!has(role.permissions,P.Administrator)||ownBotRole(role,botId),'ROTATION_ADMIN_AUDIENCE_UNKNOWN');
  const viewers=new Set([guild.ownerId]);
  for(const overwrite of overwrites.values()){
    check([0,1].includes(overwrite.type)&&idPattern.test(overwrite.id),'ROTATION_AUDIENCE_UNAVAILABLE');
    if(overwrite.type===0&&has(overwrite.allow,P.ViewChannel))check(ownBotRole(roles.get(overwrite.id),botId),'ROTATION_ROLE_AUDIENCE_UNKNOWN');
    // Discord applies an explicit member allow after a member deny.
    if(overwrite.type===1&&has(overwrite.allow,P.ViewChannel))viewers.add(overwrite.id);
  }
  viewers.delete(botId);return [...viewers].sort();
}

function sourcesFor(adapter,voice,batch,config){
  const notice=voiceNotice(config).id,values=[];
  for(const entry of batch.entries){
    const source=adapter.store.sourceInternal(entry.key);
    if(!source||source.withdrawn||source.revision!==entry.revision||!source.final||!voice.allowed(entry.inputAccountId))continue;
    if(source.provider!=='discord'||source.guildId!==batch.guildId||source.channelId!==batch.channelId||source.metadata?.kind!=='voice'||
      source.metadata.transcriptOrigin!=='local_asr'||source.metadata.inputAccountId!==entry.inputAccountId||source.metadata.privacyNoticeId!==notice)continue;
    if(source.actorId!==null&&source.actorId!==entry.inputAccountId)continue;
    values.push({entry,source});
  }
  return values;
}

function renderTranscript(values,batch,config){
  const labels=new Map(),lines=[];
  for(const {entry,source} of [...values].sort((a,b)=>a.entry.startedAt-b.entry.startedAt||a.entry.key.localeCompare(b.entry.key))){
    const identified=source.actorId===entry.inputAccountId&&source.metadata.attribution==='discord_input_track'&&!config.discord.unattributedUsers.includes(entry.inputAccountId);
    if(identified&&!labels.has(entry.inputAccountId))labels.set(entry.inputAccountId,`話者${labels.size+1}`);
    const label=identified?labels.get(entry.inputAccountId):'話者不明',seconds=Math.max(0,Math.floor((entry.startedAt-batch.startedAt)/1000));
    lines.push(`[${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}] ${label}: ${source.text.replace(/\r?\n/g,'\n    ')}`);
  }
  const file=Buffer.from(lines.join('\n')+'\n','utf8');check(file.length<=1000000,'ROTATION_TRANSCRIPT_LIMIT');
  const people=[...labels].map(([id,label])=>`${label}: <@${id}>`).join('\n');
  const content=`音声の区間記録 ${new Date(batch.startedAt).toISOString()} ～ ${new Date(batch.endedAt).toISOString()}\n確定して閲覧を確認できた発話のみです。未確定・撤回済みの発話は含みません。${people?'\n'+people:''}`;
  check(content.length<=2000,'ROTATION_SPEAKER_LIMIT');return {file,content};
}

export async function deliverRotation(adapter,batch,{voice,readConfig,isActive=()=>true}){
  let claimed=false;
  try{
    check(adapter.verifiedInstallation&&adapter.client.isReady()&&voice&&isActive()&&Array.isArray(batch.entries)&&batch.entries.length<=1024,'ROTATION_NOT_AVAILABLE');
    const generation=adapter.accessGeneration;
    const scoped=config=>{check(config.voice.rotation?.enabled&&config.voice.transcriptSource==='local'&&config.discord.guildId===batch.guildId&&config.discord.voiceChannelId===batch.channelId&&config.voice.rotation.channelId===batch.targetChannelId,'ROTATION_SCOPE_CHANGED');return config;};
    const policy=async()=>scoped(await readConfig());
    const audience=async()=>{
      const guild=await adapter.client.guilds.fetch({guild:batch.guildId,force:true});
      const bot=await guild.members.fetch({user:adapter.client.user.id,force:true});
      const roles=await guild.roles.fetch(),channel=await adapter.client.channels.fetch(batch.targetChannelId,{force:true});
      check(channel?.permissionsFor(bot)?.has([P.ViewChannel,P.SendMessages,P.AttachFiles]),'ROTATION_BOT_PERMISSION_REQUIRED');
      return {channel,viewers:rotationViewers(channel,guild,roles,adapter.client.user.id)};
    };
    let config=await policy(),values=sourcesFor(adapter,voice,batch,config);if(!values.length)return {state:'empty'};
    const initial=await audience(),voiceChannel=await adapter.client.channels.fetch(batch.channelId,{force:true});
    const checkReaders=viewers=>{for(const actor of viewers)for(const {entry} of values){const source=adapter.store.source(entry.key,actor);check(source.revision===entry.revision,'ROTATION_SOURCE_CHANGED');}};
    checkReaders(initial.viewers);
    for(const actor of initial.viewers)check(await adapter.canRead(voiceChannel,actor),'ROTATION_SOURCE_ACCESS_DENIED');
    await policy();const final=await audience();check(digest(initial.viewers)===digest(final.viewers),'ROTATION_AUDIENCE_CHANGED');
    check(isActive()&&adapter.verifiedInstallation&&adapter.client.isReady()&&adapter.accessGeneration===generation,'ROTATION_ACCESS_CHANGED');
    config=scoped(adapter.policy());const current=sourcesFor(adapter,voice,batch,config);
    check(current.length===values.length&&current.every((value,index)=>value.entry.key===values[index].entry.key),'ROTATION_SOURCE_CHANGED');
    values=current;checkReaders(final.viewers);
    const {file,content}=renderTranscript(values,batch,config),key=digest(['voice-rotation',batch.id,batch.guildId,batch.channelId,batch.targetChannelId]);
    claimed=adapter.store.claimDelivery(key,digest({content,file:file.toString('utf8')}));
    if(!claimed)return {state:adapter.store.deliveryState(key)==='sent'?'sent':'unknown'};
    const message=await final.channel.send({content,files:[{attachment:file,name:`voice-interval-${digest(batch.id).slice(0,16)}.txt`}],allowedMentions:{parse:[]},nonce:key.slice(0,25),enforceNonce:true});
    check(message?.id,'ROTATION_SEND_UNCONFIRMED');adapter.store.delivered(key,message.id);return {state:'sent'};
  }catch{return {state:claimed?'unknown':'blocked'};}
}
