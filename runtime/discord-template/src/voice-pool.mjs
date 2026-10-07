import {Client,GatewayIntentBits} from 'discord.js';
import {VoiceRoom} from './voice.mjs';
import {check,digest,errorCode} from './common.mjs';

const layout=config=>digest({guild:config.discord.guildId,application:config.discord.applicationId,token:config.discord.botTokenEnv,
  channels:[config.discord.voiceChannelId,...(config.voicePool?.rooms??[]).map(room=>room.channelId)].filter(Boolean),bots:config.voicePool?.bots??[]});
const definitions=config=>[...(config.discord.voiceChannelId?[{channelId:config.discord.voiceChannelId}]:[]),...config.voicePool.rooms];

// Resource reservations belong to this installation's one host-lock owner.
// They neither create a Task owner nor coordinate unrelated installations.
export class VoicePool {
  constructor({config,policy=()=>config,store,ownerId,pipeline,clients,readers,onError=()=>{},roomFactory=options=>new VoiceRoom(options)}){
    Object.assign(this,{config,policy,store,ownerId,pipeline,onError});this.binding=layout(config);this.stopped=false;
    check(store.lock()?.owner===ownerId,'VOICE_POOL_OWNER_REQUIRED');
    this.slots=clients.map(({applicationId,client})=>({applicationId,client,lease:null}));
    check(this.slots.length>0&&new Set(this.slots.map(slot=>slot.applicationId)).size===this.slots.length,'VOICE_POOL_DUPLICATE_BOT');
    this.rooms=new Map();this.listeners=[];
    for(const definition of definitions(config)){
      check(!this.rooms.has(definition.channelId),'VOICE_POOL_DUPLICATE_ROOM');
      const channelId=definition.channelId,roomConfig=this.roomPolicy(channelId);
      const room=roomFactory({config:roomConfig,policy:()=>this.roomPolicy(channelId),client:clients[0].client,store,pipeline,onError,
        sourceReaders:()=>readers(room),acquireConnection:target=>this.acquire(target)});
      this.rooms.set(channelId,room);
    }
    for(const slot of this.slots){
      const lost=()=>{const room=this.rooms.get(slot.lease?.channelId);if(room)void room.close().catch(error=>onError(errorCode(error)));};
      for(const event of ['shardDisconnect','invalidated']){slot.client.on(event,lost);this.listeners.push([slot.client,event,lost]);}
    }
    this.control={start:()=>{for(const room of this.rooms.values())room.control.start();},
      check:()=>Promise.all([...this.rooms.values()].map(room=>room.control.check())),
      status:()=>({rooms:[...this.rooms].map(([channelId,room])=>({channelId,...room.control.status()}))}),
      command:async(mode,options={})=>{
        if(mode==='status'&&!options.channelId)return this.control.status();
        const room=this.forChannel(options.channelId??(this.rooms.size===1?[...this.rooms.keys()][0]:null));
        check(room,'VOICE_ROOM_REQUIRED');return room.control.command(mode,options);
      }};
  }
  roomPolicy(channelId){
    const current=this.policy();
    const definition=!this.stopped&&this.store.lock()?.owner===this.ownerId&&current.voicePool&&layout(current)===this.binding?definitions(current).find(room=>room.channelId===channelId):null;
    if(!definition)return {...current,discord:{...current.discord,voiceChannelId:null},voice:{...current.voice,autoJoin:false,participantIds:[]}};
    const {channelId:_,...overrides}=definition;
    return {...current,discord:{...current.discord,voiceChannelId:channelId},voice:{...current.voice,...overrides}};
  }
  forChannel(channelId){return this.rooms.get(channelId)??null;}
  forSource(source){return source?.provider==='discord'&&source.guildId===this.config.discord.guildId?this.forChannel(source.channelId):null;}
  async acquire(target){
    check(!this.stopped&&this.store.lock()?.owner===this.ownerId,'VOICE_POOL_OWNER_CHANGED');
    check(target.guildId===this.config.discord.guildId&&this.rooms.has(target.voiceChannelId)&&layout(this.policy())===this.binding,'VOICE_TARGET_MISMATCH');
    check(!this.slots.some(slot=>slot.lease?.channelId===target.voiceChannelId),'VOICE_ALREADY_CONNECTED');
    for(const slot of this.slots){
      if(slot.lease||!slot.client.isReady())continue;
      const lease={channelId:target.voiceChannelId};slot.lease=lease;
      const release=()=>{if(slot.lease===lease)slot.lease=null;};
      try{
        const guild=await slot.client.guilds.fetch(target.guildId);
        const member=await guild.members.fetchMe({force:true});
        // An external connection is occupied too; never move it into our room.
        if(member.voice.channelId){release();continue;}
        const channel=await slot.client.channels.fetch(target.voiceChannelId,{force:true});
        check(!this.stopped&&slot.lease===lease&&slot.client.isReady()&&this.store.lock()?.owner===this.ownerId&&layout(this.policy())===this.binding,'VOICE_POOL_OWNER_CHANGED');
        return {channel,group:`${this.config.installation}:${slot.applicationId}`,release};
      }catch(error){release();throw error;}
    }
    check(false,'VOICE_POOL_BUSY');
  }
  async dispose(){
    this.stopped=true;await Promise.all([...this.rooms.values()].map(room=>room.dispose()));
    for(const [client,event,listener] of this.listeners)client.off(event,listener);
    for(const slot of this.slots.slice(1))await slot.client.destroy();
  }
}

export async function createVoicePool(options,{clientFactory=()=>new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildVoiceStates]})}={}){
  const {config,client}=options,clients=[{applicationId:config.discord.applicationId,client}],created=[];
  try{
    for(const bot of config.voicePool.bots){
      const extra=clientFactory();created.push(extra);extra.on('error',()=>options.onError?.('VOICE_POOL_CLIENT_FAILED'));
      const token=process.env[bot.botTokenEnv];check(token,'DISCORD_CREDENTIAL_REQUIRED');let timer;
      const ready=new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(new Error('DISCORD_READY_TIMEOUT')),30000);extra.once('clientReady',resolve);});
      try{await Promise.all([extra.login(token),ready]);}finally{clearTimeout(timer);}
      check(extra.application.id===bot.applicationId,'BOT_APPLICATION_MISMATCH');
      await extra.guilds.fetch(config.discord.guildId);clients.push({applicationId:bot.applicationId,client:extra});
    }
    return new VoicePool({...options,clients});
  }catch(error){await Promise.allSettled(created.map(extra=>extra.destroy()));throw error;}
}
