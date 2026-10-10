import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,symlink,link} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Config,exampleConfig} from '../src/config.mjs';
import {CliWorker} from '../src/worker.mjs';
import {runCommand} from '../src/command.mjs';
import {digest,inside} from '../src/common.mjs';
import {loadProjectSkillInput,projectSkillsDigest,MAX_PROJECT_SKILL_BYTES} from '../src/project-skill-input.mjs';

const name='fixture-method';
const skill=(body='原文を確認して、最新の訂正と根拠を成果へ反映する。',declared=name)=>`---\nname: ${declared}\ndescription: 合成課題を検査する手順。\n---\n${body}\n`;
async function git(cwd,args){const result=await runCommand('git',args,{cwd,timeoutMs:15000});assert.equal(result.code,0,result.stderr);return result.stdout.trim();}
async function fixture(t,{names=[name],body=skill(),projectSkills,mode={}}={}){
  const root=await mkdtemp(path.join(os.tmpdir(),'ktdm-skill-input-')),repo=path.join(root,'repo'),data=path.join(root,'data');await mkdir(repo);
  await git(repo,['init','-q']);await git(repo,['config','core.autocrlf','false']);await git(repo,['config','user.name','Synthetic']);await git(repo,['config','user.email','synthetic@example.invalid']);
  await writeFile(path.join(repo,'source.txt'),'initial\n');
  for(const selected of names){const dir=path.join(repo,'.agents','skills',selected);await mkdir(dir,{recursive:true});await writeFile(path.join(dir,'SKILL.md'),selected===name?body:skill('合成の別手順。',selected));}
  await git(repo,['add','.']);await git(repo,['commit','-qm','fixture']);
  const config=exampleConfig({workspace:repo});config.dataDir=data;
  config.worker.projectSkills=projectSkills??{research:[name],develop:[name],write_file:[name]};
  config.worker.actions=['research','summarize','develop','write_file'];config.worker.executable=process.execPath;config.worker.timeoutSeconds=10;
  const capture=path.join(root,'capture.json'),cli=path.join(root,'capture-cli.mjs');
  const proof=path.join(data,'artifacts','task-fixture-r1','input-receipt.json');
  await writeFile(cli,`
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const [capture,proof,modeJson,...args]=process.argv.slice(2),mode=JSON.parse(modeJson),chunks=[];
for await(const chunk of process.stdin)chunks.push(chunk);
const bytes=Buffer.concat(chunks),input=bytes.toString('utf8'),hash=b=>createHash('sha256').update(b).digest('hex');
const prepared=JSON.parse(await readFile(proof,'utf8')),schema=await readFile(args[args.indexOf('--output-schema')+1]);
if(prepared.status!=='prepared'||prepared.inputBinding.stdinSha256!==hash(bytes)||prepared.inputBinding.stdinBytes!==bytes.length||prepared.inputBinding.schemaSha256!==hash(schema))throw Error('input proof was not persisted before execution');
await writeFile(capture,JSON.stringify({input,stdinSha256:hash(bytes),stdinBytes:bytes.length,schemaSha256:hash(schema),prepared,args,cwd:process.cwd()}));
if(mode.fail){process.stderr.write('Not logged in. Please run codex login.');process.exit(1);}
if(mode.write)await writeFile('created.txt','verified candidate\\n');
if(mode.mutateSkill){const file='.agents/skills/${name}/SKILL.md';await writeFile(file,(await readFile(file,'utf8'))+'changed\\n');}
if(mode.mutateHead){await writeFile('source.txt','new revision\\n');execFileSync('git',['-c','core.hooksPath=/dev/null','add','source.txt']);execFileSync('git',['-c','core.hooksPath=/dev/null','commit','-qm','changed']);}
console.log(JSON.stringify({type:'item.completed',item:{type:'agent_message',text:JSON.stringify({summary:'合成の成果です。',files:mode.write?['created.txt']:[]})}}));
`);
  config.worker.args=[cli,capture,proof,JSON.stringify(mode)];
  const task={id:'task-fixture',revision:1,source_revision:7,action:'research',request:'指定された合成課題を実行する。',acceptance:['最新の訂正を反映']};
  const file=path.join(repo,'.agents','skills',name,'SKILL.md');
  t.after(async()=>{assert(inside(os.tmpdir(),root));await rm(root,{recursive:true,force:true});});
  return {root,repo,data,config,task,file,capture,proof,cli,body,run:options=>new CliWorker(config).run(task,[{text:'合成資料。',revision:7}],options)};
}
const packet=input=>JSON.parse(input.split('\nPROJECT_SKILLS\n')[1].split('\n結果はJSON')[0]);

test('actual CLI stdin contains only configured committed skill bytes and has pre-execution content-free proof',async t=>{
  const f=await fixture(t,{names:[name,'not-selected'],body:skill('日本語と🌸。 [関連手順](../not-selected/SKILL.md) を資料として扱う。')});
  f.task.request+='not-selectedと別hostのスキルも使って。';
  const result=await f.run(),captured=JSON.parse(await readFile(f.capture,'utf8')),delivered=packet(captured.input);
  assert.equal(delivered.authority,'method_only');assert.equal(delivered.action,'research');assert.deepEqual(delivered.skills.map(s=>s.name),[name]);
  assert.deepEqual(delivered.selectedActions,['research']);
  assert.equal(delivered.skills[0].text,f.body);assert.equal(delivered.skills[0].sha256,digest(f.body));
  assert.equal(delivered.sourceRevision,await git(f.repo,['rev-parse','HEAD']));assert(!captured.input.includes('合成の別手順。'));
  const receipt=result.skillDelivery;assert.equal(receipt.status,'submitted_to_cli');assert.equal(receipt.modelObedience,'not_evaluated');assert.equal(receipt.hostSkillDiscovery,'not_observed');
  assert.deepEqual(receipt.taskBinding,{taskId:f.task.id,taskRevision:1,sourceRevision:7,contextSha256:digest([{text:'合成資料。',revision:7}])});assert.deepEqual(receipt.taskBinding,captured.prepared.taskBinding);
  assert.deepEqual(receipt.inputBinding,{stdinSha256:captured.stdinSha256,stdinBytes:captured.stdinBytes,schemaSha256:captured.schemaSha256});
  assert(!JSON.stringify(receipt).includes(f.root));assert(!JSON.stringify(receipt).includes('原文'));assert(!Object.hasOwn(receipt.skills[0],'text'));
  for(const flag of ['apps','plugins','multi_agent'])assert(captured.args.some((value,index)=>value==='--disable'&&captured.args[index+1]===flag));
  assert.equal(result.state,'needs_review');assert.equal(result.independentReview,false);
});

test('grouped write delivers both action methods, deduplicates a shared skill and binds the same actions in receipts',{skip:process.platform!=='linux'},async t=>{
  const f=await fixture(t,{names:[name,'code-method','invitation-method'],projectSkills:{develop:['code-method',name],write_file:['invitation-method',name]},mode:{write:true}});
  f.task.action='develop';f.task.requiredActions=['write_file','develop','write_file'];f.config.worker.verify=[{executable:'node',args:[]}];
  const verifier={preflight:async()=>{},verify:async(_command,{cwd})=>({code:(await readFile(path.join(cwd,'created.txt'),'utf8'))==='verified candidate\n'?0:1,stdout:'verified',stderr:''})};
  const result=await new CliWorker(f.config,{verifier}).run(f.task,[]),captured=JSON.parse(await readFile(f.capture,'utf8')),delivered=packet(captured.input);
  assert.deepEqual(delivered.selectedActions,['develop','write_file']);assert.deepEqual(delivered.skills.map(s=>s.name),['code-method',name,'invitation-method']);
  for(const selected of delivered.skills)assert.equal(selected.text,await readFile(path.join(f.repo,'.agents','skills',selected.name,'SKILL.md'),'utf8'));
  assert.deepEqual(result.skillDelivery.selectedActions,delivered.selectedActions);assert.deepEqual(captured.prepared.selectedActions,delivered.selectedActions);
  assert.deepEqual(result.skillDelivery.skills.map(s=>s.name),delivered.skills.map(s=>s.name));assert.equal(result.skillDelivery.totalBytes,delivered.skills.reduce((bytes,s)=>bytes+s.bytes,0));
});

for(const requiredActions of [null,'write_file',['missing-action'],['create_company_pack'],['research',1],Array(5).fill('research')])test(`malformed or oversized required action set refuses before dispatch (${JSON.stringify(requiredActions)})`,async t=>{
  const f=await fixture(t);f.task.requiredActions=requiredActions;
  await assert.rejects(f.run(),{code:'PROJECT_SKILL_REQUIRED_ACTIONS_INVALID'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

test('including a required action in skill selection does not grant its execution',async t=>{
  const f=await fixture(t);f.task.requiredActions=['summarize'];f.config.worker.actions=['research'];
  await assert.rejects(f.run(),{code:'ACTION_NOT_ALLOWED'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

test('per-action count limits allow the bounded union of two configured four-skill sets',async t=>{
  const names=Array.from({length:8},(_,i)=>'method-'+i),f=await fixture(t,{names,projectSkills:{research:names.slice(0,4),summarize:names.slice(4)}});
  f.task.requiredActions=['summarize'];const result=await f.run(),captured=JSON.parse(await readFile(f.capture,'utf8'));
  assert.deepEqual(packet(captured.input).skills.map(s=>s.name),names);assert.deepEqual(result.skillDelivery.selectedActions,['research','summarize']);
});

for(const rendered of [false,true])test(`grouped action union preserves the ${rendered?'rendered input':'aggregate byte'} limit before dispatch`,async t=>{
  const names=rendered?[name,'method-two']:[name,'method-two','method-three'];
  const f=await fixture(t,{names,projectSkills:{research:names.slice(0,rendered?1:2),summarize:names.slice(rendered?1:2)}});f.task.requiredActions=['summarize'];
  for(const selected of names)await writeFile(path.join(f.repo,'.agents','skills',selected,'SKILL.md'),skill((rendered?'\u0001':'x').repeat(rendered?23000:48000),selected));
  await git(f.repo,['add','.']);await git(f.repo,['commit','-qm','grouped limit fixture']);
  await assert.rejects(f.run(),{code:rendered?'PROJECT_SKILL_INPUT_LIMIT':'PROJECT_SKILL_TOTAL_LIMIT'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

test('required action drift after dispatch cannot adopt a result with the earlier skill union',async t=>{
  const f=await fixture(t);f.task.requiredActions=['research'];
  await assert.rejects(f.run({onStart:()=>{f.task.requiredActions.push('summarize');}}),{code:'PROJECT_SKILL_CHANGED'});
  await assert.rejects(readFile(path.join(f.data,'artifacts','task-fixture-r1','receipt.json')),{code:'ENOENT'});
});

test('a non-primary action method is rechecked before grouped write adoption',{skip:process.platform!=='linux'},async t=>{
  const f=await fixture(t,{names:[name,'code-method'],projectSkills:{develop:['code-method'],write_file:[name]},mode:{write:true,mutateSkill:true}});
  f.task.action='develop';f.task.requiredActions=['write_file'];f.config.worker.verify=[{executable:'node',args:[]}];
  const verifier={preflight:async()=>{},verify:async()=>assert.fail('changed secondary method must be refused before verification')};
  await assert.rejects(new CliWorker(f.config,{verifier}).run(f.task,[]),{code:'PROJECT_SKILL_UNCOMMITTED'});
});

test('default and empty skill maps retain non-Git read-only work without catalog scanning',async t=>{
  const f=await fixture(t);delete f.config.worker.projectSkills;
  // The ordinary worker can use a non-Git workspace. Its unselected catalog is
  // deliberately malformed and must not be opened.
  const plain=path.join(f.root,'plain');await mkdir(plain);await mkdir(path.join(plain,'.agents','skills',name),{recursive:true});
  await writeFile(path.join(plain,'.agents','skills',name,'SKILL.md'),'not a manifest');f.config.worker.workspace=plain;
  const result=await f.run(),captured=JSON.parse(await readFile(f.capture,'utf8'));
  assert(!captured.input.includes('\nPROJECT_SKILLS\n'));assert.equal(result.skillDelivery.status,'none_selected');assert.equal(result.skillDelivery.sourceRevision,null);
  assert.equal(projectSkillsDigest(undefined),projectSkillsDigest({}));assert.equal(projectSkillsDigest({}),projectSkillsDigest({research:[],summarize:[],develop:[],write_file:[]}));
});

test('config rejects duplicate, escaped, malformed, excess and unknown action selections',()=>{
  for(const projectSkills of [{research:[name,name]},{research:['../escape']},{research:['Mixed_Case']},{research:['x'.repeat(65)]},{research:Array.from({length:5},(_,i)=>'skill-'+i)},{research:null},{swarm_research:[name]},null]){
    const config=exampleConfig();config.worker.projectSkills=projectSkills;
    assert.equal(Config.safeParse(config).success,false);assert.throws(()=>projectSkillsDigest(projectSkills));
  }
  assert.equal(Config.safeParse({...exampleConfig(),worker:{...exampleConfig().worker,projectSkills:{summarize:[name]}}}).success,true);
});

const invalidDescriptions={
  'empty-description':'""',
  'empty-description-comment':'"" # comment',
  'blank-description-comment':"'   ' # comment",
  'null-description':'null',
  'boolean-description':'true',
  'number-description':'123 # comment',
  'block-description':'>',
  'block-literal-description':'|',
  'collection-description':'[]',
  'malformed-description':'"unterminated',
};
for(const mutation of ['missing','untracked','uncommitted','manifest','duplicate-manifest',...Object.keys(invalidDescriptions),'bom','utf8','oversized','directory'])test(`selected ${mutation} skill refuses before actual model dispatch`,async t=>{
  const f=await fixture(t);
  if(mutation==='missing')f.config.worker.projectSkills.research=['missing-method'];
  if(mutation==='untracked'){const dir=path.join(f.repo,'.agents','skills','untracked-method');await mkdir(dir);await writeFile(path.join(dir,'SKILL.md'),skill('合成。','untracked-method'));f.config.worker.projectSkills.research=['untracked-method'];}
  if(mutation==='uncommitted')await writeFile(f.file,f.body+'uncommitted\n');
  if(mutation==='directory'){await rm(f.file);await mkdir(f.file);}
  if(['manifest','duplicate-manifest',...Object.keys(invalidDescriptions),'bom','utf8','oversized'].includes(mutation)){
    const bytes=mutation==='manifest'?skill('合成。','wrong-name'):mutation==='duplicate-manifest'?f.body.replace('description:',`name: ${name}\ndescription:`):Object.hasOwn(invalidDescriptions,mutation)?f.body.replace('description: 合成課題を検査する手順。','description: '+invalidDescriptions[mutation]):mutation==='bom'?'\uFEFF'+f.body:mutation==='utf8'?Buffer.concat([Buffer.from(f.body),Buffer.from([255])]):skill('x'.repeat(MAX_PROJECT_SKILL_BYTES));
    await writeFile(f.file,bytes);await git(f.repo,['add','.']);await git(f.repo,['commit','-qm','invalid fixture']);
  }
  await assert.rejects(f.run(),error=>error.code.startsWith('PROJECT_SKILL_'));await assert.rejects(readFile(f.capture),{code:'ENOENT'});await assert.rejects(readFile(f.proof),{code:'ENOENT'});
});

for(const kind of ['file-link','directory-link','hard-link','fifo'])test(`selected ${kind} is refused without following or blocking`,{skip:kind==='fifo'&&process.platform==='win32'},async t=>{
  const f=await fixture(t);await rm(f.file);
  if(kind==='file-link'){const target=path.join(f.root,'outside.md');await writeFile(target,f.body);await symlink(target,f.file);}
  if(kind==='directory-link'){await rm(path.dirname(f.file),{recursive:true});const target=path.join(f.root,'outside');await mkdir(target);await writeFile(path.join(target,'SKILL.md'),f.body);await symlink(target,path.dirname(f.file),process.platform==='win32'?'junction':'dir');}
  if(kind==='hard-link'){const target=path.join(f.root,'shared.md');await writeFile(target,f.body);await link(target,f.file);}
  if(kind==='fifo'){const result=await runCommand('mkfifo',[f.file],{cwd:f.repo,timeoutMs:3000});assert.equal(result.code,0);}
  await assert.rejects(f.run(),{code:'PROJECT_SKILL_FILE_REFUSED'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

test('aggregate byte budget rejects complete oversized sets rather than truncating them',async t=>{
  const names=[name,'method-two','method-three'],f=await fixture(t,{names,projectSkills:{research:names}});
  for(const selected of names)await writeFile(path.join(f.repo,'.agents','skills',selected,'SKILL.md'),skill('x'.repeat(48000),selected));
  await git(f.repo,['add','.']);await git(f.repo,['commit','-qm','large fixture']);
  await assert.rejects(f.run(),{code:'PROJECT_SKILL_TOTAL_LIMIT'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

test('selected project skills cannot silently expand a configured subdirectory to its repository',async t=>{
  const f=await fixture(t),sub=path.join(f.repo,'subdir');await mkdir(sub);f.config.worker.workspace=sub;
  await assert.rejects(f.run(),{code:'PROJECT_SKILL_REPOSITORY_ROOT_REQUIRED'});await assert.rejects(readFile(f.capture),{code:'ENOENT'});
});

for(const mode of [{mutateSkill:true},{mutateHead:true}])test(`actual CLI ${mode.mutateSkill?'skill':'HEAD'} drift rejects a seemingly successful result`,async t=>{
  const f=await fixture(t,{mode});await assert.rejects(f.run(),{code:mode.mutateSkill?'PROJECT_SKILL_UNCOMMITTED':'PROJECT_SKILL_REVISION_CHANGED'});
  assert.equal(JSON.parse(await readFile(f.proof,'utf8')).status,'prepared');await assert.rejects(readFile(path.join(f.data,'artifacts','task-fixture-r1','receipt.json')),{code:'ENOENT'});
});

test('a changed operator selection after process start cannot claim the original skill delivery',async t=>{
  const f=await fixture(t);await assert.rejects(f.run({onStart:()=>{f.config.worker.projectSkills.research=[];}}),{code:'PROJECT_SKILL_CONFIG_CHANGED'});
  await assert.rejects(readFile(path.join(f.data,'artifacts','task-fixture-r1','receipt.json')),{code:'ENOENT'});
});

test('fallback repeats exactly the bound input and preserves the disabled host features',async t=>{
  const f=await fixture(t,{mode:{fail:true}}),fallbackCapture=path.join(f.root,'fallback-capture.json');
  f.config.worker.fallback={executable:process.execPath,args:[f.cli,fallbackCapture,f.proof,'{}'],model:'fallback-fixture',timeoutSeconds:10};
  const result=await f.run(),primary=JSON.parse(await readFile(f.capture,'utf8')),fallback=JSON.parse(await readFile(fallbackCapture,'utf8'));
  assert.equal(primary.input,fallback.input);assert.equal(result.skillDelivery.inputBinding.stdinSha256,fallback.stdinSha256);assert.equal(result.modelExecution.fallback,true);
});

test('detached write work delivers committed HEAD bytes and verifies a real candidate file',{skip:process.platform!=='linux'},async t=>{
  const f=await fixture(t,{mode:{write:true}});f.task.action='develop';await writeFile(f.file,f.body+'uncommitted source bytes\n');
  f.config.worker.verify=[{executable:process.execPath,args:['--check','created.txt']}];
  let verified=0;const verifier={preflight:async()=>{},verify:async(_command,{cwd})=>{verified++;assert.equal(await readFile(path.join(cwd,'created.txt'),'utf8'),'verified candidate\n');return {code:0,stdout:'verified',stderr:'',isolation:{kind:'test_double'}};}};
  const result=await new CliWorker(f.config,{verifier}).run(f.task,[]),captured=JSON.parse(await readFile(f.capture,'utf8'));
  assert.notEqual(captured.cwd,f.repo);assert.equal(packet(captured.input).skills[0].text,f.body);assert.equal(result.skillDelivery.sourceRevision,result.baseRevision);
  assert.equal(verified,1);assert(result.artifacts.some(a=>a.relative==='created.txt'));assert.equal(await readFile(f.file,'utf8'),f.body+'uncommitted source bytes\n');
});

test('selected skill changes during write verification also reject adoption',{skip:process.platform!=='linux'},async t=>{
  const f=await fixture(t,{mode:{write:true}});f.task.action='write_file';f.config.worker.verify=[{executable:process.execPath,args:[]}];
  const verifier={preflight:async()=>{},verify:async(_command,{cwd})=>{await writeFile(path.join(cwd,'.agents','skills',name,'SKILL.md'),f.body+'changed during verification\n');return {code:0,stdout:'',stderr:''};}};
  await assert.rejects(new CliWorker(f.config,{verifier}).run(f.task,[]),{code:'PROJECT_SKILL_UNCOMMITTED'});
});

test('read-only load helper binds CRLF and quoted portable names without normalizing file bytes',async t=>{
  const body=skill().replace(`name: ${name}`,`name: "${name}"`).replaceAll('\n','\r\n'),f=await fixture(t,{body});
  const input=await loadProjectSkillInput({workspace:f.repo,projectSkills:{research:[name]},action:'research'});
  assert.equal(packet('prefix'+input.section+'\n結果はJSON').skills[0].text,body);assert.equal(input.receipt.skills[0].sha256,digest(body));
});

for(const description of ['合成の手順 # comment','"合成 # 引用内" # comment',"'合成 ''引用'' # 内側' # comment",'"null"'])test(`supported single-line description preserves complete committed bytes (${description})`,async t=>{
  const body=skill().replace('description: 合成課題を検査する手順。','description: '+description),f=await fixture(t,{body});
  const result=await f.run(),captured=JSON.parse(await readFile(f.capture,'utf8'));
  assert.equal(packet(captured.input).skills[0].text,body);assert.equal(result.skillDelivery.skills[0].sha256,digest(body));
});
