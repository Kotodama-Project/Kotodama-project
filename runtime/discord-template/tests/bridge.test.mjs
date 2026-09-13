import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Store} from '../src/store.mjs';
import {exampleConfig} from '../src/config.mjs';
import {startBridge} from '../src/bridge.mjs';
import {parseLumaCsv,lumaSource} from '../src/integrations.mjs';
test('Luma HTTP import is private, idempotent and cannot authorize work',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-bridge-')),store=new Store(root),config=exampleConfig();const actor=config.discord.operators[0],other='100000000000000009';config.discord.operators.push(other);config.bridge={enabled:true,host:'127.0.0.1',port:0,actorId:actor,tokenEnv:'KOTODAMA_TEST_BRIDGE_TOKEN'};config.integrations.luma={eventRef:'event-fixture',eventUrl:'https://example.invalid/event'};process.env.KOTODAMA_TEST_BRIDGE_TOKEN='synthetic-bridge-credential-only';let calls=0;
  const server=await startBridge({config,store,pipeline:{ingest:async(source,flags)=>{assert.equal(flags.execute,false);assert.equal(flags.reply,false);calls++;return store.ingest(source);}}});
  t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));store.close();delete process.env.KOTODAMA_TEST_BRIDGE_TOKEN;assert(path.basename(root).startsWith('ktdm-bridge-'));await rm(root,{recursive:true,force:true});});const url='http://127.0.0.1:'+server.address().port+'/v1/luma/import';
  const body={eventRef:'event-fixture',csv:'Name,Email,Ticket ID\nSample,sample@example.invalid,t1\n',revision:1};const send=(payload,authorized=true)=>fetch(url,{method:'POST',headers:{'content-type':'application/json',...(authorized?{authorization:'Bearer '+process.env.KOTODAMA_TEST_BRIDGE_TOKEN}:{})},body:JSON.stringify(payload)});
  assert.equal((await send(body,false)).status,401);assert.equal((await send({...body,actorId:other})).status,400);assert.equal((await send({...body,eventRef:'wrong'})).status,400);
  const legacy=lumaSource(parseLumaCsv(body.csv,{eventRef:body.eventRef}),{guildId:config.discord.guildId,channelId:config.discord.resultChannelId,actorId:actor,readers:[actor,other],revision:1});store.ingest(legacy);assert.equal(store.sources(other).length,1);
  assert.equal((await send(body)).status,200);assert.equal((await (await send(body)).json()).state,'duplicate');assert.equal(calls,1);assert.equal(store.sources(actor).length,1);assert.equal(store.sources(actor)[0].revision,2);assert.equal(store.sources(other).length,0);
  config.bridge.enabled=false;assert.equal((await send(body)).status,400);
});
