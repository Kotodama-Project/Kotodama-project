import {parse} from 'csv-parse/sync';
import {check,digest} from './common.mjs';

const normalized=k=>k.toLowerCase().replace(/[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]/g,'');
const pick=(row,names)=>{for(const name of names){const key=Object.keys(row).find(k=>normalized(k)===normalized(name));if(key!==undefined)return String(row[key]??'').trim();}return '';};
export function parseLumaCsv(csv,{eventRef}){
  check(typeof csv==='string'&&Buffer.byteLength(csv)<=2000000,'CSV_SIZE_LIMIT');check(typeof eventRef==='string'&&eventRef.length>0,'EVENT_REF_REQUIRED');
  const rows=parse(csv,{columns:true,bom:true,skip_empty_lines:true,max_record_size:50000});check(rows.length<=10000,'CSV_ROW_LIMIT');
  const people=new Set(),tickets=new Set(),statusCounts={},records=[];let unknownPeople=0,unkeyedTickets=0;
  for(const row of rows){
    const email=pick(row,['email','email address','メールアドレス']).toLowerCase();
    const guest=pick(row,['guest id','guest api id','guest api_id','guest key','api_id']);
    const ticket=pick(row,['ticket id','ticket key','ticket api_id','qr code url']);
    const status=pick(row,['approval status','approval_status','status','承認ステータス'])||'unknown';
    const personKey=guest||email?digest([eventRef,guest||email]):null;
    if(personKey)people.add(personKey);else unknownPeople++;
    if(ticket)tickets.add(digest([eventRef,ticket]));else unkeyedTickets++;
    statusCounts[status]=(statusCounts[status]??0)+1;
    records.push({personKey,ticketKey:ticket?digest([eventRef,ticket]):null,status,checkedIn:Boolean(pick(row,['checked in at','checked_in_at','check-in time','チェックイン時刻']))});
  }
  return {eventRef,sourceDigest:digest(csv),rows:rows.length,identifiedPeople:people.size,rowsWithoutPersonIdentity:unknownPeople,identifiedTickets:tickets.size,rowsWithoutTicketIdentity:unkeyedTickets,statusCounts,records};
}
export function lumaSummary(data){return `イベント ${data.eventRef}\n取込行数: ${data.rows}\n識別できた参加者: ${data.identifiedPeople}\n識別できたチケット: ${data.identifiedTickets}\n参加者を識別できない行: ${data.rowsWithoutPersonIdentity}\nチケットIDのない行: ${data.rowsWithoutTicketIdentity}\n申込状態（行単位）: ${JSON.stringify(data.statusCounts)}\n人数とチケット数は別集計です。CSV取得後の変更は含みません。`;}
export function lumaSource(data,{guildId,channelId,actorId,readers,revision=Date.now()}){
  return {provider:'luma',guildId,channelId,sourceId:`${data.eventRef}:guest-snapshot`,actorId,readers,revision,final:true,text:lumaSummary(data),metadata:{eventRef:data.eventRef,sourceDigest:data.sourceDigest,kind:'guest_snapshot',imported:true,records:data.records}};
}
export function parseIcs(text){
  check(typeof text==='string'&&text.startsWith('BEGIN:VCALENDAR')&&Buffer.byteLength(text)<=2000000,'ICS_INVALID');
  const lines=text.replace(/\r?\n[ \t]/g,'').split(/\r?\n/);const events=[];let current=null;
  for(const line of lines){if(line==='BEGIN:VEVENT')current={};else if(line==='END:VEVENT'){if(current?.UID)events.push(current);current=null;}else if(current){const colon=line.indexOf(':');if(colon>0){const field=line.slice(0,colon).split(';')[0];if(['UID','SUMMARY','DTSTART','DTEND','URL','LOCATION','LAST-MODIFIED','SEQUENCE','STATUS'].includes(field))current[field]=line.slice(colon+1).replace(/\\n/gi,'\n').replace(/\\([,;\\])/g,'$1');}}}
  return events;
}
