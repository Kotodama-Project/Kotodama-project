import test from 'node:test';
import assert from 'node:assert/strict';
import {ACTION_LANES,WORKER_ACTIONS,DEFAULT_WORKER_ACTIONS,INTENT_ACTIONS} from '../src/capability-lanes.mjs';
import {Config,exampleConfig} from '../src/config.mjs';
import {Analysis,analysisSchema} from '../src/llm.mjs';
import {commandDefinition} from '../src/discord.mjs';

const sorted=value=>[...value].sort();
const analysis=action=>({summary:'fixture',intents:[{kind:'request',title:'fixture',request:'fixture',action,explicit:true,complete:true,acceptance:[]}],replyRequested:false,reply:'',voiceAction:'none'});

test('existing actions have a fixed immutable risk mapping and unchanged default grants',()=>{
  assert.deepEqual(WORKER_ACTIONS,['research','summarize','write_file','develop','create_company_pack','swarm_research']);
  assert.deepEqual(DEFAULT_WORKER_ACTIONS,['research','summarize']);
  assert.deepEqual(Config.parse(exampleConfig()).worker.actions,['research','summarize']);
  for(const action of WORKER_ACTIONS){const write=['write_file','develop','create_company_pack'].includes(action);assert.equal(ACTION_LANES[action].lane,write?'edit':'inspect');assert.equal(ACTION_LANES[action].riskClass,write?'reversible_change':'inspect');assert.equal(ACTION_LANES[action].defaultGranted,!write&&action!=='swarm_research');assert(Object.isFrozen(ACTION_LANES[action]));}
  assert.throws(()=>{ACTION_LANES.research.defaultGranted=false;},TypeError);
});
test('manual actions are configurable slash choices but stay outside analyzer vocabulary',()=>{
  const choices=commandDefinition.options.find(o=>o.name==='do').options.find(o=>o.name==='action').choices;
  assert.deepEqual(sorted(choices.map(c=>c.value)),sorted(WORKER_ACTIONS));
  assert.deepEqual(sorted(analysisSchema.properties.intents.items.properties.action.enum),sorted(INTENT_ACTIONS));
  for(const action of WORKER_ACTIONS){const config=exampleConfig();config.worker.actions=[action];assert.equal(Config.safeParse(config).success,true);assert.equal(Analysis.safeParse(analysis(action)).success,!ACTION_LANES[action].manualOnly);}
  assert.equal(Analysis.safeParse(analysis('none')).success,true);assert.equal(Object.hasOwn(ACTION_LANES,'none'),false);
});
test('privileged and unknown operations cannot be granted or emitted as runnable actions',()=>{
  for(const action of ['deploy','merge','push','publish','external_send','credential_change','delete','code.test','unknown']){
    const config=exampleConfig();config.worker.actions=[action];assert.equal(Config.safeParse(config).success,false,action);assert.equal(Analysis.safeParse(analysis(action)).success,false,action);assert.equal(Object.hasOwn(ACTION_LANES,action),false);
  }
});
test('lane metadata does not add a second grant setting',()=>{
  const config=exampleConfig();config.worker.lanes=['edit'];assert.equal(Config.safeParse(config).success,false);
  config.worker.actions=['write_file'];delete config.worker.lanes;assert.equal(Config.safeParse(config).success,true);
  assert.deepEqual(DEFAULT_WORKER_ACTIONS,['research','summarize']);
});
