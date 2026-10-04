import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {Refused} from '../src/common.mjs';
import {registerShutdownSignals} from '../src/shutdown.mjs';

test('uncertain drains preserve the process and allow a later shutdown signal',async t=>{
  const target=new EventEmitter(),exits=[],errors=[];let calls=0,release;
  const gate=new Promise(resolve=>{release=resolve;});
  const dispose=registerShutdownSignals({close:async()=>{calls++;if(calls===1){await gate;throw new Refused('NOTIFICATION_DRAIN_UNCERTAIN');}}},{target,exit:code=>exits.push(code),report:code=>errors.push(code)});t.after(dispose);
  target.emit('SIGINT');await new Promise(resolve=>setImmediate(resolve));target.emit('SIGTERM');assert.equal(calls,1);
  release();await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(exits,[]);assert.deepEqual(errors,['NOTIFICATION_DRAIN_UNCERTAIN']);
  target.emit('SIGTERM');await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,2);assert.deepEqual(exits,[0]);assert.equal(target.listenerCount('SIGINT'),0);assert.equal(target.listenerCount('SIGTERM'),0);
});

test('a definitive shutdown failure reports its code and exits unsuccessfully',async()=>{
  const target=new EventEmitter(),exits=[],errors=[];
  registerShutdownSignals({close:async()=>{throw new Refused('RUNTIME_LOCK_CHANGED');}},{target,exit:code=>exits.push(code),report:code=>errors.push(code)});
  target.emit('SIGINT');await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(exits,[1]);assert.deepEqual(errors,['RUNTIME_LOCK_CHANGED']);assert.equal(target.listenerCount('SIGTERM'),0);
});
