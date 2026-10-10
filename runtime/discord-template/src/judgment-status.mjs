import {check,digest} from './common.mjs';
import {WORKER_ACTIONS} from './capability-lanes.mjs';
import {lumaEventSchema} from './dots.mjs';
import {awaitWithSignal,deadlineScope} from './http-limits.mjs';

const LIMIT=20,MAX_BINDINGS=32;
const policies=new Set(['never','untrusted','on-request','on-failure']);
const taskStates=new Set(['queued','running','needs_review','failed','paused','stopping','cancelled','stale','uncertain']);
const lumaQuery=`SELECT d.*,r.actor,r.source_key,r.source_revision,r.created,r.state AS request_state
  FROM dot_event_drafts d JOIN dot_requests r ON r.id=d.request_id`;

// Arguments are configuration, never observed Codex runtime policy. Do not
// print arbitrary arguments: they may contain credentials or private paths.
export function configuredToolApproval(adapter){
  const args=adapter?.args??[];let value='unspecified';
  if(args.length>256)return 'unknown';
  for(let i=0;i<args.length;i++){
    const arg=args[i];let candidate;
    if(arg==='-a'||arg==='--ask-for-approval')candidate=args[++i];
    else if(arg.startsWith('--ask-for-approval='))candidate=arg.slice(19);
    else if((arg==='-c'||arg==='--config')&&/^approval_policy\s*=/.test(args[i+1]??''))candidate=args[++i].split('=').slice(1).join('=').trim().replace(/^["']|["']$/g,'');
    else if(/^--config=approval_policy\s*=/.test(arg))candidate=arg.split('=').slice(2).join('=').trim().replace(/^["']|["']$/g,'');
    if(candidate!==undefined)value=policies.has(candidate)?candidate:'unknown';
  }
  return value;
}

function driftFields(start,current){
  return ['dataDir','owner','discordInstallation','workspace','workerAdapter','verification','channelWorkspaces','analyzer'].filter(field=>{
    const select=c=>({dataDir:c.dataDir,owner:c.owner,discordInstallation:[c.installation,c.discord.guildId,c.discord.applicationId],workspace:c.worker.workspace,
      workerAdapter:[c.worker.executable,c.worker.args,c.worker.model,c.worker.codexHome,c.worker.ignoreUserConfig,c.worker.fallback],
      verification:[c.worker.verification,c.worker.verify],channelWorkspaces:c.worker.channelWorkspaces,analyzer:c.analyzer})[field]??null;
    return digest(select(start))!==digest(select(current));
  });
}

function actionStatus(action,start,current,drift,now){
  const reasons=[];
  if(!current.worker.actions.includes(action))reasons.push('ACTION_NOT_ALLOWED');
  if(!start.worker.actions.includes(action))reasons.push('WORKER_RESTART_REQUIRED');
  if(drift.length)reasons.push('RUNTIME_CONFIGURATION_CHANGED');
  if(current.owner.kind!=='local')reasons.push('REMOTE_OWNER_UNOBSERVED');
  if(['write_file','develop','create_company_pack','swarm_research'].includes(action)&&process.platform!=='linux')reasons.push('LINUX_HOST_REQUIRED');
  if(['write_file','develop'].includes(action)&&(!start.worker.verification||!start.worker.verify.length))reasons.push('WRITE_VERIFICATION_REQUIRED');
  if(action==='create_company_pack'){
    if(!start.worker.verification)reasons.push('VERIFICATION_ISOLATION_REQUIRED');
    if(!current.worker.companyPack)reasons.push('COMPANY_PACK_NOT_CONFIGURED');
    else if(Date.parse(current.worker.companyPack.authorityExpiresAt)<=now)reasons.push('COMPANY_PACK_AUTHORITY_EXPIRED');
    if(digest(current.worker.companyPack??null)!==digest(start.worker.companyPack??null))reasons.push('COMPANY_PACK_BINDING_CHANGED');
  }
  if(action==='swarm_research'){
    if(!current.worker.swarm||current.worker.swarm.maxDailyTasks<=0||!current.worker.swarm.codexHome)reasons.push('SWARM_NOT_CONFIGURED');
    else if(Date.parse(current.worker.swarm.authorityExpiresAt)<=now)reasons.push('SWARM_AUTHORITY_EXPIRED');
    if(digest(current.worker.swarm??null)!==digest(start.worker.swarm??null))reasons.push('SWARM_BINDING_CHANGED');
  }
  return {action,configured:current.worker.actions.includes(action),runningWorkerConfigured:start.worker.actions.includes(action),
    eligibility:reasons.length?'blocked':'scope_check_required',reasons};
}

function technical(result,matching){
  if(!matching)return {execution:'invalidated',checks:'invalidated',independentReview:'invalidated',artifactReadback:'not_run'};
  const checks=Array.isArray(result?.validations)?result.validations:[];
  return {execution:result?.verifiedExecution===true?'reported':'unobserved',
    checks:checks.length>32?'unobserved':checks.length?checks.every(v=>v.exitCode===0||v.status==='passed')?'reported_pass':'reported_failure':'unobserved',checksTruncated:checks.length>32,
    independentReview:result?.independentReview===true||result?.independent_review===true?'reported_pass':'unobserved',artifactReadback:'not_run'};
}

function sourceBindings(store,task,actor){
  check(Array.isArray(task.contextSources??[])&&(task.contextSources??[]).length<=MAX_BINDINGS,'JUDGMENT_BINDING_LIMIT');
  const bindings=[{key:task.source_key,revision:task.source_revision},...(task.contextSources??[])];
  return bindings.map(binding=>{const source=store.source(binding.key,actor);return {key:binding.key,expected:binding.revision,revision:source.revision};});
}

/** One bounded read over the existing owners. Timed-out provider reads retain
 * the slot until they settle; retries cannot build an unbounded raw queue. */
export class JudgmentStatusReader{
  constructor({config,store,owner,dots=()=>null,authorize,readPolicy,assertActive=()=>{},accessEpoch=()=>null,track=()=>{},now=Date.now,timeoutMs=8000}){
    check(typeof authorize==='function'&&typeof readPolicy==='function','JUDGMENT_AUTHORIZATION_REQUIRED');
    check(Number.isSafeInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=10000,'JUDGMENT_LIMIT_INVALID');
    Object.assign(this,{config,store,owner,dots,authorize,readPolicy,assertActive,accessEpoch,track,now,timeoutMs});this.pending=null;
  }
  async read({actor,taskId}={}){
    check(!this.pending,'JUDGMENT_BUSY');check(typeof actor==='string'&&/^\d{5,24}$/.test(actor),'OPERATOR_REQUIRED');
    check(taskId===undefined||typeof taskId==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(taskId),'JUDGMENT_TASK_INVALID');
    const deadline=deadlineScope(this.timeoutMs,'JUDGMENT_READ_TIMEOUT');
    const work=this.report({actor,taskId,signal:deadline.signal});this.pending=work;
    const settled=()=>{if(this.pending===work)this.pending=null;};work.then(settled,settled);this.track(work);
    try{return await awaitWithSignal(work,deadline.signal);}finally{deadline.dispose();}
  }
  async drain({timeoutMs=15000}={}){
    if(!this.pending)return;
    const deadline=deadlineScope(timeoutMs,'JUDGMENT_DRAIN_UNCERTAIN');
    try{await awaitWithSignal(this.pending.catch(()=>{}),deadline.signal);}finally{deadline.dispose();}
  }
  async report({actor,taskId,signal}){
    const guard=()=>{signal.throwIfAborted();this.assertActive();};guard();
    const current=await this.readPolicy();guard();check(current.discord.operators.includes(actor),'OPERATOR_REQUIRED');
    const policyDigest=digest(current),accessEpoch=this.accessEpoch(),start=this.config,now=this.now();check(Number.isSafeInteger(now),'JUDGMENT_CLOCK_INVALID');
    const drift=driftFields(start,current),actions=WORKER_ACTIONS.map(action=>actionStatus(action,start,current,drift,now));
    const report={kind:'kotodama.judgment-status',version:1,observedAt:new Date(now).toISOString(),scope:'authenticated_actor',
      configured:{taskOwner:current.owner.kind,actions:[...current.worker.actions],clarification:current.interaction.clarification},
      effective:{runningTaskOwner:start.owner.kind,configurationDrift:drift,actions,technicalPreflight:'not_run',executionAuthorized:false},
      codexToolApproval:{configured:{worker:configuredToolApproval(current.worker),analyzer:current.analyzer.kind==='responses'?'not_applicable':configuredToolApproval(current.analyzer)},
        runningConfiguration:{worker:configuredToolApproval(start.worker),analyzer:start.analyzer.kind==='responses'?'not_applicable':configuredToolApproval(start.analyzer)},observed:'unknown',businessDecisionAffected:false},
      humanDecision:{requirement:'unknown',receipt:'unobserved',reason:'BUSINESS_DECISION_OWNER_UNOBSERVED'},
      identity:{humanStepRequired:'unknown',authenticatedProviderSession:'unobserved'},
      tasks:{state:'unobserved',items:[],unavailable:0,truncated:false,limit:LIMIT},
      luma:{state:'unobserved',items:[],unavailable:0,truncated:false,limit:LIMIT},
      mutationsEnabled:false,claims:{humanGo:false,promotion:false,currentTruthChanged:false,providerVerified:false},publicBeta:'NO_GO_UNPUBLISHED'};
    const receipts=[];
    // A remote owner replaces SQLite Tasks. Never inspect the local mirror or
    // claim remote decisions from this diagnostic's local configuration.
    if(start.owner.kind==='local'&&current.owner.kind==='local'&&this.owner===this.store&&drift.length===0){
      const ids=taskId?[taskId]:this.store.db.prepare('SELECT id FROM tasks WHERE actor=? ORDER BY rowid DESC LIMIT ?').all(actor,LIMIT+1).map(row=>row.id);
      report.tasks.state='observed';report.tasks.truncated=ids.length>LIMIT;
      for(const id of ids.slice(0,LIMIT)){
        guard();
        try{
          const task=this.store.taskInternal(id);check(task.actor===actor,'TASK_ACCESS_DENIED');
          check(/^task-[a-f0-9-]{36}$/.test(task.id)&&Number.isSafeInteger(task.revision)&&Number.isSafeInteger(task.source_revision),'JUDGMENT_RECORD_INVALID');
          const before=sourceBindings(this.store,task,actor);await this.authorize(task);guard();
          const latest=this.store.taskInternal(id);check(digest(latest)===digest(task),'TASK_CHANGED');
          const after=sourceBindings(this.store,latest,actor);check(digest(before)===digest(after),'SOURCE_CHANGED');
          const matching=after.every(b=>b.expected===b.revision),allowed=actions.find(a=>a.action===task.action);
          check(Array.isArray(task.requiredActions??[])&&(task.requiredActions??[]).length<=MAX_BINDINGS,'JUDGMENT_BINDING_LIMIT');
          const granted=(task.requiredActions??[task.action]).every(action=>actions.some(a=>a.action===action&&a.eligibility==='scope_check_required'));
          report.tasks.items.push({id:task.id,revision:task.revision,action:WORKER_ACTIONS.includes(task.action)?task.action:'unknown',state:taskStates.has(task.state)?task.state:'unknown',
            sourceBinding:matching?'matching':'mismatched',executionEligibility:matching&&allowed?.eligibility==='scope_check_required'&&granted?'scope_check_required':'blocked',
            review:matching&&task.state==='needs_review'?'RESULT_REVIEW_PENDING':'none',humanDecisionRequired:'unknown',approvalReceipt:'unobserved',technical:technical(task.result,matching)});
          receipts.push(()=>check(digest(this.store.taskInternal(id))===digest(task)&&digest(sourceBindings(this.store,task,actor))===digest(after),'JUDGMENT_INPUT_CHANGED'));
        }catch(error){guard();report.tasks.unavailable++;}
      }
    }else report.tasks.reason=current.owner.kind==='remote'||start.owner.kind==='remote'?'REMOTE_OWNER_UNOBSERVED':'RUNTIME_CONFIGURATION_CHANGED';
    const dots=this.dots();
    if(!taskId&&dots&&current.dots.enabled&&current.dots.actorId===actor&&start.dots.actorId===actor&&drift.length===0){
      const rows=this.store.db.prepare(lumaQuery+' WHERE r.actor=? ORDER BY d.rowid DESC LIMIT ?').all(actor,LIMIT+1);
      report.luma.state='observed';report.luma.truncated=rows.length>LIMIT;
      for(const row of rows.slice(0,LIMIT)){
        guard();
        try{
          check(/^luma_[a-f0-9]{24}$/.test(row.id)&&Number.isSafeInteger(row.source_revision),'JUDGMENT_RECORD_INVALID');
          const source=this.store.source(row.source_key,actor);check(source.provider==='discord'&&source.guildId===current.discord.guildId&&current.dots.channelIds.includes(source.channelId),'DOTS_SOURCE_SCOPE_CHANGED');
          await dots.authorize(source);guard();
          check(digest(this.store.source(row.source_key,actor))===digest(source),'DOTS_SOURCE_CHANGED');
          let parsed;try{parsed=lumaEventSchema.safeParse(JSON.parse(row.event));}catch{parsed={success:false};}
          const matches=source.revision===row.source_revision&&row.revision===row.source_revision&&parsed.success&&digest({operation:row.operation,targetUrl:row.target_url,event:parsed.data})===row.digest;
          const requestFresh=now>=row.created&&now-row.created<=current.dots.requestTtlSeconds*1000;
          let approval='missing';
          if(row.state==='expired')approval='expired';
          else if(!matches||row.state==='superseded')approval='mismatched';
          else if(row.approved_at!==null){
            if(!Number.isSafeInteger(row.approved_at)||now<row.approved_at)approval='mismatched';
            else if(['executing','uncertain','reported'].includes(row.state))approval='consumed';
            else if(now-row.approved_at>300000||!requestFresh)approval='expired';
            else if(row.state==='approved'&&row.request_state==='pending')approval='valid';
            else approval='mismatched';
          }
          const canReview=matches&&requestFresh&&row.request_state==='pending'&&['needs_review','approved'].includes(row.state);
          report.luma.items.push({id:row.id,sourceRevision:row.source_revision,candidateDigest:/^[a-f0-9]{64}$/.test(row.digest)?row.digest:null,operation:['create','update'].includes(row.operation)?row.operation:'unknown',
            humanDecisionRequired:true,approvalReceipt:approval,pendingDecision:canReview&&(approval==='missing'||approval==='expired')?'HUMAN_DECISION_REQUIRED':!canReview&&approval!=='consumed'?'CANDIDATE_RECONCILIATION_REQUIRED':'none',
            executionAuthorized:false,readback:row.reported!==null?'reported_not_independently_verified':'unobserved'});
          receipts.push(()=>check(digest(this.store.db.prepare(lumaQuery+' WHERE d.id=? AND r.actor=?').get(row.id,actor))===digest(row)&&digest(this.store.source(row.source_key,actor))===digest(source),'JUDGMENT_INPUT_CHANGED'));
        }catch(error){guard();report.luma.unavailable++;}
      }
    }else report.luma.reason=taskId?'TASK_SCOPE_ONLY':!current.dots.enabled?'DOTS_DISABLED':'DOTS_SCOPE_UNOBSERVED';
    const final=await this.readPolicy();guard();check(final.discord.operators.includes(actor),'OPERATOR_REQUIRED');check(digest(final)===policyDigest,'JUDGMENT_POLICY_CHANGED');
    check(this.accessEpoch()===accessEpoch,'JUDGMENT_ACCESS_CHANGED');
    for(const receipt of receipts)receipt();
    return report;
  }
}

export function formatJudgmentStatus(report){
  const lines=['ことだま — 判断と許可の現在地（読取専用）',`設定された操作: ${report.configured.actions.join(', ')||'なし'}`,
    `起動時設定との差分: ${report.effective.configurationDrift.join(', ')||'なし'}`,
    `Codex tool approval: 設定 ${report.codexToolApproval.configured.worker} / 実効値 ${report.codexToolApproval.observed}`,
    '会社のHuman Decision: 未観測 / 本人ログインの必要性: 未観測'];
  for(const action of report.effective.actions)if(action.configured)lines.push(`${action.action}: ${action.eligibility}${action.reasons.length?' / '+action.reasons.join(', '):' / 対象scopeと実行前検査が必要'}`);
  for(const task of report.tasks.items)lines.push(`${task.id}: ${task.state} / ${task.review} / 独立review ${task.technical.independentReview}`);
  for(const draft of report.luma.items)lines.push(`${draft.id}: 人間承認 ${draft.approvalReceipt} / ${draft.pendingDecision}`);
  lines.push(`Task: ${report.tasks.state} / 閲覧不可 ${report.tasks.unavailable} / 続き ${report.tasks.truncated?'あり':'なし'}`,
    `Luma: ${report.luma.state} / 閲覧不可 ${report.luma.unavailable} / 続き ${report.luma.truncated?'あり':'なし'}`,
    'この表示は実行・承認・Promotionを行いません。');
  return lines.join('\n');
}
