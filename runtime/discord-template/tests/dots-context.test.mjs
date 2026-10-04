import test from 'node:test';
import assert from 'node:assert/strict';
import {benchmarkDotsContext} from '../tools/benchmark-dots-context.mjs';

test('long multilingual context crosses the real packaged MCP stdio and loopback boundary',async t=>{
  const report=await benchmarkDotsContext();assert.equal(report.status,'PASS');assert.equal(report.modelReasoningEvaluated,false);assert.equal(report.liveDotsAccepted,false);assert(report.metrics.sourceUtf16Units>500000);assert(report.metrics.selectedReadCalls>=12);t.diagnostic(JSON.stringify(report));
});
