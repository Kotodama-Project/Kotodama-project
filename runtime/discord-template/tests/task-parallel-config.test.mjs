import test from 'node:test';
import assert from 'node:assert/strict';
import {Config,exampleConfig} from '../src/config.mjs';
import {DEFAULT_TASK_LIMITS,isReadOnlyTask,taskLimits} from '../src/task-admission.mjs';

test('Task admission defaults to one worker and validates each independent limit',()=>{
  const config=exampleConfig();assert.deepEqual(config.worker.taskLimits,DEFAULT_TASK_LIMITS);
  for(const value of [{maxConcurrentReadOnly:5},{maxQueued:-1},{maxQueuedBytes:-1},{maxInputBytes:1023},{maxResultBytes:67108865},{maxConcurrentReadOnly:1.5}]){
    assert.throws(()=>Config.parse({...config,worker:{...config.worker,taskLimits:value}}));assert.throws(()=>taskLimits(value),/TASK_LIMIT_INVALID/);
  }
  assert.throws(()=>Config.parse({...config,worker:{...config.worker,taskLimits:{unknown:1}}}));
  assert.equal(Config.parse({...config,worker:{...config.worker,taskLimits:{maxConcurrentReadOnly:2,maxQueued:0,maxQueuedBytes:0}}}).worker.taskLimits.maxConcurrentReadOnly,2);
});

test('only the established basic read-only worker actions can overlap',()=>{
  assert(isReadOnlyTask({action:'research'}));assert(isReadOnlyTask({action:'summarize',requiredActions:['research','summarize']}));
  for(const action of ['develop','write_file','create_company_pack','swarm_research','future_action'])assert(!isReadOnlyTask({action}));
  assert(!isReadOnlyTask({action:'research',requiredActions:['develop']}));
});
