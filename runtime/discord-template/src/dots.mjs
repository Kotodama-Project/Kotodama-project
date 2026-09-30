import {z} from 'zod';
import {check,digest,uid,errorCode} from './common.mjs';

export const lumaEventSchema=z.object({
  name:z.string().trim().min(1).max(150),description_md:z.string().max(12000),
  start_at:z.string().datetime({offset:true}),end_at:z.string().datetime({offset:true}),
  timezone:z.string().min(1).max(80),visibility:z.enum(['private','public']).default('private'),
  location:z.string().trim().min(1).max(500),location_visibility:z.enum(['guests-only','public']).default('guests-only'),
  max_capacity:z.number().int().min(1).max(10000),require_approval:z.boolean().default(true),
}).strict().superRefine((event,ctx)=>{
  if(Date.parse(event.end_at)<=Date.parse(event.start_at))ctx.addIssue({code:'custom',message:'LUMA_END_BEFORE_START'});
  try{new Intl.DateTimeFormat('ja-JP',{timeZone:event.timezone});}catch{ctx.addIssue({code:'custom',message:'LUMA_TIMEZONE_INVALID'});}
});
function eventUrl(value){check(typeof value==='string'&&value.length<=1000,'LUMA_EVENT_URL_INVALID');const parsed=new URL(value);check(parsed.protocol==='https:'&&['luma.com','lu.ma'].includes(parsed.hostname)&&!parsed.username&&!parsed.password&&!parsed.search&&!parsed.hash&&parsed.pathname.length>1,'LUMA_EVENT_URL_INVALID');return parsed.href;}

// These tables are transport receipts, not a second Task owner.
export class DotsBridge {
  constructor({config,store,policy=()=>config,authorize=async()=>{},deliver,now=()=>Date.now()}){
    Object.assign(this,{config,store,policy,authorize,deliver,now});this.inFlight=new Set();
    store.db.exec(`
      CREATE TABLE IF NOT EXISTS dot_requests(id TEXT PRIMARY KEY,source_key TEXT NOT NULL,source_revision INTEGER NOT NULL,actor TEXT NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL,response_digest TEXT,message_id TEXT);
      CREATE TABLE IF NOT EXISTS dot_event_drafts(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,revision INTEGER NOT NULL,event TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,operation TEXT NOT NULL,target_url TEXT,approved_at INTEGER,claim_id TEXT,review_message_id TEXT,reported TEXT);
    `);
    // A interrupted send may already have reached Discord; never replay it.
    store.db.prepare("UPDATE dot_requests SET state='unknown' WHERE state='sending'").run();
    store.db.prepare("UPDATE dot_event_drafts SET state='uncertain' WHERE state='executing'").run();
    this.prune();
  }
  settings(){const config=this.policy(),dots=config.dots;check(dots?.enabled,'DOTS_DISABLED');check(dots.actorId===this.config.dots.actorId&&dots.actorId&&config.discord.operators.includes(dots.actorId),'DOTS_OWNER_CHANGED');return {config,dots};}
  snapshot(id,{reconcile=false}={}){
    const {config,dots}=this.settings();
    const row=this.store.db.prepare('SELECT * FROM dot_requests WHERE id=?').get(id);check(row&&row.actor===dots.actorId,'DOTS_REQUEST_NOT_FOUND');
    const source=this.store.source(row.source_key,row.actor);check(source.revision===row.source_revision,'DOTS_SOURCE_CHANGED');
    check(source.provider==='discord'&&source.guildId===config.discord.guildId&&dots.channelIds.includes(source.channelId),'DOTS_SOURCE_SCOPE_CHANGED');
    check(this.now()>=row.created&&(reconcile||this.now()-row.created<=dots.requestTtlSeconds*1000),'DOTS_REQUEST_EXPIRED');return {row,source};
  }
  async current(id,options){const initial=this.snapshot(id,options);await this.authorize(initial.source);return this.snapshot(id,options);}
  prune(){
    if(this.lastPrunedAt!==undefined&&this.now()>=this.lastPrunedAt&&this.now()-this.lastPrunedAt<60000)return 0;
    const days=this.policy().dots?.draftRetentionDays??7,cutoff=this.now()-days*86400000;this.lastPrunedAt=this.now();
    return this.store.db.prepare("UPDATE dot_event_drafts SET event='{}',target_url=NULL,reported=NULL,state='expired' WHERE state<>'expired' AND request_id IN (SELECT id FROM dot_requests WHERE created<?)").run(cutoff).changes;
  }
  enqueue(source){
    const {config,dots}=this.settings();check(source.actorId===dots.actorId&&source.provider==='discord'&&source.guildId===config.discord.guildId&&dots.channelIds.includes(source.channelId),'DOTS_ACTOR_REQUIRED');
    check(source.final&&!source.withdrawn&&source.readers.includes(source.actorId),'FINAL_AUTHENTICATED_SOURCE_REQUIRED');
    check(source.text.trim()&&source.text.length<=16000,'DOTS_REQUEST_SIZE');
    const {key,revision}=this.store.ingest(source);check(revision===source.revision,'DOTS_SOURCE_CHANGED');const id='dot_'+digest([key,source.revision]).slice(0,24);
    const old=this.store.db.prepare('SELECT id FROM dot_requests WHERE id=?').get(id);
    if(!old)check(this.store.db.prepare("SELECT count(*) AS n FROM dot_requests WHERE state='pending'").get().n<100,'DOTS_INBOX_FULL');
    const inserted=this.store.db.prepare("INSERT OR IGNORE INTO dot_requests(id,source_key,source_revision,actor,state,created) VALUES(?,?,?,?,'pending',?)").run(id,key,source.revision,source.actorId,this.now());
    return {id,revision:source.revision,state:this.store.db.prepare('SELECT state FROM dot_requests WHERE id=?').get(id).state,created:inserted.changes===1};
  }
  async list(){
    const {dots}=this.settings();this.prune();const result=[];let unavailable=0,checked=0;
    const rows=this.store.db.prepare("SELECT id FROM dot_requests WHERE actor=? AND state='pending' ORDER BY created LIMIT 100").all(dots.actorId);
    for(const {id} of rows){checked++;try{const {row,source}=await this.current(id);result.push({id,revision:row.source_revision,text:source.text,channelId:source.channelId,createdAt:new Date(row.created).toISOString(),authority:'conversation_and_event_draft_only'});if(result.length===10)break;}catch(e){if(['DOTS_SOURCE_CHANGED','DOTS_SOURCE_SCOPE_CHANGED','DOTS_REQUEST_EXPIRED','SOURCE_ACCESS_DENIED','SOURCE_NOT_FOUND'].includes(errorCode(e)))this.store.db.prepare("UPDATE dot_requests SET state='stale' WHERE id=? AND state='pending'").run(id);else unavailable++;}}
    return {requests:result,complete:unavailable===0&&checked===rows.length,unavailable,uninspected:rows.length-checked,taskOwnerUnchanged:true};
  }
  async send(id,revision,text){
    check(typeof text==='string'&&text.trim()&&text.length<=1900,'DOTS_REPLY_SIZE');const bodyDigest=digest(text);
    const {row,source}=await this.current(id);check(row.source_revision===revision,'DOTS_SOURCE_CHANGED');
    if(row.state==='sent'){check(row.response_digest===bodyDigest,'DOTS_REPLY_CHANGED');return {state:'already_sent',messageId:row.message_id};}
    check(row.state==='pending'&&!this.inFlight.has(id),'DOTS_DELIVERY_UNCERTAIN');this.inFlight.add(id);
    try{
      await this.current(id);const changed=this.store.db.prepare("UPDATE dot_requests SET state='sending',response_digest=? WHERE id=? AND state='pending'").run(bodyDigest,id);check(changed.changes===1,'DOTS_DELIVERY_UNCERTAIN');
      let message;try{message=await this.deliver(source,{content:text,allowedMentions:{parse:[]}},{beforeSend:()=>{const fresh=this.snapshot(id);check(fresh.row.source_revision===revision&&fresh.row.state==='sending'&&fresh.row.response_digest===bodyDigest,'DOTS_DELIVERY_BINDING_CHANGED');}});check(message?.id,'DOTS_SEND_UNCONFIRMED');}catch{this.store.db.prepare("UPDATE dot_requests SET state='unknown' WHERE id=? AND state='sending'").run(id);return {state:'unknown',retryAllowed:false};}
      this.store.db.prepare("UPDATE dot_requests SET state='sent',message_id=? WHERE id=? AND state='sending'").run(message.id,id);return {state:'sent',messageId:message.id};
    }finally{this.inFlight.delete(id);}
  }
  async cancel(id,actor){const {row}=await this.current(id);check(actor===row.actor,'DOTS_ACTOR_REQUIRED');check(!this.inFlight.has(id)&&row.state==='pending','DOTS_DELIVERY_UNCERTAIN');this.store.db.prepare("UPDATE dot_requests SET state='cancelled' WHERE id=? AND state='pending'").run(id);return {state:'cancelled',delegatedWorkStopped:false};}
  async prepareEvent(id,revision,event,{operation='create',targetUrl}={}){
    const {row,source}=await this.current(id);check(row.source_revision===revision&&row.state==='pending','DOTS_SOURCE_CHANGED');const parsed=lumaEventSchema.parse(event);
    check(['create','update'].includes(operation),'LUMA_OPERATION_INVALID');check(operation==='update'?Boolean(targetUrl):!targetUrl,'LUMA_TARGET_REQUIRED');const target=targetUrl?eventUrl(targetUrl):null;
    check(!this.store.db.prepare("SELECT id FROM dot_event_drafts WHERE request_id=? AND state IN ('executing','uncertain','reported')").get(id),'LUMA_OPERATION_ALREADY_STARTED');
    check(Date.parse(parsed.start_at)>this.now(),'LUMA_START_IN_PAST');const eventDigest=digest({operation,targetUrl:target,event:parsed}),draftId='luma_'+digest([id,revision,eventDigest]).slice(0,24);
    const old=this.store.db.prepare('SELECT * FROM dot_event_drafts WHERE id=?').get(draftId);if(old){check(old.state!=='superseded','LUMA_DRAFT_SUPERSEDED');return this.draft(draftId);}
    this.store.db.prepare("UPDATE dot_event_drafts SET state='superseded' WHERE request_id=? AND state IN ('needs_review','approved')").run(id);
    this.store.db.prepare("INSERT INTO dot_event_drafts(id,request_id,revision,event,digest,state,operation,target_url) VALUES(?,?,?,?,?,'needs_review',?,?)").run(draftId,id,revision,JSON.stringify(parsed),eventDigest,operation,target);
    let message;try{message=await this.deliver(source,this.reviewMessage(this.draft(draftId)),{purpose:'event_review',beforeSend:()=>{const fresh=this.snapshot(id),draft=this.draft(draftId);check(fresh.row.source_revision===revision&&fresh.row.state==='pending'&&draft.state==='needs_review','LUMA_APPROVAL_BINDING_CHANGED');}});}catch{}
    this.store.db.prepare('UPDATE dot_event_drafts SET review_message_id=? WHERE id=?').run(message?.id??null,draftId);
    return {...this.draft(draftId),providerOperationPerformed:false};
  }
  draft(id){const row=this.store.db.prepare('SELECT * FROM dot_event_drafts WHERE id=?').get(id);check(row,'LUMA_DRAFT_NOT_FOUND');check(row.state!=='expired'&&row.event!==null,'LUMA_DRAFT_CONTENT_EXPIRED');return {id:row.id,requestId:row.request_id,revision:row.revision,event:JSON.parse(row.event),digest:row.digest,operation:row.operation,targetUrl:row.target_url,state:row.state,approvedAt:row.approved_at,claimId:row.claim_id,reviewDelivery:row.review_message_id?'sent':'unknown',reported:row.reported?JSON.parse(row.reported):null};}
  async readDraft(id){const draft=this.draft(id),reconcile=Boolean(draft.claimId)&&['executing','uncertain','reported'].includes(draft.state),{row}=await this.current(draft.requestId,{reconcile});check(draft.revision===row.source_revision,'DOTS_SOURCE_CHANGED');return this.draft(id);}
  reviewMessage(draft){return {content:eventPreview(draft),files:[{attachment:Buffer.from(eventDetails(draft),'utf8'),name:'luma-event.txt'},{attachment:Buffer.from(JSON.stringify({operation:draft.operation,targetUrl:draft.targetUrl,event:draft.event},null,2),'utf8'),name:'luma-event.json'}],components:[{type:1,components:[{type:2,style:1,label:'この内容でLuma操作を許可',custom_id:'kotodama-luma:'+draft.id+':'+draft.digest.slice(0,16)}]}],allowedMentions:{parse:[]}};}
  async approve(id,prefix,actor){
    const draft=this.draft(id),{row}=await this.current(draft.requestId);check(actor===row.actor&&draft.revision===row.source_revision&&draft.digest.slice(0,16)===prefix,'LUMA_APPROVAL_BINDING_CHANGED');
    const expiredApproval=draft.state==='approved'&&(this.now()<draft.approvedAt||this.now()-draft.approvedAt>300000);
    check(draft.state==='needs_review'||expiredApproval,'LUMA_DRAFT_ALREADY_DECIDED');check(row.state==='pending'&&this.snapshot(draft.requestId).row.state==='pending','DOTS_REQUEST_NOT_PENDING');
    const changed=this.store.db.prepare("UPDATE dot_event_drafts SET state='approved',approved_at=? WHERE id=? AND state=? AND approved_at IS ?").run(this.now(),id,draft.state,draft.approvedAt);check(changed.changes===1,'LUMA_DRAFT_ALREADY_DECIDED');return this.draft(id);
  }
  async approvedEvent(id){
    const draft=this.draft(id),{row}=await this.current(draft.requestId);check(draft.state==='approved'&&draft.revision===row.source_revision&&row.state==='pending','LUMA_APPROVAL_REQUIRED');
    check(this.now()>=draft.approvedAt&&this.now()-draft.approvedAt<=300000,'LUMA_APPROVAL_EXPIRED');return {...draft,action:draft.operation+'_event_once',executionRoute:'connected_luma_plugin_or_official_browser',invitesAllowed:false,paidTicketsAllowed:false};
  }
  async claimEvent(id){const draft=await this.approvedEvent(id),claimId=uid('luma');check(this.snapshot(draft.requestId).row.state==='pending','DOTS_REQUEST_NOT_PENDING');const changed=this.store.db.prepare("UPDATE dot_event_drafts SET state='executing',claim_id=? WHERE id=? AND state='approved' AND approved_at=?").run(claimId,id,draft.approvedAt);check(changed.changes===1,'LUMA_OPERATION_ALREADY_STARTED');return {...draft,state:'executing',claimId};}
  async recordEvent(id,claimId,url,observed){
    const draft=await this.readDraft(id);check(['executing','uncertain','reported'].includes(draft.state)&&draft.claimId===claimId,'LUMA_EXECUTION_BINDING_CHANGED');const target=eventUrl(url);check(draft.operation!=='update'||target===draft.targetUrl,'LUMA_TARGET_CHANGED');
    check(digest({operation:draft.operation,targetUrl:draft.targetUrl,event:lumaEventSchema.parse(observed)})===draft.digest,'LUMA_READBACK_CHANGED');
    const reported={url:target,observedAt:new Date(this.now()).toISOString(),evidence:'DOT_REPORTED_NOT_INDEPENDENTLY_VERIFIED'};
    if(draft.reported){check(draft.reported.url===reported.url,'LUMA_READBACK_CHANGED');return {state:'reported',...draft.reported};}
    this.store.db.prepare("UPDATE dot_event_drafts SET state='reported',reported=? WHERE id=? AND state IN ('executing','uncertain')").run(JSON.stringify(reported),id);return {state:'reported',...reported};
  }
}

export function eventPreview(draft){
  const preview={...draft,targetUrl:draft.targetUrl?.slice(0,120),event:{...draft.event,location:draft.event.location.slice(0,160),description_md:draft.event.description_md.slice(0,400)}};
  return eventDetails(preview)+'\n\n添付luma-event.txtに対象と説明の全文があります。全文を確認してからbuttonを押してください。有料チケット・招待は含みません。許可は5分間有効です。';
}
export function eventDetails(draft){const e=draft.event;return `Lumaイベントの内容確認\n操作: ${draft.operation==='update'?'既存イベントの更新':'新規作成'}${draft.targetUrl?'\n対象: '+draft.targetUrl:''}\n${e.name}\n開始: ${e.start_at}\n終了: ${e.end_at}\nタイムゾーン: ${e.timezone}\n場所: ${e.location}\n場所の公開: ${e.location_visibility==='guests-only'?'承認済み参加者のみ':'一般公開'}\n公開範囲: ${e.visibility==='private'?'非公開':'公開'}\n定員: ${e.max_capacity}\n参加承認: ${e.require_approval?'必要':'不要'}\n説明:\n${e.description_md}`;}
