import {readdir,open,lstat} from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {check,digest,safePath,errorCode} from '../src/common.mjs';
import {runCommand,workerEnv} from '../src/command.mjs';

const ROOT=fileURLToPath(new URL('../../..',import.meta.url));
const RUNTIME='runtime/discord-template';
export const WORKFLOW_CASES=Object.freeze([
  {id:'skill_delivery',tests:['project-skill-input.test.mjs','project-skill-policy.test.mjs']},
  {id:'requirements_clarification',tests:['clarify-once.test.mjs']},
  {id:'research_context',tests:['dots-context.test.mjs','project-context.test.mjs']},
  {id:'writing_corrections',tests:['native-corrections.test.mjs']},
  {id:'development_verification',tests:['runtime.test.mjs','verification.test.mjs']},
].map(value=>Object.freeze({...value,tests:Object.freeze(value.tests)})));

// Only the declared local source/test inputs are read. Private data dirs,
// environment values, dependency contents and child output are not receipts.
export async function workflowSnapshot(root=ROOT){
  const paths=[];let visited=0;
  async function walk(relative,depth=0){
    check(depth<=8,'EVALUATION_INPUT_DEPTH');
    const directory=await safePath(root,relative);
    for(const entry of await readdir(directory,{withFileTypes:true})){
      check(++visited<=2048,'EVALUATION_INPUT_COUNT');
      check(!entry.isSymbolicLink(),'EVALUATION_LINK_REFUSED');
      const next=relative+'/'+entry.name;
      if(entry.isDirectory())await walk(next,depth+1);
      else if(/\.(mjs|json)$/.test(entry.name)){
        check(entry.isFile(),'EVALUATION_INPUT_INVALID');paths.push(next);
      }
    }
  }
  for(const directory of ['src','tests','tools','bin','dots-plugin'])await walk(RUNTIME+'/'+directory);
  paths.push(RUNTIME+'/package.json',RUNTIME+'/pnpm-lock.yaml');
  for(const name of ['intent','research','handoff'])paths.push('.agents/skills/kotodama-'+name+'/SKILL.md');
  paths.push(RUNTIME+'/.agents/skills/shareable-invitation/SKILL.md');
  check(paths.length<=512,'EVALUATION_INPUT_COUNT');
  const records=[];let totalBytes=0;
  for(const relative of [...new Set(paths)].sort()){
    const target=await safePath(root,relative),before=await lstat(target);
    check(before.isFile()&&before.nlink===1&&before.size<=1048576,'EVALUATION_INPUT_INVALID');
    const handle=await open(target,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));
    try{
      const stat=await handle.stat();
      check(stat.isFile()&&stat.nlink===1&&stat.dev===before.dev&&stat.ino===before.ino&&stat.size===before.size,'EVALUATION_INPUT_INVALID');
      check(totalBytes+stat.size<=8388608,'EVALUATION_INPUT_BYTES');
      const bytes=Buffer.alloc(stat.size+1);const {bytesRead}=await handle.read(bytes,0,bytes.length,0);
      check(bytesRead===stat.size,'EVALUATION_INPUT_CHANGED');
      totalBytes+=bytesRead;records.push({path:relative,sha256:digest(bytes.subarray(0,bytesRead))});
    }finally{await handle.close();}
  }
  return {sha256:digest(records),fileCount:records.length,totalBytes};
}

function counts(stdout){
  const result={};
  for(const name of ['tests','pass','fail','cancelled','skipped','todo']){
    const matches=[...stdout.matchAll(new RegExp('^# '+name+' (\\d+)\\r?$','gm'))];
    check(matches.length===1,'EVALUATION_SUMMARY_UNKNOWN');
    result[name]=Number(matches[0][1]);check(Number.isSafeInteger(result[name]),'EVALUATION_SUMMARY_UNKNOWN');
  }
  check(result.tests>0&&result.tests===result.pass+result.fail+result.cancelled+result.skipped+result.todo,'EVALUATION_SUMMARY_UNKNOWN');
  return result;
}

export async function evaluateSkillWorkflows({root=ROOT,run=runCommand,snapshot=()=>workflowSnapshot(root)}={}){
  const before=await snapshot(),cases=[];
  for(const spec of WORKFLOW_CASES){
    const record={id:spec.id,tests:[...spec.tests],status:'UNKNOWN'};
    try{
      const result=await run(process.execPath,['--test','--test-reporter=tap','--test-concurrency=1','--test-timeout=30000',...spec.tests.map(name=>'tests/'+name)],{
        cwd:path.join(root,RUNTIME),timeoutMs:90000,maxBytes:2000000,
        env:workerEnv(process.env.KOTODAMA_TEST_VERIFIER_IMAGE?{KOTODAMA_TEST_VERIFIER_IMAGE:process.env.KOTODAMA_TEST_VERIFIER_IMAGE}:{}),
      });
      record.exitCode=result.code;record.outputSha256=digest([result.stdout,result.stderr]);
      if(result.code!==0)record.status='FAILED';
      else{
        record.counts=counts(result.stdout);
        record.status=record.counts.fail||record.counts.cancelled?'FAILED':record.counts.skipped||record.counts.todo?'PARTIAL':'PASS';
      }
    }catch(error){record.reason=errorCode(error);}
    cases.push(record);
  }
  let inputStable=false;
  try{inputStable=(await snapshot()).sha256===before.sha256;}catch{}
  const status=!inputStable||cases.some(record=>record.status==='UNKNOWN')?'UNKNOWN':cases.some(record=>record.status==='FAILED')?'FAILED':cases.some(record=>record.status==='PARTIAL')?'PARTIAL':'PASS';
  return {schemaVersion:'kotodama.skill-workflow-evaluation.v1',status,evidenceTier:'LOCAL',
    observedAt:new Date().toISOString(),nodeVersion:process.version,inputSnapshot:before,inputStable,
    cases,modelReasoningEvaluated:false,liveProviderAccepted:false,
    unexecuted:['requirement_tradeoff_quality','research_recommendation_quality','writing_reader_acceptance','development_requester_acceptance'],
    ...(inputStable?{}:{reason:'EVALUATION_INPUT_CHANGED'})};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{
    check(process.argv.length===2,'EVALUATION_ARGUMENTS_UNSUPPORTED');
    const receipt=await evaluateSkillWorkflows();console.log(JSON.stringify(receipt));
    if(receipt.status!=='PASS')process.exitCode=1;
  }catch(error){console.log(JSON.stringify({status:'UNKNOWN',reason:errorCode(error),evidenceTier:'LOCAL',modelReasoningEvaluated:false}));process.exitCode=1;}
}
