import path from 'node:path';
import {z} from 'zod';
import {readJson, check, inside} from './common.mjs';
import {immutableImage} from './verification.mjs';
import {DEFAULT_ANALYSIS_LIMITS} from './analysis-admission.mjs';
import {DEFAULT_TASK_LIMITS} from './task-admission.mjs';
import {isTimeZone} from './time-zone.mjs';
import {WORKER_ACTIONS,DEFAULT_WORKER_ACTIONS} from './capability-lanes.mjs';
import {PROJECT_SKILL_ACTIONS,PROJECT_SKILL_NAME,MAX_PROJECT_SKILLS} from './project-skill-input.mjs';

const id = z.string().regex(/^\d{5,24}$/);
const envName=z.string().regex(/^[A-Z_][A-Z0-9_]*$/);
const projectSkillNames=z.array(z.string().min(1).max(64).regex(PROJECT_SKILL_NAME)).max(MAX_PROJECT_SKILLS).refine(names=>new Set(names).size===names.length,{message:'PROJECT_SKILL_DUPLICATE'});
const projectSkills=z.object(Object.fromEntries(PROJECT_SKILL_ACTIONS.map(action=>[action,projectSkillNames.optional()]))).strict();
const commandBase = z.object({executable:z.string().min(1),args:z.array(z.string()).default([]),model:z.string().optional(),codexHome:z.string().min(1).optional(),ignoreUserConfig:z.boolean().default(true),timeoutSeconds:z.number().int().min(5).max(3600).default(300)}).strict();
const command=commandBase.extend({model:z.string().default('gpt-5.6-luna'),fallback:commandBase.extend({model:z.string().min(1)}).optional()});
const analysisLimitsConfig=z.object({maxConcurrent:z.number().int().min(1).max(16),maxQueued:z.number().int().min(0).max(256),maxPerRoom:z.number().int().min(1).max(16),maxPerActor:z.number().int().min(1).max(16),maxDailyAnalyses:z.number().int().min(0).max(1000000),maxTotalAnalyses:z.number().int().min(0).max(10000000)}).partial().strict().transform(value=>({...DEFAULT_ANALYSIS_LIMITS,...value})).prefault({});
const taskLimitsConfig=z.object({maxConcurrentReadOnly:z.number().int().min(1).max(4),maxQueued:z.number().int().min(0).max(256),maxQueuedBytes:z.number().int().min(0).max(1048576),maxInputBytes:z.number().int().min(1024).max(8388608),maxResultBytes:z.number().int().min(1024).max(67108864)}).partial().strict().transform(value=>({...DEFAULT_TASK_LIMITS,...value})).prefault({});
const analyzerContext={limits:analysisLimitsConfig,maxContextSources:z.number().int().min(1).max(30).default(12),maxContextChars:z.number().int().min(1000).max(120000).default(24000),maxTaskContextItems:z.number().int().min(0).max(10).default(5),maxTaskContextChars:z.number().int().min(0).max(40000).default(12000)};
const analyzerConfig=z.union([
  command.extend({kind:z.literal('codex_cli').default('codex_cli'),...analyzerContext}),
  z.object({kind:z.literal('responses'),model:z.string().default('gpt-5.6-luna'),apiKeyEnv:envName.default('OPENAI_API_KEY'),baseUrl:z.string().url().default('https://api.openai.com/v1'),timeoutSeconds:z.number().int().min(5).max(300).default(60),maxOutputTokens:z.number().int().min(256).max(8000).default(3000),reasoningEffort:z.enum(['low','medium','high']).default('low'),...analyzerContext}).strict()
]);
const proactive=z.object({enabled:z.boolean().default(false),cues:z.array(z.enum(['question','fact_check','schedule'])).min(1).max(3).default(['question','fact_check','schedule']),minIntervalSeconds:z.number().int().min(600).max(86400).default(600),maxPerDay:z.number().int().min(0).max(3).default(3),declineCooldownSeconds:z.number().int().min(3600).max(86400).default(3600),checkIntervalSeconds:z.number().int().min(30).max(86400).default(30),maxDailyChecks:z.number().int().min(0).max(200).default(200)}).strict().prefault({});
const voice=z.object({proactive,mode:z.enum(['assist','minutes']).default('assist'),autoJoin:z.boolean().default(false),apiKeyEnv:envName.default('OPENAI_API_KEY'),
  rotation:z.object({enabled:z.boolean().default(false),channelId:id.optional(),maxExtendSeconds:z.number().int().min(0).max(120).default(60),postWaitSeconds:z.number().int().min(1).max(120).default(60)}).strict().prefault({}),
  consentMode:z.enum(['owner_managed','participant_opt_in']).default('owner_managed'),participantIds:z.array(id).default([]),
  assistModel:z.literal('gpt-live-1').default('gpt-live-1'),minutesModel:z.literal('gpt-live-transcribe').default('gpt-live-transcribe'),
  transcriptSource:z.enum(['live','local']).default('live'),contextCorrection:z.boolean().default(false),naturalConversation:z.boolean().default(false),conversationStart:z.enum(['wake','speech']).default('wake'),wakeWords:z.array(z.string().min(1).max(40)).min(1).max(20).default(['ことだま','ことたま','コトダマ','コトタマ','言霊','kotodama','エージェント']),localAsr:z.object({url:z.string().url(),protocol:z.enum(['openai','kotodama']).default('openai'),model:z.string().min(1).max(200),language:z.string().min(1).max(20).default('ja'),initialPrompt:z.string().max(1000).default(''),hotwords:z.string().max(1000).default(''),apiKeyEnv:envName.optional(),timeoutSeconds:z.number().int().min(5).max(120).default(20),maxUtteranceSeconds:z.number().int().min(3).max(120).default(30)}).strict().optional(),
  maxSessionSeconds:z.number().int().min(10).max(14400).default(1200),maxDailyAudioSeconds:z.number().int().min(0).max(86400).default(0),
  maxTotalAudioSeconds:z.number().int().min(0).max(10000000).optional(),
  vadSilenceMs:z.number().int().min(300).max(3000).default(1000),conversationIdleSeconds:z.number().int().min(30).max(600).default(120),replySeconds:z.number().int().min(3).max(60).default(30),outputPrefillMs:z.number().int().min(0).max(500).default(120),maxOutputQueueMs:z.number().int().min(200).max(2000).default(500),storeAudio:z.boolean().default(false)}).strict().superRefine((value,ctx)=>{if(value.transcriptSource==='local'&&!value.localAsr)ctx.addIssue({code:'custom',path:['localAsr'],message:'LOCAL_ASR_CONFIG_REQUIRED'});if(value.outputPrefillMs>value.maxOutputQueueMs)ctx.addIssue({code:'custom',path:['outputPrefillMs'],message:'VOICE_PREFILL_EXCEEDS_QUEUE'});}).prefault({});
export const Config = z.object({
  version:z.literal(1), installation:z.string().regex(/^[a-z0-9-]{1,64}$/), dataDir:z.string().default('data'),
  agentBinding:z.object({agentId:z.string().regex(/^[a-z0-9-]{1,64}$/),vmId:z.string().regex(/^[a-zA-Z0-9-]{1,64}$/)}).strict().optional(),
  discord:z.object({guildId:id,applicationId:id.optional(), textChannelIds:z.array(id).min(1), voiceChannelId:id.optional(), resultChannelId:id,
    operators:z.array(id).min(1), agentChannelIds:z.array(id).default([]), consentingUsers:z.array(id).default([]),unattributedUsers:z.array(id).default([]),botTokenEnv:z.string().regex(/^[A-Z_][A-Z0-9_]*$/).default('DISCORD_BOT_TOKEN')}).strict(),
  voice,
  voicePool:z.object({rooms:z.array(z.object({channelId:id,mode:z.enum(['assist','minutes']).optional(),autoJoin:z.boolean().optional(),participantIds:z.array(id).optional()}).strict()).min(1).max(8),bots:z.array(z.object({applicationId:id,botTokenEnv:envName}).strict()).max(7).default([])}).strict().optional(),
  archive:z.object({enabled:z.boolean(),archiveRoot:z.string(),journalPath:z.string(),retentionPolicyRef:z.string(),sourceRef:z.string(),actorId:id,readers:z.array(id).min(1),ffmpeg:z.string().default('ffmpeg'),whisperEndpoint:z.string().url(),batchMs:z.number().int().min(20).max(250).default(250),rotationMs:z.number().int().min(1000).max(60000).default(55000),maxPendingSessions:z.number().int().min(1).max(128).default(16),maxJournalPcmBytes:z.number().int().min(1000000).max(1073741824).default(536870912),maxPcmBytes:z.number().int().min(1000000).max(134217728).default(134217728),vocabulary:z.array(z.string().max(100)).max(100).default([])}).strict().optional(),
  interaction:z.object({clarification:z.enum(['once','off']).default('once'),clarificationWindowSeconds:z.number().int().min(60).max(3600).default(600)}).strict().prefault({}),
  notifications:z.object({taskProgress:z.object({enabled:z.boolean().default(false),minIntervalSeconds:z.number().int().min(30).max(3600).default(30),maxUpdates:z.number().int().min(1).max(6).default(6)}).strict().prefault({}),quietHours:z.object({enabled:z.boolean().default(false),startHour:z.number().int().min(0).max(23).default(22),endHour:z.number().int().min(0).max(23).default(9),timeZone:z.string().min(1).max(100).refine(isTimeZone,{message:'TIME_ZONE_INVALID'}).default('Asia/Tokyo')}).strict().prefault({})}).strict().prefault({}),
  analyzer:analyzerConfig.prefault({kind:'codex_cli',executable:'codex',args:[],model:'gpt-5.6-luna',timeoutSeconds:120}),
  worker:command.extend({workspace:z.string(),actions:z.array(z.enum(WORKER_ACTIONS)).default([...DEFAULT_WORKER_ACTIONS]),
    taskLimits:taskLimitsConfig,
    projectSkills:projectSkills.optional(),
    swarm:z.object({pythonExecutable:z.string().min(1).default('python3'),codexExecutable:z.string().min(1).default('codex'),codexHome:z.string().min(1).optional(),maxDailyTasks:z.number().int().min(0).max(100).default(0),ownerRef:z.string().regex(/^ref\/[A-Za-z0-9][A-Za-z0-9._/@-]{1,180}$/),authorityRef:z.string().regex(/^ref\/[A-Za-z0-9][A-Za-z0-9._/@-]{1,180}$/),authorityExpiresAt:z.string().datetime({offset:true}),timeoutSeconds:z.number().int().min(20).max(1260).default(1260)}).strict().optional(),
    companyPack:z.object({pythonExecutable:z.string().min(1).default('python3'),outputRoot:z.string().min(1),ownerRef:z.string().regex(/^ref\/[A-Za-z0-9][A-Za-z0-9._/@-]{1,180}$/),workOrderRef:z.string().regex(/^work-order:[A-Za-z0-9][A-Za-z0-9._/-]{1,127}$/),capabilityRef:z.string().regex(/^capability:[A-Za-z0-9][A-Za-z0-9._/-]{1,127}$/),retentionPolicyRef:z.string().min(1).max(200),authorityExpiresAt:z.string().datetime({offset:true})}).strict().optional(),
    channelWorkspaces:z.object({channelIds:z.array(id).min(1).max(8),maxAgeSeconds:z.number().int().min(60).max(1800).default(1800),generation:z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/).default('initial')}).strict().optional(),
    verification:z.object({kind:z.literal('docker'),image:z.string().regex(immutableImage),executable:z.string().min(1).default('docker'),memoryMb:z.number().int().min(128).max(8192).default(512),cpus:z.number().min(0.1).max(8).default(1),pidsLimit:z.number().int().min(16).max(512).default(64)}).strict().optional(),
    verify:z.array(z.object({executable:z.string().min(1),args:z.array(z.string())}).strict()).default([]),maxArtifactBytes:z.number().int().min(1000).max(50000000).default(5000000)}).strict(),
  owner:z.discriminatedUnion('kind',[
    z.object({kind:z.literal('local')}).strict(),
    z.object({kind:z.literal('remote'),url:z.string().url(),tokenEnv:z.string().min(1)}).strict()
  ]).default({kind:'local'}),
  bridge:z.object({enabled:z.boolean().default(false),host:z.enum(['127.0.0.1','::1']).default('127.0.0.1'),port:z.number().int().min(1024).max(65535).default(18796),tokenEnv:z.string().default('KOTODAMA_BRIDGE_TOKEN'),actorId:id.optional()}).strict().prefault({}),
  browser:z.object({cdpUrl:z.string().url().optional(),allowedOrigins:z.array(z.string().url()).default([])}).strict().prefault({}),
  integrations:z.object({luma:z.object({eventUrl:z.string().url(),eventRef:z.string().min(1)}).strict().optional()}).strict().prefault({}),
  dots:z.object({enabled:z.boolean().default(false),actorId:id.optional(),channelIds:z.array(id).max(20).default([]),replyMode:z.enum(['channel','dm']).default('channel'),requestTtlSeconds:z.number().int().min(300).max(86400).default(3600),draftRetentionDays:z.number().int().min(1).max(30).default(7)}).strict().prefault({})
}).strict().superRefine((value,ctx)=>{if(value.voice.proactive.enabled&&(value.voice.transcriptSource!=='local'||value.voice.naturalConversation||value.analyzer.kind!=='responses'))ctx.addIssue({code:'custom',path:['voice','proactive'],message:'PROACTIVE_REQUIRES_LOCAL_TRANSCRIPT_AND_RESPONSES'});if(value.voice.rotation.enabled&&(!value.voice.rotation.channelId||!value.discord.voiceChannelId||value.voice.rotation.channelId===value.discord.voiceChannelId||value.voice.transcriptSource!=='local'))ctx.addIssue({code:'custom',path:['voice','rotation'],message:'VOICE_ROTATION_SCOPE_REQUIRED'});});

export async function loadConfig(filename) {
  const config=Config.parse(await readJson(filename));check(Boolean(config.archive?.enabled)===config.voice.storeAudio,'ARCHIVE_RECORDING_CONFIG_REQUIRED');if(config.archive?.enabled){check(config.voice.transcriptSource==='local'&&config.voice.consentMode==='owner_managed'&&config.agentBinding&&config.owner.kind==='local','ARCHIVE_BINDING_REQUIRED');const endpoint=new URL(config.archive.whisperEndpoint);check(['127.0.0.1','localhost',new URL(config.voice.localAsr.url).hostname].includes(endpoint.hostname),'ARCHIVE_ASR_HOST_MISMATCH');}
  check(!config.notifications.taskProgress.enabled||config.owner.kind==='local','QUIET_PROGRESS_LOCAL_OWNER_REQUIRED');
  if(config.worker.channelWorkspaces)check(new Set(config.worker.channelWorkspaces.channelIds).size===config.worker.channelWorkspaces.channelIds.length,'CHANNEL_WORKSPACE_DUPLICATE_CHANNEL');
  if(config.voicePool){
    const channels=[config.discord.voiceChannelId,...config.voicePool.rooms.map(room=>room.channelId)].filter(Boolean);
    const applications=[config.discord.applicationId,...config.voicePool.bots.map(bot=>bot.applicationId)];
    const tokens=[config.discord.botTokenEnv,...config.voicePool.bots.map(bot=>bot.botTokenEnv)];
    check(channels.length<=8&&new Set(channels).size===channels.length,'VOICE_POOL_DUPLICATE_ROOM');
    check(applications.every(Boolean)&&new Set(applications).size===applications.length&&new Set(tokens).size===tokens.length,'VOICE_POOL_DUPLICATE_BOT');
    check(!config.archive?.enabled&&!config.voice.storeAudio&&!config.voice.rotation.enabled,'VOICE_POOL_ARCHIVE_SCOPE_REQUIRED');
  }
  const root=path.dirname(path.resolve(filename));
  config.dataDir=path.resolve(root,config.dataDir);if(config.archive?.enabled)check(path.isAbsolute(config.archive.archiveRoot)&&path.isAbsolute(config.archive.journalPath)&&inside(config.dataDir,config.archive.journalPath),'ARCHIVE_PATH_SCOPE');config.worker.workspace=path.resolve(root,config.worker.workspace);
  if(config.worker.companyPack)config.worker.companyPack.outputRoot=path.resolve(root,config.worker.companyPack.outputRoot);
  const commandAdapters=[config.worker,config.worker.fallback,...(config.analyzer.kind==='codex_cli'?[config.analyzer,config.analyzer.fallback]:[])];for(const adapter of commandAdapters)if(adapter?.codexHome)adapter.codexHome=path.resolve(root,adapter.codexHome);
  check(new Set(config.discord.operators).size===config.discord.operators.length,'DUPLICATE_OPERATOR');
  // Agent channels are text channels the Bot already reads; they only drop the @mention requirement for operators.
  check(config.discord.agentChannelIds.every(channel=>config.discord.textChannelIds.includes(channel)),'AGENT_CHANNEL_NOT_TEXT_CHANNEL');
  if(config.bridge.enabled)check(config.bridge.actorId&&config.discord.operators.includes(config.bridge.actorId),'BRIDGE_ACTOR_REQUIRED');
  if(config.dots.enabled){check(config.dots.actorId&&config.discord.operators.includes(config.dots.actorId),'DOTS_ACTOR_REQUIRED');check(config.dots.channelIds.length>0&&config.dots.channelIds.every(channel=>config.discord.textChannelIds.includes(channel)),'DOTS_CHANNEL_REQUIRED');}
  if(config.browser.cdpUrl) {const u=new URL(config.browser.cdpUrl);check(['localhost','127.0.0.1','[::1]'].includes(u.hostname),'CDP_MUST_BE_LOOPBACK');}
  if(config.voice.localAsr){const u=new URL(config.voice.localAsr.url),host=u.hostname.toLowerCase(),v4=host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/)?.slice(1).map(Number);const privateHost=['localhost','127.0.0.1','::1','[::1]'].includes(host)||host.endsWith('.ts.net')||Boolean(v4&&(v4[0]===10||v4[0]===127||v4[0]===192&&v4[1]===168||v4[0]===172&&v4[1]>=16&&v4[1]<=31||v4[0]===100&&v4[1]>=64&&v4[1]<=127));check(u.protocol==='https:'||u.protocol==='http:'&&privateHost,'LOCAL_ASR_TRANSPORT_REFUSED');check(!u.username&&!u.password&&!u.search&&!u.hash,'LOCAL_ASR_URL_INVALID');}
  if(config.analyzer.kind==='responses'){const u=new URL(config.analyzer.baseUrl);check(u.protocol==='https:'||(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname)),'ANALYZER_TRANSPORT_REFUSED');check(!u.username&&!u.password&&!u.search&&!u.hash,'ANALYZER_URL_INVALID');}
  return config;
}
export function exampleConfig({guildId='100000000000000001',applicationId,operatorId='100000000000000002',channelId='100000000000000003',workspace='.'}={}) {
  return Config.parse({version:1,installation:'my-kotodama',discord:{guildId,applicationId,textChannelIds:[channelId],resultChannelId:channelId,operators:[operatorId]},voice:{consentMode:'owner_managed',participantIds:[operatorId]},worker:{executable:'codex',model:'gpt-5.6-luna',workspace}});
}
