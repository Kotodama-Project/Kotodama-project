#!/usr/bin/env node
import {parseArgs} from 'node:util';
import {readFile,writeFile,mkdir,lstat} from 'node:fs/promises';
import path from 'node:path';
import {exampleConfig,loadConfig} from '../src/config.mjs';
import {check,atomicJson,errorCode,redact,uid,digest} from '../src/common.mjs';
import {Store} from '../src/store.mjs';
import {startRuntime,controlCommand} from '../src/runtime.mjs';
import {DiscordAdapter} from '../src/discord.mjs';
import {exportDocument,readExport} from '../src/documents.mjs';
import {parseLumaCsv,lumaSource,parseIcs} from '../src/integrations.mjs';
import {BrowserCli} from '../src/browser.mjs';
import {CliAnalyzer} from '../src/llm.mjs';

const HELP=`ことだま — Discordの会話から仕事へ\n\n  init --config PATH [--guild ID --app ID --operator ID --channel ID --workspace PATH]\n  doctor --config PATH\n  start --config PATH [--offline]\n  register --config PATH\n  status | shutdown --config PATH --actor ID\n  tasks | result | stop | resume --config PATH --actor ID [--task ID]\n  request --config PATH --actor ID --action research|summarize|write_file|develop --text TEXT\n  voice --config PATH --actor ID --mode assist|minutes|join|pause|resume|stop_speech|leave\n  import-discord --config PATH --actor ID [--limit 10000]\n  import-luma --config PATH --actor ID --file CSV\n  import-file --config PATH --actor ID --file TEXT\n  export --config PATH --actor ID --output FILE\n  read-export --config PATH --actor ID --file FILE\n  browser list|open|read|click|fill|scroll|screenshot --config PATH [--tab 0 --url URL --selector CSS --role ROLE --name NAME --label LABEL --text TEXT --x N --y N --output FILE]\n\n--json で機械可読の結果を返します。秘密値は引数へ渡さず環境変数に設定してください。`;
const spec={config:{type:'string',default:'.kotodama/config.json'},json:{type:'boolean',default:false},offline:{type:'boolean',default:false},guild:{type:'string'},app:{type:'string'},operator:{type:'string'},channel:{type:'string'},workspace:{type:'string'},actor:{type:'string'},task:{type:'string'},action:{type:'string'},text:{type:'string'},mode:{type:'string'},file:{type:'string'},output:{type:'string'},limit:{type:'string'},tab:{type:'string',default:'0'},url:{type:'string'},'expected-url':{type:'string'},checked:{type:'boolean'},selector:{type:'string'},role:{type:'string'},name:{type:'string'},label:{type:'string'},x:{type:'string'},y:{type:'string'},delta:{type:'string'},help:{type:'boolean'}};
const {values:options,positionals}=parseArgs({options:spec,allowPositionals:true});const [command='help',sub]=positionals;
function output(value){if(options.json)console.log(JSON.stringify(redact(value)));else if(typeof value==='string')console.log(value);else console.log(JSON.stringify(redact(value),null,2));}
try{
  if(command==='help'||options.help){output(HELP);process.exit(0);}
  const filename=path.resolve(options.config);
  if(command==='init'){
    try{await lstat(filename);throw new Error('CONFIG_ALREADY_EXISTS');}catch(e){if(e.code!=='ENOENT')throw e;}
    const cfg=exampleConfig({guildId:options.guild,applicationId:options.app,operatorId:options.operator,channelId:options.channel,workspace:options.workspace??path.resolve('.')});
    await atomicJson(filename,cfg);output({state:'initialized',config:filename,next:'doctorで設定・認証・実行器を確認してください。初期音声予算は0です。'});process.exit(0);
  }
  const config=await loadConfig(filename);
  if(command==='doctor'){
    const {spawnSync}=await import('node:child_process');const binary=cmd=>{const r=spawnSync(cmd,['--version'],{encoding:'utf8',windowsHide:true});return !r.error&&r.status===0;};
    output({node:process.versions.node,nodeSupported:Number(process.versions.node.split('.')[0])>=24,taskOwner:config.owner.kind,
      discordCredentialPresent:Boolean(process.env[config.discord.botTokenEnv]),openaiCredentialPresent:Boolean(process.env[config.voice.apiKeyEnv]),
      analyzerAdapter:config.analyzer.kind,analyzerAvailable:config.analyzer.kind==='responses'?Boolean(process.env[config.analyzer.apiKeyEnv]):binary(config.analyzer.executable),workerAvailable:binary(config.worker.executable),gitAvailable:binary('git'),
      voiceConfigured:Boolean(config.discord.voiceChannelId),privacyMode:config.voice.consentMode,voiceParticipantsConfigured:config.voice.participantIds.length,audioBudgetSeconds:config.voice.maxDailyAudioSeconds,
      browserConfigured:Boolean(config.browser.cdpUrl),localWriteWorkerSupported:process.platform!=='win32',providerVerified:false});
  }else if(command==='start'){
    const runtime=await startRuntime(filename,{offline:options.offline});const stop=()=>runtime.close().then(()=>process.exit(0)).catch(()=>process.exit(1));process.once('SIGINT',stop);process.once('SIGTERM',stop);
  }else if(['status','shutdown','tasks','result','stop','resume','voice','request'].includes(command)){
    if(command!=='status')check(options.actor&&config.discord.operators.includes(options.actor),'OPERATOR_REQUIRED');
    output(await controlCommand(config,{action:command,actor:options.actor,taskId:options.task,mode:options.mode,operation:options.action,text:options.text,requestId:uid('cli')}));
  }else if(['register','import-discord'].includes(command)){
    check(!options.offline,'LIVE_DISCORD_REQUIRED');const store=new Store(config.dataDir);check(!store.lock(),'STOP_RUNTIME_BEFORE_MAINTENANCE');const adapter=new DiscordAdapter({config,store,pipeline:{ingest:async()=>{}},onError:()=>{}});
    try{await adapter.login();if(command==='register')output(await adapter.register());else{check(config.discord.operators.includes(options.actor),'OPERATOR_REQUIRED');output(await adapter.backfill(options.actor,{limit:Number(options.limit??10000)}));}}finally{await adapter.close();store.close();}
  }else if(['import-luma','import-file','export','read-export'].includes(command)){
    check(config.discord.operators.includes(options.actor),'OPERATOR_REQUIRED');const store=new Store(config.dataDir);
    try{
      if(command==='export'){check(options.output,'OUTPUT_REQUIRED');let coverage=null;try{coverage=JSON.parse(await readFile(path.join(config.dataDir,'latest-import-coverage.json'),'utf8'));}catch{}output(await exportDocument(store,options.actor,path.resolve(options.output),{coverage}));}
      else if(command==='read-export'){check(options.file,'FILE_REQUIRED');output((await readExport(store,options.actor,path.resolve(options.file))).toString('utf8'));}
      else{
        check(options.file,'FILE_REQUIRED');const bytes=await readFile(options.file);check(bytes.length<=2000000,'IMPORT_SIZE_LIMIT');let source;
        if(command==='import-luma'){check(config.integrations.luma,'LUMA_NOT_CONFIGURED');const parsed=parseLumaCsv(bytes.toString('utf8'),{eventRef:config.integrations.luma.eventRef});source=lumaSource(parsed,{guildId:config.discord.guildId,channelId:config.discord.resultChannelId,actorId:options.actor,readers:[options.actor]});const old=store.sourceInternal(digest([source.provider,source.guildId,source.channelId,source.sourceId]));if(old?.metadata?.sourceDigest===parsed.sourceDigest){output({state:'duplicate'});store.close();process.exit(0);}}
        else source={provider:'file',guildId:config.discord.guildId,channelId:config.discord.resultChannelId,sourceId:digest(path.resolve(options.file)),actorId:options.actor,readers:[options.actor],revision:Date.now(),final:true,text:bytes.toString('utf8'),metadata:{kind:'file',imported:true,sha256:digest(bytes)}};
        const receipt=store.ingest(source);const s=store.source(receipt.key,options.actor);
        if(!options.offline){const result=await new CliAnalyzer(config).analyze(s,[]);store.saveIntents(s,result.intents,options.actor);}
        output({...receipt,analysis:options.offline?'not_run':'completed',execution:false});
      }
    }finally{store.close();}
  }else if(command==='browser'){
    const browser=await new BrowserCli(config.browser).connect();try{const tab=Number(options.tab);let result;
      if(sub==='list')result=browser.list();else if(sub==='open')result={tab:await browser.open(options.url)};else if(sub==='read')result=await browser.read(tab);
      else if(sub==='click')result=await browser.click(tab,{role:options.role,name:options.name,selector:options.selector,x:options.x===undefined?undefined:Number(options.x),y:options.y===undefined?undefined:Number(options.y),expectedUrl:options['expected-url']});
      else if(sub==='fill')result=await browser.fill(tab,{label:options.label,selector:options.selector,text:options.text,expectedUrl:options['expected-url']});else if(sub==='check')result=await browser.setChecked(tab,{selector:options.selector,checked:options.checked===true,expectedUrl:options['expected-url']});else if(sub==='scroll')result=await browser.scroll(tab,{selector:options.selector,deltaY:Number(options.delta)});
      else if(sub==='screenshot'){check(options.output,'OUTPUT_REQUIRED');result=await browser.screenshot(tab,path.resolve(options.output),options.selector);}else throw new Error('BROWSER_COMMAND_INVALID');output(result);
    }finally{await browser.disconnect();}
  }else throw new Error('UNKNOWN_COMMAND');
}catch(e){output({ok:false,error:errorCode(e),message:e?.issues?'設定の項目を確認してください。':undefined});process.exitCode=1;}
