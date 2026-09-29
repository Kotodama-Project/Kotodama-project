import {runCommand} from './command.mjs';
import path from 'node:path';
import {lstat} from 'node:fs/promises';
import {readArtifact} from './artifact.mjs';
import packageInfo from '../package.json' with {type:'json'};

export const PROBE_TIMEOUT_MS=5000;
export const PROBE_MAX_BYTES=16384;
const expectedPnpm=packageInfo.packageManager.split('@')[1];

export async function windowsPnpm({env=process.env}={}) {
  // Read recognized npm/pnpm shims as data; never execute a shell to inspect them.
  const searchPath=env.PATH??env.Path??'';
  for(const directory of searchPath.split(';').filter(Boolean).slice(0,64)) {
    const shimPath=path.join(directory,'pnpm.cmd');
    try {if(!(await lstat(shimPath)).isFile())break;}
    catch(error) {if(error.code==='ENOENT'||error.code==='ENOTDIR')continue;break;}
    try {
      const shim=(await readArtifact(shimPath,65536)).toString('utf8');
      const match=/"((?:%~dp0|%dp0%)[^"\r\n]+pnpm\.(?:cjs|mjs|js))"/i.exec(shim);
      if(match) {
        const relative=match[1].replace(/^%~dp0|^%dp0%/i,'');
        if(/[%!]/.test(relative)||!/[\\/]node_modules[\\/]pnpm[\\/]bin[\\/]pnpm\.(?:cjs|mjs|js)$/i.test(relative))break;
        const entry=path.resolve(directory,relative.replace(/^[\\/]+/,'').replace(/[\\/]/g,path.sep));
        if(!(await lstat(entry)).isFile())break;
        const info=JSON.parse((await readArtifact(path.join(path.dirname(entry),'../package.json'),65536)).toString('utf8'));
        if(info.name==='pnpm'&&typeof info.version==='string'&&/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(info.version))
          return {available:true,reason:null,version:info.version,source:'package_metadata',cliVerified:false};
      }
    } catch { /* Missing, linked, malformed or oversized files remain unverified. */ }
    // PATH selects the first shim. Read one reference/package only, never retry
    // thousands of duplicate references or report a different later installation.
    break;
  }
  return {available:false,reason:'package_metadata_unavailable',version:null,source:'package_metadata',cliVerified:false};
}

export async function probeTool(executable,args=['--version'],{timeoutMs=PROBE_TIMEOUT_MS,maxBytes=PROBE_MAX_BYTES}={}) {
  try {
    const result=await runCommand(executable,args,{timeoutMs,maxBytes});
    if(result.code!==0)return {available:false,reason:'exit_failed',version:null};
    const text=result.stdout.trim();
    const version=/^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(text)?text.replace(/^v/,''):null;
    return {available:true,reason:null,version};
  } catch(error) {
    const reason={COMMAND_TIMEOUT:'timeout',COMMAND_OUTPUT_LIMIT:'output_limit',STOP_UNCONFIRMED:'stop_unconfirmed',NATIVE_EXECUTABLE_REQUIRED:'native_executable_required'}[error.code]??'unavailable';
    return {available:false,reason,version:null};
  }
}

export async function diagnose(config,{platform=process.platform,nodeVersion=process.versions.node,env=process.env,probe=probeTool,pnpmMetadata=windowsPnpm}={}) {
  const probes=new Map();
  const once=(executable,args=['--version'])=>{
    const key=JSON.stringify([executable,args]);
    if(!probes.has(key))probes.set(key,Promise.resolve(probe(executable,args)));
    return probes.get(key);
  };
  const pnpmProbe=platform==='win32'?pnpmMetadata({env}):once('pnpm');
  const ffmpegRequired=Boolean(config.archive?.enabled);
  const writeRequested=config.worker.actions.some(action=>['write_file','develop'].includes(action));
  const [worker,analyzer,git,pnpm,ffmpeg,docker]=await Promise.all([
    once(config.worker.executable),
    config.analyzer.kind==='responses'?Promise.resolve({available:Boolean(env[config.analyzer.apiKeyEnv])}):once(config.analyzer.executable),
    once('git'),pnpmProbe,once(config.archive?.ffmpeg??'ffmpeg',['-version']),
    writeRequested?once(config.worker.verification?.executable??'docker'):Promise.resolve({available:false,reason:'not_required'})
  ]);
  const result={node:nodeVersion,nodeSupported:Number(nodeVersion.split('.')[0])>=24,taskOwner:config.owner.kind,
    discordCredentialPresent:Boolean(env[config.discord.botTokenEnv]),openaiCredentialPresent:Boolean(env[config.voice.apiKeyEnv]),
    analyzerAdapter:config.analyzer.kind,analyzerAvailable:analyzer.available,workerAvailable:worker.available,gitAvailable:git.available,
    voiceConfigured:Boolean(config.discord.voiceChannelId),privacyMode:config.voice.consentMode,voiceParticipantsConfigured:config.voice.participantIds.length,audioBudgetSeconds:config.voice.maxDailyAudioSeconds,
    browserConfigured:Boolean(config.browser.cdpUrl),localWriteWorkerSupported:platform==='linux',providerVerified:false,
    pnpm:{...pnpm,expected:expectedPnpm,supported:pnpm.available&&pnpm.version===expectedPnpm},
    ffmpeg:{available:ffmpeg.available,reason:ffmpeg.reason,required:ffmpegRequired},
    writeWorker:{requested:writeRequested,platformSupported:platform==='linux',dockerAvailable:docker.available,
      verificationConfigured:Boolean(config.worker.verification&&config.worker.verify.length)},
    toolReasons:{worker:worker.reason??null,analyzer:analyzer.reason??null,git:git.reason??null},nextSteps:[]};
  const add=(code,message)=>result.nextSteps.push({code,message});
  if(!result.nodeSupported)add('NODE_REQUIRED','Node.js 24以上を用意して、doctorを再実行してください。');
  if(!result.pnpm.supported)add('PNPM_REQUIRED',platform==='win32'&&!pnpm.available?`pnpmの版は未確認です。端末のpnpm --versionで${expectedPnpm}を確認してから、pnpm install --frozen-lockfile --ignore-scriptsを実行してください。`:`pnpm ${expectedPnpm}を用意し、pnpm install --frozen-lockfile --ignore-scriptsを実行してください。`);
  if(!result.gitAvailable)add('GIT_REQUIRED','Gitを用意し、CLIから実行できる状態にしてください。');
  if(!result.discordCredentialPresent)add('DISCORD_CREDENTIAL_REQUIRED','設定で指定した環境変数へDiscord Bot tokenを保存してください。tokenを診断結果へ貼り付ける必要はありません。');
  if(!result.workerAvailable)add('WORKER_REQUIRED','workerの実行ファイルを確認してください。Windowsでは.cmdではなくネイティブの実行ファイルを指定します。');
  if(!result.analyzerAvailable)add('ANALYZER_REQUIRED',config.analyzer.kind==='responses'?'解析用APIキーを、設定で指定した環境変数へ保存してください。':'analyzerの実行ファイルを確認してください。');
  if(result.voiceConfigured&&!result.openaiCredentialPresent)add('VOICE_CREDENTIAL_REQUIRED','音声用APIキーを、設定で指定した環境変数へ保存してください。');
  if(result.voiceConfigured&&result.audioBudgetSeconds===0)add('AUDIO_BUDGET_ZERO','音声を利用する場合は、許可する一日の秒数を設定してください。現在の上限は0秒です。');
  if(ffmpegRequired&&!ffmpeg.available)add('FFMPEG_REQUIRED','録音保存に使うffmpegを用意し、archive.ffmpegの実行ファイルを確認してください。');
  if(writeRequested&&!result.localWriteWorkerSupported)add('WRITE_WORKER_LINUX_REQUIRED','書込みworkerはLinuxで実行します。この端末では読取workerまたはCLIクライアントを利用してください。');
  if(writeRequested&&!result.writeWorker.verificationConfigured)add('WRITE_VERIFICATION_REQUIRED','書込みにはworker.verifyと、固定imageを使うworker.verificationの設定が必要です。');
  if(writeRequested&&result.localWriteWorkerSupported&&!docker.available)add('DOCKER_REQUIRED','Linuxの実行ホストにDockerと検証用の固定imageを用意してください。');
  return result;
}

export function formatDoctor(result) {
  const mark=value=>value?'確認済み':'要確認';
  const lines=['ことだま — 導入の確認（ローカル）',`Node.js: ${result.node} / ${mark(result.nodeSupported)}`,
    `pnpm: ${result.pnpm.version??'未確認'} / 必要な版 ${result.pnpm.expected} / ${mark(result.pnpm.supported)}`,
    `Git: ${mark(result.gitAvailable)}`,`worker: ${mark(result.workerAvailable)}`,`analyzer: ${mark(result.analyzerAvailable)}`,
    `ffmpeg: ${mark(result.ffmpeg.available)}${result.ffmpeg.required?'（録音保存に必要）':'（録音保存を使う場合）'}`,
    `書込みworkerの対応OS: ${result.localWriteWorkerSupported?'Linux / 対応':'Linuxで実行してください'}`];
  if(result.pnpm.source==='package_metadata')lines.push('Windowsのpnpmはパッケージ情報から確認します。CLIの実行はこの診断に含みません。');
  if(result.nextSteps.length)lines.push('','次の手順:',...result.nextSteps.map((step,index)=>`${index+1}. ${step.message}`));
  else lines.push('','道具のローカル確認が完了しました。');
  lines.push('','実Discord・providerの接続や動作は別に確認してください。');
  return lines.join('\n');
}
