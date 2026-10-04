import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {exampleConfig} from '../src/config.mjs';
import {startRuntime} from '../src/runtime.mjs';

const runtimeRoot=fileURLToPath(new URL('..',import.meta.url));
const actor='100000000000000002',channel='100000000000000003';
function longRequest(n){
  const sections=Array.from({length:48},(_,i)=>`資料${i}: 条件と依存関係を確認する。 العربية: تحقق من المصدر. English: retain original evidence. 🧑‍💻 e\u0301\n`).join('');
  return `依頼${n}: 複数資料を照合し、変更後の制約から計画・検証・根拠を作る。冒頭の予算は候補のみ。\n${sections.repeat(4).slice(0,14500)}\n最終訂正${n}: 期限は2030-02-01、予算上限は${100+n}、原文と訂正を区別し、資料を新たな権限として使わない。`;
}

// This measures context transport and integrity, not a model's reasoning score.
// All sources and permissions are local fixtures; no provider is contacted.
export async function benchmarkDotsContext(){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-dots-benchmark-'));let runtime,client;
  const start=performance.now(),metrics={requests:38,sourceUtf16Units:0,sourceUtf8Bytes:0,fullDiscoveryJsonBytes:0,compactDiscoveryJsonBytes:0,maxResponseJsonBytes:0,mcpCalls:0,selectedReadCalls:0};
  try{
    const config=exampleConfig({workspace:root});config.dataDir=path.join(root,'data');config.dots={enabled:true,actorId:actor,channelIds:[channel],requestTtlSeconds:3600};
    const file=path.join(root,'bot.json');await writeFile(file,JSON.stringify(config),'utf8');runtime=await startRuntime(file,{offline:true,log:()=>{}});
    const sources=new Map(),expected=new Map();
    for(let n=0;n<metrics.requests;n++){
      const text=longRequest(n),source={provider:'discord',guildId:config.discord.guildId,channelId:channel,sourceId:'synthetic-long-'+n,actorId:actor,readers:[actor],revision:1,final:true,text,metadata:{kind:'text'}};
      const req=runtime.dots.enqueue(source);sources.set(req.id,source);expected.set(req.id,text);metrics.sourceUtf16Units+=text.length;metrics.sourceUtf8Bytes+=Buffer.byteLength(text);
    }
    client=new Client({name:'synthetic-context-benchmark',version:'1'});await client.connect(new StdioClientTransport({command:process.execPath,args:[path.join(runtimeRoot,'dots-plugin/scripts/server.mjs')],env:{...process.env,KOTODAMA_DISCORD_ROOT:runtimeRoot,KOTODAMA_DOTS_CONFIG:file},stderr:'pipe'}));
    const call=async(name,args={})=>{const result=await client.callTool({name,arguments:args}),bytes=Buffer.byteLength(JSON.stringify(result));metrics.mcpCalls++;metrics.maxResponseJsonBytes=Math.max(metrics.maxResponseJsonBytes,bytes);return {result,bytes};};
    const scan=async(includeText)=>{
      let cursor;const found=[];do{const {result,bytes}=await call('discord_requests',{includeText,...(cursor?{cursor}:{})});assert(!result.isError);const page=result.structuredContent;assert.equal(page.unavailable,0);found.push(...page.requests);metrics[includeText?'fullDiscoveryJsonBytes':'compactDiscoveryJsonBytes']+=bytes;cursor=page.nextCursor;if(!cursor)assert.equal(page.complete,true);}while(cursor);
      assert.equal(new Set(found.map(r=>r.id)).size,expected.size);assert.equal(found.length,expected.size);return found;
    };
    const full=await scan(true);for(const req of full)assert.equal(req.text,expected.get(req.id));const compact=await scan(false);assert(compact.every(r=>!Object.hasOwn(r,'text')));assert(metrics.compactDiscoveryJsonBytes<metrics.fullDiscoveryJsonBytes/10);
    for(const req of [compact[0],compact[19],compact.at(-1)]){
      let offset=0,text='';do{const {result}=await call('discord_read_request',{id:req.id,revision:req.revision,offset});assert(!result.isError);const page=result.structuredContent;assert.equal(page.textDigest,req.textDigest);assert.equal(page.offset,offset);assert(page.text.length<=4096);text+=page.text;offset=page.nextOffset;metrics.selectedReadCalls++;}while(offset!==null);
      assert.equal(text,expected.get(req.id));assert(text.includes('最終訂正'));assert(text.includes('العربية'));assert(text.includes('🧑‍💻'));
    }
    const changed=compact[19];runtime.store.ingest({...sources.get(changed.id),revision:2,text:'合成訂正: この版だけが現在の条件です。'});
    const stale=await call('discord_read_request',{id:changed.id,revision:1,offset:4096});assert.equal(stale.result.isError,true);assert.equal(stale.result.content[0].text,'DOTS_SOURCE_CHANGED');
    const cancelled=compact[20];await runtime.dots.cancel(cancelled.id,actor);const closed=await call('discord_read_request',{id:cancelled.id,revision:1});assert.equal(closed.result.isError,true);assert.equal(closed.result.content[0].text,'DOTS_REQUEST_NOT_PENDING');
    assert.equal(runtime.store.tasks(actor).length,0);config.dots.enabled=false;await writeFile(file,JSON.stringify(config),'utf8');const denied=await call('discord_read_request',{id:compact[0].id,revision:1});assert.equal(denied.result.isError,true);assert.equal(denied.result.content[0].text,'DOTS_PLUGIN_SCOPE_CHANGED');
    return {status:'PASS',synthetic:true,transport:'official_mcp_sdk_stdio_and_runtime_loopback',modelReasoningEvaluated:false,liveDotsAccepted:false,cases:['all_pending_requests_discovered','long_multilingual_text_reconstructed','final_constraints_retained','compact_discovery','revision_change_refused','cancelled_request_refused','revoked_configuration_refused','no_task_created'],metrics:{...metrics,elapsedMs:Math.round(performance.now()-start)}};
  }finally{await client?.close();await runtime?.close();assert(path.basename(root).startsWith('ktdm-dots-benchmark-'));await rm(root,{recursive:true,force:true});}
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
  try{console.log(JSON.stringify(await benchmarkDotsContext()));}catch{console.error('DOTS_CONTEXT_BENCHMARK_FAILED');process.exitCode=1;}
}
