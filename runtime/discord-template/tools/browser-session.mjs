#!/usr/bin/env node
import {spawn} from 'node:child_process';
import {parseArgs} from 'node:util';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {atomicJson,check,uid} from '../src/common.mjs';

const {values:o}=parseArgs({options:{browser:{type:'string'},profile:{type:'string',default:'.kotodama/setup-browser'},url:{type:'string',default:'https://discord.com/developers/applications'},headless:{type:'boolean',default:false}}});
check(o.browser,'BROWSER_EXECUTABLE_REQUIRED');const url=new URL(o.url);check(url.protocol==='https:'||(url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)),'BROWSER_URL_REFUSED');
const profile=path.resolve(o.profile),stateFile=path.join(profile,'kotodama-owner.json');await mkdir(profile,{recursive:true,mode:0o700});
let old;try{old=JSON.parse(await readFile(stateFile,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
if(old?.state==='running'){let alive=true;try{process.kill(old.browserPid,0);}catch(e){alive=e.code!=='ESRCH';}check(!alive,'BROWSER_PROFILE_ALREADY_OWNED');}
const ownerId=uid('browser');const args=[`--user-data-dir=${profile}`,'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--no-first-run','--no-default-browser-check'];if(o.headless)args.push('--headless=new');args.push(o.url);
const child=spawn(o.browser,args,{stdio:'ignore',windowsHide:o.headless});let ended=false;child.once('exit',()=>{ended=true;});
await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});
let port;const deadline=Date.now()+15000;
while(Date.now()<deadline&&!ended){try{const raw=await readFile(path.join(profile,'DevToolsActivePort'),'utf8');const candidate=Number(raw.split('\n')[0]);if(Number.isInteger(candidate)&&candidate>0){const response=await fetch(`http://127.0.0.1:${candidate}/json/version`,{signal:AbortSignal.timeout(500)});if(response.ok){port=candidate;break;}}}catch{}await new Promise(r=>setTimeout(r,100));}
check(port,'BROWSER_CDP_NOT_READY');const state={ownerId,managerPid:process.pid,browserPid:child.pid,startedAt:new Date().toISOString(),cdpUrl:`http://127.0.0.1:${port}`,state:'running',profile};await atomicJson(stateFile,state);
console.log(JSON.stringify({state:'browser_ready',cdpUrl:state.cdpUrl,stateFile,humanAction:'必要な場合は、この専用ブラウザでログイン・本人確認を行ってください。'}));
child.once('exit',async()=>{await atomicJson(stateFile,{...state,state:'closed',closedAt:new Date().toISOString()});process.exit(0);});
