import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createAnalysisAuthorizer} from '../src/analysis-policy.mjs';
import {exampleConfig} from '../src/config.mjs';
import {Store} from '../src/store.mjs';
import {Pipeline} from '../src/pipeline.mjs';
const participant='100000000000000009';
const config=exampleConfig();
const source={provider:'discord',guildId:config.discord.guildId,channelId:config.discord.textChannelIds[0],sourceId:'voice-fixture',key:'voice-fixture',actorId:participant,revision:1,final:true,text:'synthetic voice',readers:[participant],metadata:{kind:'voice'}};

test('voice analysis permission does not require or create execution operator membership',async()=>{
  let allowed=true;const authorize=createAnalysisAuthorizer({config,readConfig:async()=>config,owner:{kind:'local'},voice:()=>({allowed:actor=>allowed&&actor===participant})});
  await authorize(source,participant);assert(!config.discord.operators.includes(participant));
  allowed=false;await assert.rejects(authorize(source,participant),{code:'GRANT_REVOKED'});
});
test('voice processing consent never bypasses source ACL or current guild binding',async()=>{
  const authorize=createAnalysisAuthorizer({config,readConfig:async()=>config,owner:{kind:'local'},voice:()=>({allowed:()=>true})});
  for(const changed of [{readers:[]},{withdrawn:true},{guildId:'100000000000000008'}])await assert.rejects(authorize({...source,...changed},participant),{code:'SOURCE_ACCESS_DENIED'});
});
test('analysis rechecks actual Discord channel access and remote source revision',async()=>{
  let canRead=true,revision=1,reads=0;const remoteConfig={...config,owner:{kind:'remote'}};
  const authorize=createAnalysisAuthorizer({config:remoteConfig,readConfig:async()=>remoteConfig,voice:()=>({allowed:()=>true}),discord:()=>({client:{channels:{fetch:async()=>{reads++;return {};}}},canRead:async()=>canRead}),owner:{kind:'remote',source:async()=>({revision})}});
  await authorize(source,participant);assert.equal(reads,1);canRead=false;await assert.rejects(authorize(source,participant),{code:'SOURCE_ACCESS_DENIED'});canRead=true;revision=2;await assert.rejects(authorize(source,participant),{code:'REMOTE_SOURCE_CHANGED'});
});
test('a consenting non-operator can contribute intent but cannot start a Task',async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'ktdm-analysis-reader-')),store=new Store(dir),cfg=exampleConfig({workspace:dir});let calls=0;
  const authorizeAnalysis=createAnalysisAuthorizer({config:cfg,readConfig:async()=>cfg,owner:store,voice:()=>({allowed:actor=>actor===participant})});
  const p=new Pipeline({store,config:cfg,authorizeAnalysis,analyzer:{analyze:async()=>{calls++;return {summary:'fixture',intents:[{kind:'request',title:'fixture',request:'fixture',action:'research',acceptance:[],explicit:true,complete:true}],replyRequested:false,reply:''};}}});
  t.after(async()=>{await p.close();store.close();await rm(dir,{recursive:true,force:true});});
  await p.ingest(source,{execute:true});assert.equal(calls,1);assert.equal(store.listIntents(participant).length,1);assert.equal(store.tasks(participant).length,0);
});
