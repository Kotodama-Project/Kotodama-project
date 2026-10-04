import test from 'node:test';
import assert from 'node:assert/strict';
import {LocalAsr,pcm24MonoWav} from '../src/local-asr.mjs';
import {Config} from '../src/config.mjs';

test('local ASR sends a bounded WAV utterance and returns only the final Japanese text',async()=>{
  let request;const asr=new LocalAsr({url:'http://127.0.0.1:9000/v1/audio/transcriptions',model:'tiny',apiKey:'synthetic',fetcher:async(url,options)=>{request={url,options};return new Response(JSON.stringify({text:'  ことだま、状態を教えて  '}),{status:200,headers:{'content-type':'application/json'}});}});
  const text=await asr.transcribe(Buffer.alloc(4800));assert.equal(text,'ことだま、状態を教えて');assert.equal(String(request.url),'http://127.0.0.1:9000/v1/audio/transcriptions');assert.equal(request.options.headers.authorization,'Bearer synthetic');
  const file=request.options.body.get('file'),wav=Buffer.from(await file.arrayBuffer());assert.equal(wav.toString('ascii',0,4),'RIFF');assert.equal(wav.toString('ascii',8,12),'WAVE');assert.equal(wav.readUInt32LE(24),24000);assert.equal(wav.length,4844);
});

test('local ASR rejects oversized audio and never exposes provider failure bodies',async()=>{
  const asr=new LocalAsr({url:'https://asr.example.test/v1/audio/transcriptions',model:'tiny',maxUtteranceSeconds:3,fetcher:async()=>new Response('private diagnostic',{status:500})});
  await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_FAILED',message:'LOCAL_ASR_FAILED'});await assert.rejects(asr.transcribe(Buffer.alloc(3*48000+2)),{code:'LOCAL_ASR_AUDIO_INVALID'});assert.throws(()=>pcm24MonoWav(Buffer.alloc(3)),{code:'LOCAL_ASR_AUDIO_INVALID'});
});
test('local ASR bounds a chunked response before parsing it',async()=>{const asr=new LocalAsr({url:'https://asr.example.test/v1/audio/transcriptions',model:'tiny',fetcher:async()=>new Response(new ReadableStream({start(controller){controller.enqueue(new Uint8Array(70000));controller.close();}}),{status:200})});await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_RESULT_LIMIT'});});

test('the Kotodama ASR protocol preserves its audio field and joins verified segment text',async()=>{let form;const asr=new LocalAsr({url:'http://127.0.0.1:8000/transcribe',protocol:'kotodama',model:'tiny',initialPrompt:'ことだま',hotwords:'ことだま',fetcher:async(_url,options)=>{form=options.body;return new Response(JSON.stringify({segments:[{text:'ことだま、'},{text:'状態を教えて'}]}),{status:200});}});assert.equal(await asr.transcribe(Buffer.alloc(4800)),'ことだま、状態を教えて');assert(form.get('audio'));assert.equal(form.get('file'),null);assert.equal(form.get('initial_prompt'),'ことだま');assert.equal(form.get('hotwords'),'ことだま');});

test('local transcript mode requires an explicit local ASR endpoint',()=>{
  const base={version:1,installation:'fixture',discord:{guildId:'100000000000000001',textChannelIds:['100000000000000003'],resultChannelId:'100000000000000003',operators:['100000000000000002']},voice:{transcriptSource:'local'},worker:{executable:'codex',workspace:'.'}};
  assert.throws(()=>Config.parse(base),/LOCAL_ASR_CONFIG_REQUIRED/);base.voice.localAsr={url:'http://127.0.0.1:9000/v1/audio/transcriptions',model:'tiny'};assert.equal(Config.parse(base).voice.localAsr.language,'ja');
});

test('local ASR deadline covers a stalled response body and cancels its stream',async()=>{
  let cancelled=false;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',timeoutSeconds:0.03,fetcher:async()=>new Response(new ReadableStream({cancel(){cancelled=true;}}))});
  await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_TIMEOUT',message:'LOCAL_ASR_TIMEOUT'});assert.equal(cancelled,true);
});

test('local ASR bounds connection wait and cancels a response returned after timeout',async()=>{
  let resolveFetch,signal,cancelled=false;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',timeoutSeconds:0.03,fetcher:(_url,options)=>{signal=options.signal;return new Promise(resolve=>{resolveFetch=resolve;});}});
  await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_TIMEOUT'});assert.equal(signal.aborted,true);
  resolveFetch(new Response(new ReadableStream({cancel(){cancelled=true;}})));await new Promise(resolve=>setImmediate(resolve));assert.equal(cancelled,true);
});

test('local ASR explicit cancellation returns a classified refusal',async()=>{
  const controller=new AbortController();let cancelled=false;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',fetcher:async()=>new Response(new ReadableStream({cancel(){cancelled=true;}}))});
  const work=asr.transcribe(Buffer.alloc(4800),{signal:controller.signal});await new Promise(resolve=>setImmediate(resolve));controller.abort();
  await assert.rejects(work,{code:'LOCAL_ASR_CANCELLED'});assert.equal(cancelled,true);
});

for(const status of [200,500])test(`local ASR cancels unread refused response bodies (${status})`,async()=>{
  let cancelled=false;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',fetcher:async()=>new Response(new ReadableStream({cancel(){cancelled=true;}}),{status,headers:{'content-length':'70000'}})});
  await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:status===200?'LOCAL_ASR_RESULT_LIMIT':'LOCAL_ASR_FAILED'});assert.equal(cancelled,true);
});

test('ignored transport cancellation retains finite ASR admission until actual completion',async()=>{
  const pending=[];let calls=0;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',timeoutSeconds:0.02,fetcher:()=>{calls++;return new Promise(resolve=>pending.push(resolve));}});
  for(let i=0;i<2;i++)await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_TIMEOUT'});
  for(let i=0;i<5;i++)await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_BUSY'});
  assert.equal(calls,2);assert.equal(asr.pendingRequests.size,2);
  for(const resolve of pending)resolve(new Response('{"text":"late"}'));await new Promise(resolve=>setImmediate(resolve));assert.equal(asr.pendingRequests.size,0);
  asr.fetcher=async()=>new Response('{"text":"resumed"}');assert.equal(await asr.transcribe(Buffer.alloc(4800)),'resumed');
});

test('ignored response reader cancellation also keeps the ASR admission slot',async()=>{
  const reads=[];let calls=0;
  const asr=new LocalAsr({url:'http://127.0.0.1:9000/transcribe',model:'fixture',timeoutSeconds:0.02,fetcher:async()=>{calls++;return {ok:true,headers:new Headers(),body:{getReader:()=>({read:()=>new Promise(resolve=>reads.push(resolve)),cancel:async()=>{},releaseLock(){}})}};}});
  for(let i=0;i<2;i++)await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_TIMEOUT'});
  await assert.rejects(asr.transcribe(Buffer.alloc(4800)),{code:'LOCAL_ASR_BUSY'});assert.equal(calls,2);
  for(const resolve of reads)resolve({done:true});await new Promise(resolve=>setImmediate(resolve));assert.equal(asr.pendingRequests.size,0);
});
