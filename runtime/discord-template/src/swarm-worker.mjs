import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir,writeFile,readdir} from 'node:fs/promises';
import {runCommand} from './command.mjs';
import {readArtifact} from './artifact.mjs';
import {check,digest,canonical,safePath,atomicJson,Refused} from './common.mjs';

const repositoryRoot=fileURLToPath(new URL('../../../',import.meta.url));
const taskPattern=/^task-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const sha=/^[a-f0-9]{64}$/;
const jobs=['facts','counterpoints','options'];
const artifactNames=['input.json','plan.json','facts.json','counterpoints.json','options.json','review.json','result.json'];
const fixedCriteria=['C1','C2','C3','C4'];

export function swarmPayload(task,context){
  check(taskPattern.test(task.id)&&Number.isSafeInteger(task.revision)&&task.revision>0,'SWARM_TASK_BINDING_INVALID');
  check(typeof task.request==='string'&&task.request.trim()&&task.request.length<=4000,'SWARM_REQUEST_LIMIT');
  const acceptance=task.acceptance??[];check(Array.isArray(acceptance)&&acceptance.length<=20&&acceptance.every(s=>typeof s==='string'&&s.trim()&&s.length<=1000),'SWARM_ACCEPTANCE_LIMIT');
  check(Array.isArray(context)&&context.length>0&&context.length<=10,'SWARM_CONTEXT_LIMIT');
  const sources=context.map(s=>{check(sha.test(s.key)&&Number.isSafeInteger(s.revision)&&s.revision>=0&&typeof s.text==='string'&&s.text.trim()&&s.text.length<=12000,'SWARM_SOURCE_LIMIT');return {key:s.key,revision:s.revision,text:s.text,sha256:digest(s.text)};});
  check(new Set(sources.map(s=>s.key+':'+s.revision)).size===sources.length,'SWARM_SOURCE_DUPLICATE');
  check(sources.some(s=>s.key===task.source_key&&s.revision===task.source_revision),'SWARM_PRIMARY_SOURCE_MISSING');
  const bindings=task.contextSources??[];check(bindings.length===sources.length&&bindings.every(b=>sources.some(s=>s.key===b.key&&s.revision===b.revision)),'SWARM_CONTEXT_BINDING_MISMATCH');
  const payload={version:1,task_id:task.id,revision:task.revision,request:task.request,acceptance,sources};
  check(Buffer.byteLength(canonical(payload))<=256*1024,'SWARM_CONTEXT_LIMIT');return payload;
}

export class SwarmWorker {
  constructor(config,{store,syntheticFixture=false}={}){this.config=config;this.store=store;this.syntheticFixture=syntheticFixture;}
  async run(task,context,{signal,authorize=async()=>{},onStart=()=>{}}={}){
    const cfg=this.config,settings=cfg.worker.swarm;
    check(cfg.owner.kind==='local'&&this.store,'SWARM_LOCAL_OWNER_REQUIRED');
    check(task.action==='swarm_research'&&cfg.worker.actions.includes('swarm_research'),'ACTION_NOT_ALLOWED');
    check(process.platform!=='win32','SWARM_WORKER_REQUIRES_POSIX_HOST');
    check(settings&&settings.maxDailyTasks>0,'SWARM_BUDGET_REQUIRED');
    check(this.syntheticFixture||(typeof settings.codexHome==='string'&&path.isAbsolute(settings.codexHome)),'SWARM_CODEX_HOME_REQUIRED');
    const source=context.find(s=>s.key===task.source_key);check(source?.metadata?.kind==='command','SWARM_REQUIRES_SLASH_COMMAND');
    const payload=swarmPayload(task,context),executionRef=task.id+'-r'+task.revision;
    const deadline=Math.min(Date.parse(settings.authorityExpiresAt),Date.now()+settings.timeoutSeconds*1000);
    const guard=async()=>{check(!signal?.aborted,'CANCELLED');await authorize();check(Date.now()<deadline,'SWARM_AUTHORITY_EXPIRED');for(const input of context)if(input.metadata?.kind==='voice'){const speaker=input.metadata.inputAccountId??input.actorId;check(typeof speaker==='string'&&!this.store.voiceOptedOut(input.guildId,input.channelId,speaker),'SWARM_VOICE_SCOPE_REVOKED');}};
    await guard();
    check(this.store.reserveSwarmExecution(task.id,task.revision,settings.maxDailyTasks),'STOP_UNCONFIRMED');
    const root=await safePath(cfg.dataDir,path.join('runs','swarm',executionRef),{mustExist:false});
    await mkdir(path.dirname(root),{recursive:true,mode:0o700});
    try{await mkdir(root,{mode:0o700});}catch(e){if(e.code==='EEXIST')throw new Refused('STOP_UNCONFIRMED');throw e;}
    const inputPath=path.join(root,'task-input.json'),ownerPath=path.join(root,'owner.json');
    const inputBytes=Buffer.from(canonical(payload)+'\n');await writeFile(inputPath,inputBytes,{flag:'wx',mode:0o600});
    const checks=[{path:inputPath,sha256:digest(inputBytes)}],codeRoot=path.join(repositoryRoot,'runtime','task_swarm');
    const modules=(await readdir(codeRoot)).filter(name=>name.endsWith('.py')).sort();
    check(modules.length>0&&modules.length<=128,'SWARM_IMPLEMENTATION_LIMIT');
    for(const file of [...modules.map(name=>path.join(codeRoot,name)),path.join(repositoryRoot,'tools','task_swarm.py'),path.join(repositoryRoot,'requirements-task-swarm-ci.txt')]){
      const safe=await safePath(repositoryRoot,path.relative(repositoryRoot,file));checks.push({path:safe,sha256:digest(await readArtifact(safe,2*1024*1024))});
    }
    const binding={task_id:task.id,revision:task.revision,context_digest:digest(payload),owner_ref:settings.ownerRef,active_home:root,authority_ref:settings.authorityRef,capability_ref:'ref/capability/swarm_research',expires_at:deadline/1000,status:'active'};
    const actors=Object.fromEntries([...jobs.map(job=>'worker-'+job),'verifier'].map(actor=>[actor,{epoch:1,invocation_ref:executionRef+'-'+actor,actor_status:'active',capability_ref:binding.capability_ref,peers:[]}]));
    const owner={binding,actors,storage:{root,mailbox:path.join(root,'mailbox.sqlite'),payloads:path.join(root,'payloads')},source_checks:checks,allowed_actions:[]};
    const ownerBytes=Buffer.from(canonical(owner)+'\n');check(ownerBytes.length<=1024*1024,'SWARM_OWNER_INPUT_LIMIT');await writeFile(ownerPath,ownerBytes,{flag:'wx',mode:0o600});
    const child=new AbortController();let fencePromise=null,fenceFailed=false;
    const fence=()=>fencePromise??=(async()=>{let timer;try{const write=atomicJson(ownerPath,{...owner,binding:{...binding,status:'cancelled'}}).then(()=>true,()=>false);fenceFailed=!(await Promise.race([write,new Promise(resolve=>{timer=setTimeout(()=>resolve(false),2000);})]));}finally{clearTimeout(timer);child.abort();}})();
    const aborted=()=>{void fence();};signal?.addEventListener('abort',aborted,{once:true});
    const timeout=setTimeout(aborted,Math.max(1,deadline-Date.now()));timeout.unref();
    if(signal?.aborted)aborted();
    try{
      await guard();check(!child.signal.aborted,'CANCELLED');
      const args=['-B',path.join(repositoryRoot,'tools','task_swarm.py'),'task-run','--owner',ownerPath,'--input',inputPath,'--backend',this.syntheticFixture?'synthetic':'codex',...(this.syntheticFixture?['--allow-local-fixture']:['--codex-executable',settings.codexExecutable,'--task-codex-home',settings.codexHome,'--allow-codex'])];
      const command=await runCommand(settings.pythonExecutable,args,{cwd:repositoryRoot,keepStdinOpen:true,signal:child.signal,timeoutMs:Math.max(1,deadline-Date.now())+1000,maxBytes:1024*1024,onStart});
      if(fencePromise)await fencePromise;check(!fenceFailed,'STOP_UNCONFIRMED');await guard();
      if(command.code!==0){
        let refusal;try{refusal=JSON.parse(command.stderr.trim()).error;}catch{}
        check(refusal!=='stop_unconfirmed'&&refusal!=='RUN_RECOVERY_REQUIRED','STOP_UNCONFIRMED');
        throw new Refused(typeof refusal==='string'&&/^[a-zA-Z_]{1,70}$/.test(refusal)?'SWARM_'+refusal.toUpperCase():'SWARM_RUN_FAILED');
      }
      let status;try{status=JSON.parse(command.stdout);}catch{throw new Refused('SWARM_OUTPUT_INVALID');}
      const runId='task-run-'+digest([task.id,task.revision]).slice(0,32);check(status.run_id===runId&&status.synthetic===this.syntheticFixture&&status.task_state_changed===false,'SWARM_OUTPUT_INVALID');
      const directory=await safePath(root,runId),receiptBytes=await readArtifact(await safePath(directory,'receipt.json'),2*1024*1024),receipt=JSON.parse(receiptBytes);
      check(sha.test(status.receipt_sha256??'')&&digest(receiptBytes)===status.receipt_sha256,'SWARM_RECEIPT_CHANGED');
      check(receipt.version===1&&receipt.run_id===runId&&receipt.input_digest===digest(payload)&&receipt.owner_input_sha256===digest(ownerBytes)&&receipt.synthetic===this.syntheticFixture&&receipt.task_state_changed===false,'SWARM_RECEIPT_MISMATCH');
      check(Object.keys(receipt.artifact_sha256??{}).sort().join(',')===[...artifactNames].sort().join(','),'SWARM_ARTIFACT_SET_INVALID');
      const artifacts=[],documents={};
      for(const name of artifactNames){const file=await safePath(directory,name),bytes=await readArtifact(file,2*1024*1024);check(sha.test(receipt.artifact_sha256[name])&&digest(bytes)===receipt.artifact_sha256[name],'SWARM_ARTIFACT_CHANGED');artifacts.push({path:file,sha256:digest(bytes),bytes:bytes.length});documents[name]=JSON.parse(bytes);}
      const result=documents['result.json'],criteria=[...fixedCriteria,...payload.acceptance.map((_,i)=>'U'+(i+1))];
      check(result.task_id===task.id&&result.revision===task.revision&&result.synthetic===this.syntheticFixture&&result.model_runtime_verified===!this.syntheticFixture,'SWARM_RESULT_BINDING_INVALID');
      check(Array.isArray(result.validations)&&result.validations.length===criteria.length&&new Set(result.validations.map(v=>v.criterion_id)).size===criteria.length&&result.validations.every(v=>criteria.includes(v.criterion_id)&&['passed','failed','blocked','not_run'].includes(v.status)),'SWARM_CRITERIA_INCOMPLETE');
      const accepted=result.validations.every(v=>v.status==='passed');check(receipt.accepted===accepted&&result.independent_review===accepted&&result.state===(accepted?'needs_review':'failed')&&status.status===result.state,'SWARM_RESULT_STATE_INVALID');
      check(documents['review.json'].result.context_digest===digest(payload),'SWARM_REVIEW_CONTEXT_MISMATCH');
      await guard();check(digest(await readArtifact(ownerPath,1024*1024))===digest(ownerBytes),'SWARM_OWNER_CHANGED');
      const workspace=await safePath(cfg.dataDir,path.join('worktrees','swarm-results',executionRef),{mustExist:false});await mkdir(path.join(workspace,'deliverables'),{recursive:true,mode:0o700});
      const summary=jobs.map(job=>{const report=result.reports?.[job];check(report&&typeof report.summary==='string','SWARM_REPORT_MISSING');return job+'\n'+report.summary;}).join('\n\n');
      const bundle=Buffer.from(JSON.stringify(result,null,2)+'\n');check(bundle.length<=cfg.worker.maxArtifactBytes,'SWARM_RESULT_LIMIT');
      const bundlePath=path.join(workspace,'deliverables','swarm-research.txt');await writeFile(bundlePath,bundle,{flag:'wx',mode:0o600});await guard();
      artifacts.push({path:bundlePath,relative:'deliverables/swarm-research.txt',sha256:digest(bundle),bytes:bundle.length},{path:path.join(directory,'receipt.json'),sha256:digest(receiptBytes),bytes:receiptBytes.length});
      return {state:result.state,summary,artifacts,workspace,validations:result.validations,verifiedExecution:true,independentReview:accepted,synthetic:this.syntheticFixture,modelRuntimeVerified:result.model_runtime_verified,modelExecution:null,adapter:'task_swarm_v1',taskRevision:task.revision,sourceRevision:task.source_revision};
    }catch(error){await fence();if(fenceFailed)throw new Refused('STOP_UNCONFIRMED');throw error;}
    finally{clearTimeout(timeout);signal?.removeEventListener('abort',aborted);if(fencePromise)await fencePromise;}
  }
}
