import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir,writeFile,lstat} from 'node:fs/promises';
import {runCommand} from './command.mjs';
import {DockerVerifier} from './verification.mjs';
import {readArtifact} from './artifact.mjs';
import {check,digest,canonical,safePath,inside,Refused} from './common.mjs';

const repositoryRoot=fileURLToPath(new URL('../../../',import.meta.url));
const executor=path.join(repositoryRoot,'tools','run_company_pack_task.py');
const taskId=/^task-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const sha=/^[a-f0-9]{64}$/;
// Matches the executor's ensure_ascii=True canonical JSON, including its final LF.
export const companyPackDigest=value=>digest(canonical(value).replace(/[^\x00-\x7f]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'))+'\n');
const integrityProgram=`const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');const expected=JSON.parse(process.argv[1]),pending=['.'],seen=[];let entries=0,total=0;while(pending.length){const dir=pending.pop();for(const item of fs.readdirSync(dir)){assert(++entries<=128);const name=path.join(dir,item),stat=fs.lstatSync(name);assert(!stat.isSymbolicLink());if(stat.isDirectory()){pending.push(name);continue;}assert(stat.isFile()&&stat.nlink===1&&seen.length<64);const bytes=fs.readFileSync(name);total+=bytes.length;assert(total<=1048576);assert.deepEqual(expected[name],{bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});seen.push(name);}}assert.deepEqual(seen.sort(),Object.keys(expected).sort());console.log(JSON.stringify({status:'PASS',files:seen.length}));`;

export function companyPackPaths(config){
  const settings=config.worker.companyPack;check(settings,'COMPANY_PACK_CONFIG_REQUIRED');
  const namespace=path.join(config.dataDir,'worktrees','company-pack-operations'),output=path.resolve(settings.outputRoot);
  check(path.isAbsolute(config.dataDir)&&path.isAbsolute(settings.outputRoot)&&inside(namespace,output),'COMPANY_PACK_OUTPUT_SCOPE');
  return {output,reports:path.join(config.dataDir,'worktrees','company-pack-results')};
}

export class CompanyPackWorker {
  constructor(config,{verifier}={}){this.config=config;this.verifier=verifier??new DockerVerifier(config.worker.verification);}
  async run(task,_context,{signal,authorize=async()=>{},onStart=()=>{}}={}){
    const cfg=this.config,settings=cfg.worker.companyPack;
    check(cfg.owner.kind==='local','COMPANY_PACK_LOCAL_OWNER_REQUIRED');check(cfg.worker.actions.includes('create_company_pack')&&task.action==='create_company_pack','ACTION_NOT_ALLOWED');
    check(process.platform==='linux','WRITE_WORKER_REQUIRES_LINUX_HOST');
    check(taskId.test(task.id)&&Number.isSafeInteger(task.revision)&&task.revision>0&&task.requiredActions?.length===1&&task.requiredActions[0]==='create_company_pack','COMPANY_PACK_TASK_BINDING_INVALID');
    check(typeof task.request==='string'&&/^[a-z0-9][a-z0-9-]{1,62}$/.test(task.request.trim()),'COMPANY_PACK_ID_REQUIRED');
    check(task.intentIds?.length===1&&sha.test(task.intentIds[0])&&sha.test(task.source_key)&&Number.isSafeInteger(task.source_revision),'COMPANY_PACK_TASK_BINDING_INVALID');
    const roots=companyPackPaths(cfg),executionRef=`${task.id}-r${task.revision}`;
    const guard=async()=>{await authorize();check(Date.parse(settings.authorityExpiresAt)>Date.now(),'COMPANY_PACK_AUTHORITY_EXPIRED');};
    await guard();await this.verifier.preflight({signal});await guard();
    const output=await safePath(cfg.dataDir,path.relative(cfg.dataDir,roots.output));check((await lstat(output)).isDirectory(),'COMPANY_PACK_OUTPUT_ROOT_REQUIRED');
    const sourceRun=await runCommand(settings.pythonExecutable,['-S','-B',executor,'--source-binding'],{cwd:repositoryRoot,signal,timeoutMs:30000,maxBytes:65536,onStart});
    check(sourceRun.code===0,'COMPANY_PACK_EXECUTOR_UNAVAILABLE');let source;try{source=JSON.parse(sourceRun.stdout);}catch{throw new Refused('COMPANY_PACK_SOURCE_INVALID');}
    check(Object.keys(source).sort().join(',')==='revision,sha256'&&/^[a-f0-9]{40}$/.test(source.revision)&&sha.test(source.sha256),'COMPANY_PACK_SOURCE_INVALID');
    await guard();
    const workspace=await safePath(cfg.dataDir,path.relative(cfg.dataDir,path.join(roots.reports,executionRef)),{mustExist:false});await mkdir(path.dirname(workspace),{recursive:true,mode:0o700});
    try{await mkdir(workspace,{mode:0o700});}catch(error){if(error.code==='EEXIST')throw new Refused('COMPANY_PACK_ATTEMPT_EXISTS');throw error;}
    const inputRoot=await safePath(cfg.dataDir,path.join('runs','company-pack',executionRef),{mustExist:false});await mkdir(inputRoot,{recursive:true,mode:0o700});
    const request={kind:'company_pack_task_request',operation:'CREATE_COMPANY_PACK',operation_key:executionRef,task_ref:'task:'+task.id,
      work_order_ref:settings.workOrderRef,capability_ref:settings.capabilityRef,authorized_output_root:output,source,pack_id:task.request.trim(),
      human_intent_ref:'human-intent:'+task.intentIds[0],authority_expires_at:settings.authorityExpiresAt,retention_policy_ref:settings.retentionPolicyRef};
    const binding={kind:'company_pack_discord_task_binding',version:'1.0',owner_kind:'local',owner_ref:settings.ownerRef,
      database_path:await safePath(cfg.dataDir,'kotodama.sqlite'),task_id:task.id,task_revision:task.revision,source_key:task.source_key,
      source_revision:task.source_revision,required_actions:task.requiredActions,request_sha256:companyPackDigest(request)};
    const requestPath=path.join(inputRoot,'request.json'),bindingPath=path.join(inputRoot,'binding.json');
    await writeFile(requestPath,JSON.stringify(request),{flag:'wx',mode:0o600});await writeFile(bindingPath,JSON.stringify(binding),{flag:'wx',mode:0o600});
    await guard();
    const executed=await runCommand(settings.pythonExecutable,['-S','-B',executor,requestPath,'--record-binding',bindingPath,'--authorize-local-output-root',output],{cwd:repositoryRoot,signal,timeoutMs:cfg.worker.timeoutSeconds*1000,maxBytes:500000,onStart});
    check(executed.code===0,'COMPANY_PACK_GENERATION_REFUSED');await guard();
    const operation=await safePath(output,executionRef),receiptPath=await safePath(operation,'receipt.json'),receiptBytes=await readArtifact(receiptPath,500000);
    let receipt;try{receipt=JSON.parse(receiptBytes);}catch{throw new Refused('COMPANY_PACK_RECEIPT_INVALID');}
    check(receipt.kind==='company_pack_operation_receipt'&&receipt.status==='LOCAL_PASS'&&receipt.task_state_changed===false&&receipt.public_beta==='NO_GO_UNPUBLISHED'&&receipt.task_ref===request.task_ref&&receipt.operation_key===executionRef&&receipt.request_sha256===companyPackDigest(request),'COMPANY_PACK_RECEIPT_INVALID');
    check(receipt.record_binding?.kind==='discord_local_owner_readback'&&receipt.record_binding.sha256===companyPackDigest(binding)&&receipt.record_binding.task_revision===task.revision&&receipt.record_binding.source_revision===task.source_revision&&receipt.record_binding.source_key===task.source_key&&receipt.record_binding.authority_verified===false,'COMPANY_PACK_RECEIPT_INVALID');
    const files=receipt.output?.files;check(files&&typeof files==='object'&&!Array.isArray(files)&&Object.keys(files).length>0&&Object.keys(files).length<=64&&receipt.output.sha256===companyPackDigest(files),'COMPANY_PACK_RECEIPT_INVALID');
    const pack=await safePath(operation,'pack'),artifacts=[],bundleFiles=[];let total=0;
    for(const [relative,expected]of Object.entries(files)){
      check(/^[A-Za-z0-9._/-]+$/.test(relative)&&!relative.split('/').some(v=>['','..','.'].includes(v))&&Number.isSafeInteger(expected?.bytes)&&expected.bytes>=0&&sha.test(expected.sha256),'COMPANY_PACK_RECEIPT_INVALID');
      const file=await safePath(pack,relative),bytes=await readArtifact(file,Math.min(cfg.worker.maxArtifactBytes,1048576));total+=bytes.length;
      check(total<=1048576&&bytes.length===expected.bytes&&digest(bytes)===expected.sha256,'COMPANY_PACK_OUTPUT_CHANGED');
      artifacts.push({path:file,relative:'pack/'+relative,sha256:expected.sha256,bytes:bytes.length});
      bundleFiles.push({path:relative,sha256:expected.sha256,text:new TextDecoder('utf-8',{fatal:true}).decode(bytes)});
    }
    const verification=await this.verifier.verify({executable:'node',args:['-e',integrityProgram,JSON.stringify(files)]},{cwd:pack,signal,authorize:guard,timeoutMs:cfg.worker.timeoutSeconds*1000});
    check(verification.code===0,'COMPANY_PACK_VERIFICATION_FAILED');await guard();
    for(const artifact of artifacts)check(digest(await readArtifact(artifact.path,artifact.bytes))===artifact.sha256,'COMPANY_PACK_OUTPUT_CHANGED');
    check(digest(await readArtifact(receiptPath,500000))===digest(receiptBytes),'COMPANY_PACK_OUTPUT_CHANGED');
    const bundle=JSON.stringify({kind:'kotodama.company_pack_bundle',version:1,packId:request.pack_id,taskId:task.id,taskRevision:task.revision,
      source,outputSha256:receipt.output.sha256,recordBindingSha256:receipt.record_binding.sha256,files:bundleFiles,publicBeta:'NO_GO_UNPUBLISHED'},null,2)+'\n';
    check(Buffer.byteLength(bundle)<=Math.min(cfg.worker.maxArtifactBytes,2000000),'ARTIFACT_SIZE_LIMIT');
    const deliverables=path.join(workspace,'deliverables');await mkdir(deliverables,{mode:0o700});const bundlePath=path.join(deliverables,'company-pack.txt');await writeFile(bundlePath,bundle,{flag:'wx',mode:0o600});
    artifacts.push({path:receiptPath,relative:'operation-receipt.json',sha256:digest(receiptBytes),bytes:receiptBytes.length},{path:bundlePath,relative:'deliverables/company-pack.txt',sha256:digest(bundle),bytes:Buffer.byteLength(bundle)});
    await guard();return {state:'needs_review',summary:`Company Pack「${request.pack_id}」のdraftを作成し、全ファイルの内容と検証情報をテキスト束へまとめました。受入の確認をお願いします。`,
      workspace,artifacts,sourceRevision:task.source_revision,taskRevision:task.revision,verifiedExecution:true,independentReview:false,modelExecution:null,
      validations:[{command:'company_pack_integrity',exitCode:verification.code,outputSha256:digest(verification.stdout+verification.stderr),isolation:verification.isolation}],adapter:'company_pack_builtin_v1'};
  }
}
