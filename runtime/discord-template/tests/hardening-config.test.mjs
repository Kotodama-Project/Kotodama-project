import test from 'node:test';
import assert from 'node:assert/strict';
import {Config,exampleConfig} from '../src/config.mjs';
import {admissionDefaults} from '../src/analysis-admission.mjs';

test('CLI analysis installs finite defaults and keeps read-only worker defaults',()=>{const c=exampleConfig();assert.deepEqual(c.analyzer.admission,admissionDefaults);assert.deepEqual(c.worker.actions,['research','summarize']);assert.deepEqual(c.worker.verificationRuntimeRoots,[]);});
test('Responses analysis shares the same admission bounds',()=>{const c=exampleConfig();c.analyzer={kind:'responses'};assert.deepEqual(Config.parse(c).analyzer.admission,admissionDefaults);});
test('operators can lower quota to zero without enabling audio or writes',()=>{const c=exampleConfig();c.analyzer.admission.maxDailyCalls=0;const parsed=Config.parse(c);assert.equal(parsed.analyzer.admission.maxDailyCalls,0);assert.equal(parsed.voice.maxDailyAudioSeconds,0);assert.deepEqual(parsed.worker.actions,['research','summarize']);});
test('invalid or misspelled admission settings are refused',()=>{for(const value of [{concurrency:0},{maxPending:-1},{maxDailyCalls:1.2},{unlimited:true}]){const c=exampleConfig();c.analyzer.admission=value;assert.throws(()=>Config.parse(c));}});
