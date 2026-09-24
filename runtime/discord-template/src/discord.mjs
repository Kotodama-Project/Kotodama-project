import {Client,GatewayIntentBits,PermissionFlagsBits,ChannelType,MessageFlags} from 'discord.js';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {check,digest,shortText,sourceIdentity,errorCode,atomicJson} from './common.mjs';
import {voiceNotice} from './consent.mjs';
import {voiceCommand,voiceStatusText} from './voice-control.mjs';
import {NotificationQueue} from './notifications.mjs';
import {resultFiles} from './result-files.mjs';

export const commandDefinition={name:'kotodama',description:'ことだまに相談・依頼し、仕事と音声を操作します',options:[
  {type:1,name:'ask',description:'相談する',options:[{type:3,name:'text',description:'知りたいこと',required:true}]},
  {type:1,name:'do',description:'許可範囲で仕事を実行する',options:[{type:3,name:'action',description:'仕事の種類',required:true,choices:['research','summarize','write_file','develop'].map(v=>({name:v,value:v}))},{type:3,name:'text',description:'やってほしいこと',required:true}]},
  {type:1,name:'tasks',description:'自分の仕事を見る'},
  {type:1,name:'consent',description:'音声処理の運用と、自分の停止設定を確認する'},
  ...['result','stop','resume'].map(name=>({type:1,name,description:{result:'成果を読む',stop:'仕事を止める',resume:'停止した仕事を再開する'}[name],options:[{type:3,name:'task',description:'仕事のID',required:true}]})),
  {type:1,name:'voice',description:'音声モード・録音・発話を操作する',options:[{type:3,name:'mode',description:'操作',required:true,choices:['assist','minutes','join','pause','resume','stop_speech','start_conversation','end_conversation','leave','status'].map(v=>({name:v,value:v}))}]}
]};

const accessCacheMs=3000;
const accessEvents=['channelUpdate','channelDelete','guildUpdate','guildMemberUpdate','guildMemberRemove','roleCreate','roleUpdate','roleDelete','threadUpdate','threadDelete','threadMembersUpdate'];
const taskStates={queued:'受付済み',running:'実行中',needs_review:'成果確認待ち',stale:'訂正により無効',failed:'失敗',cancelled:'停止済み',stopping:'停止処理中',uncertain:'状態確認中（自動では再実行しません）',paused:'一時停止中（resumeで再開できます）'};
export const taskStateText=state=>taskStates[state]??state;
// Deferred analysis keeps the Source; say so instead of claiming it was analysed.
export function deferredAnalysisText(reason){
  if(reason==='ANALYSIS_BUDGET_EXHAUSTED')return '本日の解析回数の上限に達したため、今回は解析していません。相談内容は記録済みです。';
  if(reason==='ANALYSIS_TOTAL_BUDGET_EXHAUSTED')return '解析回数の累計上限に達したため、解析していません。相談内容は記録済みです。上限は管理者が設定で見直せます。';
  return '混み合っているため、解析を後回しにしました。相談内容は記録済みです。少し時間をおいて、もう一度お試しください。';
}
export function accessFailure(error){const status=error?.status;return Number.isInteger(status)&&status>=400&&status<500&&status!==429?'denied':'unavailable';}

export class DiscordAdapter {
  constructor({config,store,pipeline,policy=()=>config,onError=()=>{}}){
    Object.assign(this,{config,store,pipeline,policy,onError});this.voice=null;this.verifiedInstallation=false;
    this.notifications=store.db?new NotificationQueue(store.db,()=>this.policy().notifications?.quietHours,{onError}):null;
    this.client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildMessages,GatewayIntentBits.MessageContent,GatewayIntentBits.GuildVoiceStates]});
    this.client.on('messageCreate',m=>this.message(m).catch(e=>onError(errorCode(e))));
    this.client.on('messageUpdate',(_old,m)=>this.message(m,{edited:true}).catch(e=>onError(errorCode(e))));
    this.client.on('messageDelete',m=>this.withdraw(m).catch(e=>onError(errorCode(e))));
    this.client.on('interactionCreate',i=>this.interaction(i).catch(e=>onError(errorCode(e))));
    this.client.on('error',()=>onError('DISCORD_CLIENT_FAILED'));
    this.accessCache=new Map();const forget=()=>this.accessCache.clear();for(const event of accessEvents)this.client.on(event,forget);
  }
  operator(actor){check(this.policy().discord.operators.includes(actor),'OPERATOR_REQUIRED');}
  artifactRoot(){return this.config.owner.kind==='local'?path.join(this.config.dataDir,'worktrees'):null;}
  async member(actor){this.operator(actor);const guild=await this.client.guilds.fetch(this.config.discord.guildId);return guild.members.fetch({user:actor,force:true});}
  // allowed / denied / unavailable. A Discord 4xx other than 429 is a denial;
  // rate limits, 5xx, timeouts and transport errors only mean "unavailable".
  async readAccess(channel,actor,{cached=false}={}){
    const key=`${channel?.id}:${actor}`;if(cached){const hit=this.accessCache.get(key);if(hit&&hit.expires>Date.now())return hit.state;}
    let state;
    try{channel=await this.client.channels.fetch(channel.id,{force:true});
      if(!channel?.guild)state='denied';
      else{const member=await channel.guild.members.fetch({user:actor,force:true});await channel.guild.roles.fetch();const p=channel.permissionsFor(member);
        if(!p?.has(PermissionFlagsBits.ViewChannel)||!p.has(PermissionFlagsBits.ReadMessageHistory))state='denied';
        else{if(channel.type===ChannelType.PrivateThread&&!p.has(PermissionFlagsBits.ManageThreads))await channel.members.fetch({member:actor,force:true});state='allowed';}}
    }catch(error){state=accessFailure(error);}
    this.remember(key,state);return state;
  }
  async canRead(channel,actor){return await this.readAccess(channel,actor)==='allowed';}
  async memberAccess(actor,{cached=false}={}){
    this.operator(actor);const key=`member:${actor}`;if(cached){const hit=this.accessCache.get(key);if(hit&&hit.expires>Date.now())return hit.state;}
    let state;try{await this.member(actor);state='allowed';}catch(error){state=accessFailure(error);}
    this.remember(key,state);return state;
  }
  // One check per distinct channel. Cached results live for accessCacheMs and
  // are dropped on any permission-relevant gateway event.
  async actorAccess(actor,channelIds,{cached=false}={}){
    let unavailable=false;
    for(const probe of [()=>this.memberAccess(actor,{cached}),...[...new Set(channelIds)].map(id=>()=>this.readAccess({id},actor,{cached}))]){
      const state=await probe();if(state==='denied')return 'denied';if(state==='unavailable')unavailable=true;
    }
    return unavailable?'unavailable':'allowed';
  }
  remember(key,state){
    if(state==='unavailable'){this.accessCache.delete(key);return;}
    if(this.accessCache.size>=1000)for(const [k,v] of this.accessCache)if(v.expires<=Date.now())this.accessCache.delete(k);
    if(this.accessCache.size<1000)this.accessCache.set(key,{state,expires:Date.now()+accessCacheMs});
  }
  async readers(channel){const readers=[];for(const actor of this.policy().discord.operators)if(await this.canRead(channel,actor))readers.push(actor);return readers;}
  async login(){const token=process.env[this.config.discord.botTokenEnv];check(token,'DISCORD_CREDENTIAL_REQUIRED');
    let timer;const ready=new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(new Error('DISCORD_READY_TIMEOUT')),30000);this.client.once('clientReady',resolve);});
    try{await Promise.all([this.client.login(token),ready]);check(this.config.discord.applicationId&&this.client.application.id===this.config.discord.applicationId,'BOT_APPLICATION_MISMATCH');await this.client.guilds.fetch(this.config.discord.guildId);this.verifiedInstallation=true;this.notifications?.start(async(kind,body)=>{
      if(!this.verifiedInstallation)return {state:'blocked'};
      if(kind==='luma')return this.notifyLumaImport(body);
      const task=await this.pipeline.owner.task(body.id,body.actor);if(task.revision!==body.revision)return {state:'stale'};
      return this.deliver(task);
    });}catch(e){await this.client.destroy();throw e;}finally{clearTimeout(timer);}
  }
  async register(){
    check(this.verifiedInstallation,'BOT_INSTALLATION_NOT_VERIFIED');
    const guild=await this.client.guilds.fetch(this.config.discord.guildId);const existing=(await guild.commands.fetch()).find(c=>c.name==='kotodama'&&c.applicationId===this.client.application.id);
    const file=path.join(this.config.dataDir,'discord-command.json');let owned=null;try{owned=JSON.parse(await readFile(file,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
    if(existing)check(owned?.commandId===existing.id&&owned?.guildId===guild.id,'EXISTING_COMMAND_NOT_OWNED');
    const result=existing?await guild.commands.edit(existing.id,commandDefinition):await guild.commands.create(commandDefinition);
    await atomicJson(file,{commandId:result.id,guildId:guild.id,definitionDigest:digest(commandDefinition)});return {commandId:result.id,guildId:guild.id};
  }
  async source(message,{attachments=true}={}){
    check(message.guildId===this.config.discord.guildId&&!message.author?.bot&&!message.webhookId&&!message.partial,'MESSAGE_NOT_HUMAN');
    const readers=await this.readers(message.channel);let text=message.content??'';const coverage=[];
    if(attachments)for(const a of message.attachments.values()){
      const item={id:a.id,name:a.name,read:false};coverage.push(item);
      if(a.size>4000000||!(/^(text\/|application\/(json|csv))/.test(a.contentType??'')||/\.(txt|md|csv|json)$/i.test(a.name??''))){item.reason='unsupported_or_oversize';continue;}
      try{const url=new URL(a.url);check(url.protocol==='https:'&&['cdn.discordapp.com','media.discordapp.net'].includes(url.hostname),'ATTACHMENT_ORIGIN_REFUSED');const r=await fetch(url,{redirect:'error',signal:AbortSignal.timeout(15000)});check(r.ok,'ATTACHMENT_FETCH_FAILED');
        const reader=r.body.getReader();const chunks=[];let size=0;try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;check(size<=4000000,'ATTACHMENT_SIZE_LIMIT');chunks.push(value);}}finally{await reader.cancel();}
        const bytes=Buffer.concat(chunks);text+='\n\n添付 '+a.name+'\n'+new TextDecoder('utf-8',{fatal:true}).decode(bytes);item.read=true;item.sha256=digest(bytes);
      }catch(e){item.reason=errorCode(e);}
    }
    const current=await this.readers(message.channel);check(readers.every(a=>current.includes(a)),'SOURCE_AUDIENCE_CHANGED');
    return {provider:'discord',guildId:message.guildId,channelId:message.channelId,sourceId:message.id,actorId:message.author.id,readers,revision:message.editedTimestamp??message.createdTimestamp,final:true,text,metadata:{kind:'text',url:message.url,attachments:coverage,createdAt:message.createdAt.toISOString()}};
  }
  async message(message,{edited=false}={}){
    const cfg=this.policy();if(!this.verifiedInstallation||message.guildId!==cfg.discord.guildId||!cfg.discord.textChannelIds.includes(message.channelId)||message.author?.bot||message.webhookId||message.partial)return;
    const source=await this.source(message);
    const operator=cfg.discord.operators.includes(message.author.id),mentioned=message.mentions.users.has(this.client.user.id);
    // In an agent channel a new operator message is for the Bot unless it names
    // someone else or replies to another message. Editing an old message never
    // starts work without an @mention, so a typo fix cannot re-run a Task.
    const agentChannel=cfg.discord.agentChannelIds.includes(message.channelId);
    const others=[...message.mentions.users.keys()].some(id=>id!==this.client.user.id)||(message.mentions.roles?.size??0)>0||Boolean(message.reference?.messageId&&message.mentions.repliedUser?.id!==this.client.user.id);
    const forBot=mentioned||(agentChannel&&!edited&&!others);
    const addressed=operator&&forBot;
    source.metadata.directlyAddressed=operator&&mentioned;if(agentChannel)source.metadata.agentChannel=true;
    await this.pipeline.ingest(source,{execute:addressed,reply:addressed});
  }
  // Immediate DM to the requester when conversation became running work; the result follows on completion.
  async acknowledgeTask(task,{revised=false}={}){
    if(!this.verifiedInstallation)return {state:'blocked'};this.operator(task.actor);
    // Quiet hours hold every DM; the completion notice follows once they end.
    if(this.notifications?.quiet())return {state:'quiet'};
    const text=`${revised?'作業内容を更新して、走り直しています':'走り始めました'}：${task.title}\nID: ${task.id}\n終わったら、このDMで結果を届けます。止めるときは /kotodama stop でこのIDを指定してください。`;
    const user=await this.client.users.fetch(task.actor);const message=await user.send({content:shortText(text),allowedMentions:{parse:[]}});
    check(message?.id,'NOTIFICATION_SEND_UNCONFIRMED');return {state:'sent'};
  }
  async withdraw(message){if(!this.verifiedInstallation)return;if(message.guildId!==this.config.discord.guildId)return;const key=sourceIdentity({provider:'discord',guildId:message.guildId,channelId:message.channelId,sourceId:message.id});const old=this.store.sourceInternal(key);if(old)await this.pipeline.ingest({...old,revision:Math.max(Date.now(),old.revision+1),text:'',withdrawn:true,metadata:{...old.metadata,withdrawalActorUnknown:true}},{execute:false});}
  interactionSource(i,text){return {provider:'discord',guildId:i.guildId,channelId:i.channelId,sourceId:i.id,actorId:i.user.id,readers:[i.user.id],revision:i.createdTimestamp,final:true,text,metadata:{kind:'command'}};}
  async interaction(i){
    if(this.verifiedInstallation&&i.guildId===this.config.discord.guildId&&(i.isButton?.()&&i.customId.startsWith('kotodama-consent:')||i.isChatInputCommand()&&i.commandName==='kotodama'&&i.options.getSubcommand()==='consent')){await this.consentInteraction(i);return;}
    if(!this.verifiedInstallation||!i.isChatInputCommand()||i.commandName!=='kotodama'||i.guildId!==this.config.discord.guildId)return;
    await i.deferReply({flags:MessageFlags.Ephemeral});
    try{this.operator(i.user.id);await this.member(i.user.id);const sub=i.options.getSubcommand();let text;
      if(sub==='do'){const request=i.options.getString('text',true),action=i.options.getString('action',true);const t=await this.pipeline.request(this.interactionSource(i,request),{title:request.slice(0,120),request,action});text=`受け付けました。\n${t.id}\n結果はこの仕事の「result」で確認できます。`;}
      else if(sub==='ask'){const source=this.interactionSource(i,i.options.getString('text',true));source.metadata.operation='ask';const receipt=await this.pipeline.ingest(source,{execute:false,reply:false});for(const b of receipt.contextSources??[]){const s=this.store.source(b.key,i.user.id);check(s.revision===b.revision,'CONTEXT_CHANGED');if(s.provider==='discord'){const channel=await this.client.channels.fetch(s.channelId);check(await this.canRead(channel,i.user.id),'SOURCE_ACCESS_DENIED');}}text=receipt.analysis==='deferred'?deferredAnalysisText(receipt.reason):receipt.answer??receipt.summary??'整理しました。';}
      else if(sub==='tasks'){const tasks=await this.pipeline.owner.tasks(i.user.id);const visible=[];for(const task of tasks)try{await this.pipeline.authorize(task,'read_result');visible.push(task);}catch{}text=visible.slice(0,15).map(t=>`${t.id} · ${taskStateText(t.state)}\n${t.title}`).join('\n')||'読取可能な仕事はまだありません。';}
      else if(sub==='result'){const result=await this.pipeline.result(i.options.getString('task',true),i.user.id);const files=await resultFiles(result,{artifactRoot:this.artifactRoot()});await i.editReply({content:shortText(result.summary),files,allowedMentions:{parse:[]}});return;}
      else if(sub==='stop'){await this.pipeline.stop(i.options.getString('task',true),i.user.id);text='停止を受け付けました。実行中の処理の終了を確認しています。';}
      else if(sub==='resume'){const t=await this.pipeline.resume(i.options.getString('task',true),i.user.id);text=`再開しました。${t.id}`;}
      else if(sub==='voice'){check(this.voice,'VOICE_NOT_CONFIGURED');const mode=i.options.getString('mode',true);
        text=voiceStatusText(await voiceCommand(this.voice,mode,{actor:i.user.id}));
      }
      await i.editReply({content:shortText(text),allowedMentions:{parse:[]}});
    }catch(e){await i.editReply({content:`実行できませんでした：${errorCode(e)}`,allowedMentions:{parse:[]}});}
  }
  async consentInteraction(i){
    await i.deferReply({flags:MessageFlags.Ephemeral});
    try{const cfg=this.policy();check(cfg.discord.voiceChannelId,'VOICE_CHANNEL_REQUIRED');const notice=voiceNotice(cfg);const revoke=i.isButton?.()&&i.customId.startsWith('kotodama-consent:revoke:');if(!revoke){const channel=await this.client.channels.fetch(cfg.discord.voiceChannelId);check(await this.canRead(channel,i.user.id),'SOURCE_ACCESS_DENIED');}
      if(i.isButton?.()){const [,action,noticeId]=i.customId.split(':');check(['agree','revoke'].includes(action)&&(action==='revoke'||noticeId===notice.id),'CONSENT_NOTICE_CHANGED');this.store.recordConsent({guild:cfg.discord.guildId,channel:cfg.discord.voiceChannelId,actor:i.user.id,notice:notice.id,granted:action==='agree',interactionId:i.id});if(action==='revoke'){await this.voice?.stopSpeech();const session=this.voice?.sessions.get(i.user.id);if(session)await this.voice.endSession(session,{drain:false});}}
      void this.voice?.control.check();
      const granted=this.store.consent(cfg.discord.guildId,cfg.discord.voiceChannelId,i.user.id,notice.id),managed=cfg.voice.consentMode==='owner_managed',optedOut=this.store.voiceOptedOut(cfg.discord.guildId,cfg.discord.voiceChannelId,i.user.id);
      const status=managed?(optedOut?'本人の希望で停止中':cfg.voice.participantIds.includes(i.user.id)?'人間側が管理する処理対象':'処理対象外'):(granted?'同意済み':'未同意');
      const buttons=managed?(optedOut?[{type:2,style:2,label:'自分の停止設定を解除する',custom_id:'kotodama-consent:agree:'+notice.id}]:[{type:2,style:2,label:'自分の音声処理を停止する',custom_id:'kotodama-consent:revoke:'+notice.id}]):[{type:2,style:1,label:'同意して音声処理を許可',custom_id:'kotodama-consent:agree:'+notice.id},{type:2,style:2,label:'音声処理の同意を取り消す',custom_id:'kotodama-consent:revoke:'+notice.id}];
      await i.editReply({content:`${managed?'プライバシーの説明・同意確認は人間側が責任を持つ運用です。Botの同意クリックは必須ではありません。\n\n':''}${notice.text}\n\nあなたの状態：${status}`,components:[{type:1,components:buttons}],allowedMentions:{parse:[]}});
    }catch(e){await i.editReply({content:`設定できませんでした：${errorCode(e)}`,components:[],allowedMentions:{parse:[]}});}
  }
  async notifyLumaImport(receipt,{readConfig=async()=>this.policy()}={}){
    if(this.notifications?.quiet()){this.notifications.defer(digest(['luma',receipt.key,receipt.sourceDigest,receipt.actorId]),'luma',receipt);return {state:'deferred'};}
    let claimed=false;
    try{
      const actor=receipt.actorId;
      const readSource=cfg=>{
        check(this.verifiedInstallation&&cfg.discord.guildId===this.config.discord.guildId,'BOT_INSTALLATION_NOT_VERIFIED');
        check(cfg.bridge.enabled&&cfg.bridge.actorId===actor&&cfg.discord.operators.includes(actor),'OPERATOR_REQUIRED');
        check(cfg.integrations.luma?.eventRef===receipt.eventRef,'EVENT_NOT_ALLOWED');
        const source=this.store.source(receipt.key,actor);
        check(source.provider==='luma'&&source.final&&source.guildId===cfg.discord.guildId&&source.channelId===cfg.discord.resultChannelId&&source.actorId===actor&&source.readers.length===1&&source.readers[0]===actor,'LUMA_SOURCE_BINDING_CHANGED');
        check(source.revision===receipt.revision&&source.sourceId===receipt.eventRef+':guest-snapshot'&&source.metadata?.kind==='guest_snapshot'&&source.metadata.imported===true&&source.metadata.eventRef===receipt.eventRef&&source.metadata.sourceDigest===receipt.sourceDigest,'SOURCE_CHANGED');
        return source;
      };
      const cfg=await readConfig();readSource(cfg);
      const member=await this.member(actor);check(member.id===actor&&member.guild.id===cfg.discord.guildId,'GUILD_MEMBER_REQUIRED');
      const user=await this.client.users.fetch(actor,{force:true});check(user.id===actor,'NOTIFICATION_RECIPIENT_MISMATCH');
      const channel=await this.client.channels.fetch(cfg.discord.resultChannelId,{force:true});check(channel?.guildId===cfg.discord.guildId&&await this.canRead(channel,actor),'SOURCE_ACCESS_DENIED');
      const latest=await readConfig();check(latest.discord.resultChannelId===channel.id,'SOURCE_ACCESS_DENIED');const source=readSource(latest);
      const records=source.metadata.records;check(Array.isArray(records)&&records.length<=10000&&records.every(row=>row&&[row.personKey,row.ticketKey].every(key=>key===null||typeof key==='string'&&/^[a-f0-9]{64}$/.test(key))),'LUMA_SUMMARY_INVALID');
      const people=new Set(records.map(row=>row.personKey).filter(Boolean)).size,tickets=new Set(records.map(row=>row.ticketKey).filter(Boolean)).size;
      const text=`Lumaの取込が完了しました。\n取込行数: ${records.length}\n識別できた参加者: ${people}\n識別できたチケット: ${tickets}\nCSV取得後の変更は含みません。`;
      const key=digest(['luma-import',source.guildId,receipt.eventRef,receipt.sourceDigest,actor]);
      claimed=this.store.claimDelivery(key,text);if(!claimed)return {state:this.store.deliveryState(key)==='sent'?'already_sent':'unknown'};
      const message=await user.send({content:text,allowedMentions:{parse:[]}});check(message?.id,'NOTIFICATION_SEND_UNCONFIRMED');this.store.delivered(key,message.id);return {state:'sent'};
    }catch{if(claimed){this.onError('LUMA_IMPORT_NOTIFICATION_UNKNOWN');return {state:'unknown'};}return {state:'blocked'};}
  }
  async deliver(task){
    if(this.notifications?.quiet()){this.notifications.defer(digest(['task',task.id,task.revision]),'task',{id:task.id,revision:task.revision,actor:task.actor});return {state:'deferred'};}
    await this.pipeline.authorize(task,'read_result');await this.member(task.actor);const source=this.store.source(task.source_key,task.actor);const channel=await this.client.channels.fetch(source.channelId);check(await this.canRead(channel,task.actor),'SOURCE_ACCESS_DENIED');
    const key=digest([task.id,task.revision,'result']);const text=`仕事の成果ができました（確認待ち）。\n${task.id}\n${task.result.summary}`;
    const files=await resultFiles(task.result,{artifactRoot:this.artifactRoot()});await this.pipeline.authorize(task,'read_result');
    if(!this.store.claimDelivery(key,text))return;
    try{const user=await this.client.users.fetch(task.actor);const message=await user.send({content:shortText(text),files,allowedMentions:{parse:[]}});this.store.delivered(key,message.id);}catch{this.onError('RESULT_DELIVERY_UNKNOWN');}
  }
  async reply({source,text,contextSources=[]}){
    for(const b of contextSources){const s=this.store.source(b.key,source.actorId);check(s.revision===b.revision,'CONTEXT_CHANGED');}if(source.metadata?.kind==='voice'){
      await this.voice?.speak(text,{epoch:source.metadata.voiceEpoch,actorId:source.actorId,bindings:contextSources,authorizeAudience:async actors=>{for(const actor of actors){const channels=new Set();for(const b of contextSources){const s=this.store.source(b.key,actor);check(s.revision===b.revision,'CONTEXT_CHANGED');if(s.provider==='discord')channels.add(s.channelId);}for(const channelId of channels){const channel=await this.client.channels.fetch(channelId);check(await this.canRead(channel,actor),'SOURCE_ACCESS_DENIED');}}return actors;}});return;}
    await this.member(source.actorId);
    const channel=await this.client.channels.fetch(source.channelId);check(await this.canRead(channel,source.actorId),'SOURCE_ACCESS_DENIED');const user=await this.client.users.fetch(source.actorId);await user.send({content:shortText(text),allowedMentions:{parse:[]}});
  }
  async voiceAction({source,action}){await this.voice?.applyModelAction(action,source);}
  async backfill(actor,{limit=10000,signal}={}){
    await this.member(actor);const guild=await this.client.guilds.fetch(this.config.discord.guildId);const all=await guild.channels.fetch();const channels=new Map([...all.values()].filter(c=>c?.isTextBased()&&!c.isThread()).map(c=>[c.id,c]));
    const coverage={startedAt:new Date().toISOString(),channels:[],imported:0,limit,complete:false};
    const active=await guild.channels.fetchActiveThreads();for(const c of active.threads.values())channels.set(c.id,c);
    for(const parent of [...channels.values()].filter(c=>c.threads)){
      for(const category of ['public','joined_private']){let before;
        try{while(true){check(!signal?.aborted,'CANCELLED');const route=category==='public'?`/channels/${parent.id}/threads/archived/public`:`/channels/${parent.id}/users/@me/threads/archived/private`;
          const query=new URLSearchParams({limit:'100',...(before?{before}:{})});const page=await this.client.rest.get(route,{query});
          for(const raw of page.threads){const channel=await this.client.channels.fetch(raw.id);if(channel)channels.set(channel.id,channel);}
          if(!page.has_more||!page.threads.length)break;const last=page.threads.at(-1);before=category==='public'?last.thread_metadata.archive_timestamp:last.id;
        }}catch(e){coverage.channels.push({id:parent.id,kind:category,state:'unavailable',reason:errorCode(e)});}
      }
    }
    for(const channel of channels.values()){
      check(!signal?.aborted,'CANCELLED');if(!(await this.canRead(channel,actor))){coverage.channels.push({id:channel.id,state:'not_authorized'});continue;}
      let before,count=0,state='complete';
      try{while(true){check(!signal?.aborted,'CANCELLED');if(coverage.imported>=limit){state='limit_reached';break;}const pageLimit=Math.min(100,limit-coverage.imported),page=await channel.messages.fetch({limit:pageLimit,...(before?{before}:{})});if(!page.size)break;
        for(const message of page.values()){if(message.author.bot||message.webhookId)continue;const source=await this.source(message);this.store.ingest(source);count++;coverage.imported++;}
        before=page.last().id;if(page.size<pageLimit)break;
      }}catch(e){state='failed';this.onError(errorCode(e));}
      coverage.channels.push({id:channel.id,state,count});
    }
    coverage.complete=coverage.channels.every(c=>['complete','not_authorized'].includes(c.state))&&coverage.imported<limit;coverage.finishedAt=new Date().toISOString();
    await atomicJson(path.join(this.config.dataDir,'latest-import-coverage.json'),coverage);return coverage;
  }
  async close(){this.verifiedInstallation=false;await this.notifications?.stop();await this.voice?.dispose();await this.client.destroy();}
}
