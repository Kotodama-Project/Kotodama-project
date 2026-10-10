import test from 'node:test';
import assert from 'node:assert/strict';
import {evaluateSkillWorkflows,WORKFLOW_CASES,workflowSnapshot} from '../tools/evaluate-skill-workflows.mjs';
import {Refused} from '../src/common.mjs';
import {mkdtemp,mkdir,rm,symlink,writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const snapshot=async()=>({sha256:'fixture-sha',fileCount:1,totalBytes:1});
const tap=(extra={})=>({code:0,stdout:'# tests 1\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n',stderr:'',...extra});

test('fixed bounded subprocess contract and content-free evidence do not imply model acceptance',async()=>{
  const calls=[];
  const result=await evaluateSkillWorkflows({snapshot,run:async(executable,args,options)=>{calls.push({executable,args,options});return tap({stderr:'SYNTHETIC_PRIVATE_OUTPUT'});}});
  assert.equal(calls.length,5);assert.equal(result.status,'PASS');assert.equal(result.modelReasoningEvaluated,false);assert.equal(result.liveProviderAccepted,false);
  assert.equal(result.unexecuted.length,4);assert(!JSON.stringify(result).includes('SYNTHETIC_PRIVATE_OUTPUT'));
  for(let i=0;i<calls.length;i++){
    assert.equal(calls[i].executable,process.execPath);assert.equal(calls[i].options.timeoutMs,90000);assert.equal(calls[i].options.maxBytes,2000000);
    assert.deepEqual(calls[i].args.slice(4),WORKFLOW_CASES[i].tests.map(name=>'tests/'+name));
    assert.match(result.cases[i].outputSha256,/^[a-f0-9]{64}$/);
  }
});

test('one failed group cannot be hidden by four passing groups',async()=>{
  let index=0;
  const result=await evaluateSkillWorkflows({snapshot,run:async()=>tap({code:index++===2?1:0})});
  assert.equal(result.status,'FAILED');assert.equal(result.cases[2].status,'FAILED');assert.equal(result.cases.length,5);
});

test('zero exit without complete test counts is unknown; skip is partial',async()=>{
  const unknown=await evaluateSkillWorkflows({snapshot,run:async()=>tap({stdout:'ok'})});assert.equal(unknown.status,'UNKNOWN');
  const skipped=await evaluateSkillWorkflows({snapshot,run:async()=>tap({stdout:'# tests 1\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 1\n# todo 0\n'})});
  assert.equal(skipped.status,'PARTIAL');
});

test('input drift invalidates otherwise passing results',async()=>{
  let index=0;
  const result=await evaluateSkillWorkflows({snapshot:async()=>({...await snapshot(),sha256:String(index++)}),run:async()=>tap()});
  assert.equal(result.status,'UNKNOWN');assert.equal(result.inputStable,false);assert.equal(result.reason,'EVALUATION_INPUT_CHANGED');
});

test('subprocess refusal remains bounded unknown evidence without error text',async()=>{
  const result=await evaluateSkillWorkflows({snapshot,run:async()=>{throw new Refused('COMMAND_TIMEOUT','SYNTHETIC_PRIVATE_FAILURE');}});
  assert.equal(result.status,'UNKNOWN');assert(result.cases.every(value=>value.reason==='COMMAND_TIMEOUT'));
  assert(!JSON.stringify(result).includes('SYNTHETIC_PRIVATE_FAILURE'));
});

test('current checkout snapshot covers declared source and test bytes deterministically',async()=>{
  const one=await workflowSnapshot(),two=await workflowSnapshot();
  assert.deepEqual(one,two);assert(one.fileCount>100);assert.match(one.sha256,/^[a-f0-9]{64}$/);
});

test('Dots plugin implementation and manifest drift invalidate otherwise passing groups',async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-evaluation-plugin-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  const runtime=path.join(root,'runtime/discord-template');
  for(const directory of ['src','tests','tools','bin','dots-plugin/scripts'])await mkdir(path.join(runtime,directory),{recursive:true});
  for(const name of ['package.json','pnpm-lock.yaml','dots-plugin/plugin.json','dots-plugin/mcp.json','dots-plugin/scripts/server.mjs'])await writeFile(path.join(runtime,name),'synthetic fixture\n');
  for(const relative of ['.agents/skills/kotodama-intent/SKILL.md','.agents/skills/kotodama-research/SKILL.md','.agents/skills/kotodama-handoff/SKILL.md','runtime/discord-template/.agents/skills/shareable-invitation/SKILL.md']){
    const file=path.join(root,relative);await mkdir(path.dirname(file),{recursive:true});await writeFile(file,'synthetic skill\n');
  }
  for(const relative of ['dots-plugin/scripts/server.mjs','dots-plugin/plugin.json']){
    const result=await evaluateSkillWorkflows({root,run:async(executable,args)=>{
      if(args.includes('tests/dots-context.test.mjs'))await writeFile(path.join(runtime,relative),'changed synthetic fixture\n');
      return tap();
    }});
    assert(result.cases.every(value=>value.status==='PASS'));
    assert.equal(result.status,'UNKNOWN');assert.equal(result.inputStable,false);assert.equal(result.reason,'EVALUATION_INPUT_CHANGED');
    assert.notEqual((await workflowSnapshot(root)).sha256,result.inputSnapshot.sha256);
  }
});

test('snapshot refuses FIFO and symlink input before reading', {skip:process.platform==='win32'},async t=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-evaluation-'));
  t.after(async()=>{assert.equal(path.dirname(root),os.tmpdir());assert(path.basename(root).startsWith('ktdm-evaluation-'));await rm(root,{recursive:true,force:true});});
  const directory=path.join(root,'runtime/discord-template/src');await mkdir(directory,{recursive:true});
  const target=path.join(directory,'blocked.mjs');
  const command=spawnSync('mkfifo',[target],{timeout:2000});assert.equal(command.status,0);
  await assert.rejects(workflowSnapshot(root),{code:'EVALUATION_INPUT_INVALID'});
  await rm(target);await symlink('missing-target',target);
  await assert.rejects(workflowSnapshot(root),{code:'EVALUATION_LINK_REFUSED'});
});

test('only the explicit Docker fixture marker is added to the sanitized child environment',async t=>{
  const previous=process.env.KOTODAMA_TEST_VERIFIER_IMAGE;
  t.after(()=>{if(previous===undefined)delete process.env.KOTODAMA_TEST_VERIFIER_IMAGE;else process.env.KOTODAMA_TEST_VERIFIER_IMAGE=previous;});
  process.env.KOTODAMA_TEST_VERIFIER_IMAGE='synthetic-verifier-marker';
  await evaluateSkillWorkflows({snapshot,run:async(executable,args,options)=>{
    assert.equal(options.env.KOTODAMA_TEST_VERIFIER_IMAGE,'synthetic-verifier-marker');
    assert.equal(options.env.GH_TOKEN,undefined);return tap();
  }});
});
