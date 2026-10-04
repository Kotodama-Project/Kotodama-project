import test from 'node:test';
import assert from 'node:assert/strict';
import {parseLumaCsv} from '../src/integrations.mjs';

test('Luma accepts 10,000 data rows without counting the header or empty lines',()=>{
  const data=parseLumaCsv('\uFEFFName,Ticket ID\n\n'+'Sample,t1\n'.repeat(10000),{eventRef:'event-fixture'});
  assert.equal(data.rows,10000);assert.equal(data.records.length,10000);assert.equal(data.identifiedTickets,1);assert.equal(data.rowsWithoutPersonIdentity,10000);
});

test('dense Luma CSV stops at the row limit before parsing a later malformed tail',()=>{
  const csv='Name\n'+'Sample\n'.repeat(10001)+'"unterminated';
  assert.throws(()=>parseLumaCsv(csv,{eventRef:'event-fixture'}),{code:'CSV_ROW_LIMIT'});
});
