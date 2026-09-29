import test from 'node:test';
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtemp,writeFile,rm,stat} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {exampleConfig} from '../src/config.mjs';
import {diagnose,formatDoctor,probeTool,windowsPnpm,PROBE_TIMEOUT_MS,PROBE_MAX_BYTES} from '../src/doctor.mjs';

const exec=promisify(execFile);
const bin=fileURLToPath(new URL('../bin/kotodama.mjs',import.meta.url));

test('doctor reports installation prerequisites and next steps without creating runtime state',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-doctor-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  const config=exampleConfig({workspace:root});
  config.dataDir='state';config.worker.executable=process.execPath;config.analyzer.executable=process.execPath;
  const filename=path.join(root,'config.json');await writeFile(filename,JSON.stringify(config),'utf8');
  const {stdout}=await exec(process.execPath,[bin,'doctor','--config',filename,'--json'],{timeout:15000});
  const report=JSON.parse(stdout);
  assert.equal(report.pnpm.expected,'11.19.0');
  assert.equal(typeof report.ffmpeg.available,'boolean');
  assert.equal(report.localWriteWorkerSupported,process.platform==='linux');
  assert(Array.isArray(report.nextSteps));
  assert.equal(report.providerVerified,false);
  await assert.rejects(stat(path.join(root,'state')),{code:'ENOENT'});
});

const availableProbe=async (executable,args)=>({available:true,reason:null,version:executable==='pnpm'||args?.at(-1)==='pnpm --version'?'11.19.0':null});

for(const platform of ['linux','darwin','win32'])test(`doctor only supports write workers on Linux: ${platform}`,async()=>{
  const config=exampleConfig();config.worker.actions=['develop'];
  const result=await diagnose(config,{platform,env:{},probe:availableProbe});
  assert.equal(result.localWriteWorkerSupported,platform==='linux');
  assert.equal(result.writeWorker.platformSupported,platform==='linux');
  assert.equal(result.nextSteps.some(step=>step.code==='WRITE_WORKER_LINUX_REQUIRED'),platform!=='linux');
  assert(result.nextSteps.some(step=>step.code==='WRITE_VERIFICATION_REQUIRED'));
});

test('doctor checks the pinned package-manager version and returns concrete next steps',async()=>{
  const config=exampleConfig();
  const result=await diagnose(config,{platform:'linux',env:{},probe:async executable=>({available:executable==='pnpm',reason:'unavailable',version:executable==='pnpm'?'10.0.0':null})});
  assert.equal(result.pnpm.supported,false);assert.equal(result.pnpm.expected,'11.19.0');
  assert(result.nextSteps.some(step=>step.code==='PNPM_REQUIRED'&&step.message.includes('11.19.0')));
  assert(result.nextSteps.some(step=>step.code==='DISCORD_CREDENTIAL_REQUIRED'));
  assert(result.nextSteps.some(step=>step.code==='GIT_REQUIRED'));
  assert(result.nextSteps.some(step=>step.code==='WORKER_REQUIRED'));
  assert(!result.nextSteps.some(step=>step.code==='FFMPEG_REQUIRED'),'optional recording tools do not block text-only installation');
});

test('doctor checks a shared worker/analyzer executable only once',async()=>{
  const config=exampleConfig();const calls=[];
  await diagnose(config,{platform:'linux',env:{},probe:async (executable,args)=>{calls.push([executable,args]);return availableProbe(executable,args);}});
  assert.equal(calls.filter(([executable])=>executable===config.worker.executable).length,1);
});

test('doctor checks configured archive ffmpeg without connecting to configured services',async()=>{
  const config=exampleConfig();config.archive={enabled:true,ffmpeg:'fixture-ffmpeg',whisperEndpoint:'https://fixture.invalid'};
  const calls=[];
  const result=await diagnose(config,{platform:'linux',env:{},probe:async (executable,args)=>{calls.push([executable,args]);return {available:false,reason:'unavailable',version:null};}});
  assert.equal(result.ffmpeg.required,true);assert(result.nextSteps.some(step=>step.code==='FFMPEG_REQUIRED'));
  assert(calls.some(([executable,args])=>executable==='fixture-ffmpeg'&&args[0]==='-version'));
  assert(!JSON.stringify(calls).includes('fixture.invalid'));
});

test('doctor never starts a Windows shell to inspect pnpm',async()=>{
  const config=exampleConfig();config.worker.executable='fixture-native-model.exe';config.analyzer.executable='fixture-analyzer.exe';
  const calls=[];
  const result=await diagnose(config,{platform:'win32',env:{},pnpmMetadata:async()=>({available:true,reason:null,version:'11.19.0',source:'package_metadata',cliVerified:false}),probe:async (executable,args)=>{calls.push([executable,args]);return availableProbe(executable,args);}});
  assert(!calls.some(([executable])=>['cmd.exe','pnpm','pnpm.cmd'].includes(executable)));
  assert.equal(result.pnpm.supported,true);assert.equal(result.pnpm.cliVerified,false);
  assert(calls.some(([executable])=>executable==='fixture-native-model.exe'));
  assert(calls.some(([executable])=>executable==='fixture-analyzer.exe'));
});

test('Windows pnpm metadata supports known npm shims without executing their contents',async t=>{
  const {mkdir}=await import('node:fs/promises');
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-pnpm-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const binDir=path.join(root,'node_modules/pnpm/bin');await mkdir(binDir,{recursive:true});
  await writeFile(path.join(root,'node_modules/pnpm/package.json'),JSON.stringify({name:'pnpm',version:'11.19.0'}),'utf8');
  await writeFile(path.join(binDir,'pnpm.cjs'),'fixture entrypoint; not executed','utf8');
  const shim=path.join(root,'pnpm.cmd');
  for(const prefix of ['%~dp0','%dp0%']){
    await writeFile(shim,`@echo off\n"node.exe" "${prefix}\\node_modules\\pnpm\\bin\\pnpm.cjs" %*\n`,'utf8');
    const result=await windowsPnpm({env:{PATH:root}});
    assert.equal(result.version,'11.19.0');assert.equal(result.source,'package_metadata');assert.equal(result.cliVerified,false);
    assert(!JSON.stringify(result).includes(root));
  }
  await writeFile(shim,'unsupported command; must not be executed','utf8');
  assert.equal((await windowsPnpm({env:{PATH:root}})).available,false);
  await writeFile(shim,'x'.repeat(70000),'utf8');
  assert.equal((await windowsPnpm({env:{PATH:root}})).available,false);
  await writeFile(shim,'"node.exe" "%~dp0\\missing\\node_modules\\pnpm\\bin\\pnpm.cjs"\n"node.exe" "%~dp0\\node_modules\\pnpm\\bin\\pnpm.cjs"\n','utf8');
  assert.equal((await windowsPnpm({env:{PATH:root}})).available,false,'only the first recognized reference is inspected');
});

test('doctor output does not expose configured values or credential contents',async()=>{
  const config=exampleConfig();const secret='fixture-diagnostic-private-value';
  config.worker.executable=secret;config.browser.cdpUrl='http://127.0.0.1:9222/'+secret;
  config.discord.voiceChannelId='100000000000000004';
  config.discord.botTokenEnv='FIXTURE_DOCTOR_BOT';config.voice.apiKeyEnv='FIXTURE_DOCTOR_AUDIO';
  const env={FIXTURE_DOCTOR_BOT:secret,FIXTURE_DOCTOR_AUDIO:secret};
  const result=await diagnose(config,{platform:'linux',env,probe:availableProbe});
  assert(result.discordCredentialPresent&&result.openaiCredentialPresent);
  for(const output of [JSON.stringify(result),formatDoctor(result)])assert(!output.includes(secret));
  assert(result.nextSteps.some(step=>step.code==='AUDIO_BUDGET_ZERO'));
  assert.equal(result.providerVerified,false);
});

test('doctor text output presents Japanese checks and next actions',async()=>{
  const result=await diagnose(exampleConfig(),{platform:'darwin',nodeVersion:'22.0.0',env:{},probe:availableProbe});
  const text=formatDoctor(result);
  assert.match(text,/導入の確認/);assert.match(text,/次の手順/);assert.match(text,/Node.js 24以上/);
  assert.match(text,/書込みworkerの対応OS: Linuxで実行してください/);
});

test('version probe classifies missing commands and suppresses all unrecognized output',async()=>{
  assert.deepEqual(await probeTool('fixture-doctor-command-does-not-exist'),{available:false,reason:'unavailable',version:null});
  const secret='fixture-diagnostic-output-hidden';
  const result=await probeTool(process.execPath,['-e',`process.stdout.write(${JSON.stringify(secret)})`]);
  assert.equal(result.available,true);assert.equal(result.version,null);assert(!JSON.stringify(result).includes(secret));
  assert(PROBE_TIMEOUT_MS>0&&PROBE_TIMEOUT_MS<=5000);assert(PROBE_MAX_BYTES<=16384);
});

test('version probes stop a stalled child and bound excessive output',async()=>{
  const stalled=await probeTool(process.execPath,['-e','setInterval(()=>{},1000)'],{timeoutMs:100,maxBytes:1024});
  assert.equal(stalled.available,false);assert(['timeout','stop_unconfirmed'].includes(stalled.reason));
  const oversized=await probeTool(process.execPath,['-e',"process.stdout.write('x'.repeat(50000));setInterval(()=>{},1000)"],{timeoutMs:5000,maxBytes:1024});
  assert.equal(oversized.available,false);assert(['output_limit','stop_unconfirmed'].includes(oversized.reason));
});
