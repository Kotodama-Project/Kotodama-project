import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile,stat,symlink,readdir} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import os from 'node:os';
import {errorCode,Refused} from '../src/common.mjs';
import {debugRequested,describeError,enableDebugLog,disableDebugLog} from '../src/debug-log.mjs';
import {exampleConfig,loadConfig} from '../src/config.mjs';

const exec=promisify(execFile);
const fakeKey='sk-'+'fixtureonlynotreal1234567890';
const fakeDiscordToken=['A'.repeat(24),'B'.repeat(6),'C'.repeat(27)].join('.');
async function tempDir(t){const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-debug-'));t.after(async()=>{disableDebugLog();await rm(dir,{recursive:true,force:true});});return dir;}
const lines=async file=>(await readFile(file,'utf8')).trim().split('\n').map(line=>JSON.parse(line));

test('debug logging is opt-in through --verbose or KOTODAMA_DEBUG',()=>{
  assert.equal(debugRequested({env:{}}),false);assert.equal(debugRequested({env:{KOTODAMA_DEBUG:'0'}}),false);
  for(const value of ['1','true','YES','on'])assert.equal(debugRequested({env:{KOTODAMA_DEBUG:value}}),true);
  assert.equal(debugRequested({verbose:true,env:{}}),true);
});

test('by default an unexpected error is still only OPERATION_FAILED and nothing is written',async t=>{
  const dir=await tempDir(t);disableDebugLog();
  assert.equal(errorCode(new TypeError('fixture failure')),'OPERATION_FAILED');assert.equal(errorCode(new Refused('SOURCE_ACCESS_DENIED')),'SOURCE_ACCESS_DENIED');
  assert.deepEqual(await readdir(dir),[]);
});

test('opt-in debug log keeps the redacted stack and classification site with private permissions',async t=>{
  const dir=await tempDir(t),file=path.join(dir,'debug.log');enableDebugLog(dir);
  const failure=new TypeError(`fixture failure with ${fakeKey} and Bearer ${fakeDiscordToken}`);
  assert.equal(errorCode(failure),'OPERATION_FAILED');assert.equal(errorCode(failure),'OPERATION_FAILED','the same error is recorded once');
  assert.equal(errorCode(new Refused('GRANT_REVOKED')),'GRANT_REVOKED');
  const text=await readFile(file,'utf8'),[entry]=await lines(file);
  assert.equal((await lines(file)).length,1);assert.equal(entry.name,'TypeError');assert.match(entry.stack,/debug-log\.test\.mjs/);assert.match(entry.where,/debug-log\.test\.mjs/);
  assert(!text.includes(fakeKey)&&!text.includes(fakeDiscordToken),'credentials are redacted');assert.match(entry.message,/\[REDACTED\]/);
  if(process.platform!=='win32')assert.equal((await stat(file)).mode&0o777,0o600);
  disableDebugLog();errorCode(new Error('after disable'));assert.equal((await lines(file)).length,1);
});

test('configuration errors list setting paths without the configured values',async t=>{
  const dir=await tempDir(t),config=exampleConfig(),secretLike='fixture-'+'value-must-not-appear';
  config.discord.guildId=secretLike;config.voice.maxDailyAudioSeconds='sixty';const filename=path.join(dir,'config.json');await writeFile(filename,JSON.stringify(config));
  const error=await loadConfig(filename).then(()=>null,e=>e);assert(error);const entry=describeError(error);
  assert(entry.issues.some(i=>i.path==='discord.guildId'));assert(entry.issues.some(i=>i.path==='voice.maxDailyAudioSeconds'&&i.code==='invalid_type'));
  assert(!JSON.stringify(entry).includes(secretLike)&&!JSON.stringify(entry).includes('sixty'));assert.equal(entry.message,undefined);
});

test('the debug log rotates at its size limit and refuses a linked file',async t=>{
  const dir=await tempDir(t),file=path.join(dir,'debug.log');const log=enableDebugLog(dir,{maxBytes:1500});
  for(let i=0;i<20;i++){const e=new Error('rotation fixture '+i);e.stack='Error: rotation fixture '+i;errorCode(e);}
  assert((await stat(file)).size<=1500);assert((await stat(file+'.1')).size<=1500);
  if(process.platform==='win32')return;
  await rm(file);await rm(file+'.1');const target=path.join(dir,'elsewhere.txt');await writeFile(target,'unchanged');await symlink(target,file);
  assert.equal(log.record(new Error('link fixture')),false);assert.equal(await readFile(target,'utf8'),'unchanged');
});

test('the CLI prints setting paths only with --verbose and never the values',async t=>{
  const dir=await tempDir(t),config=exampleConfig(),secretLike='fixture-'+'cli-value-hidden';config.discord.guildId=secretLike;
  const filename=path.join(dir,'config.json');await writeFile(filename,JSON.stringify(config));
  const bin=fileURLToPath(new URL('../bin/kotodama.mjs',import.meta.url));
  const run=async(...extra)=>{try{await exec(process.execPath,[bin,'doctor','--json','--config',filename,...extra],{env:{...process.env,KOTODAMA_DEBUG:''}});assert.fail('invalid config must fail');}catch(e){if(!e.stdout)throw e;return JSON.parse(e.stdout.trim());}};
  const plain=await run();assert.equal(plain.error,'OPERATION_FAILED');assert.equal(plain.debug,undefined);
  const verbose=await run('--verbose');assert.equal(verbose.error,'OPERATION_FAILED');assert(verbose.debug.issues.some(i=>i.path==='discord.guildId'));
  assert(!JSON.stringify(verbose).includes(secretLike));
});
