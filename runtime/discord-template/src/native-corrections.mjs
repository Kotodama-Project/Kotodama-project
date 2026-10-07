import {MessageFlags} from 'discord.js';
import {check,errorCode,shortText} from './common.mjs';

export function correctionId({task,source},kind='edit'){
  const value=`kc:${kind}:${task.id}:${task.revision.toString(36)}:${source.revision.toString(36)}`;check(value.length<=100,'CORRECTION_ID_INVALID');return value;
}
export function parseCorrectionId(value,kind){
  const match=/^kc:(edit|submit):([A-Za-z0-9_-]{1,64}):([a-z0-9]+):([a-z0-9]+)$/.exec(value??'');check(match&&match[1]===kind&&value.length<=100,'CORRECTION_ID_INVALID');
  const taskRevision=parseInt(match[3],36),sourceRevision=parseInt(match[4],36);check(Number.isSafeInteger(taskRevision)&&taskRevision>0&&Number.isSafeInteger(sourceRevision)&&sourceRevision>=0,'CORRECTION_ID_INVALID');return {id:match[2],taskRevision,sourceRevision};
}
export function correctionModal(target){
  const {task,source}=target;check(source.text.length<=4000&&task.title.length<=120&&task.acceptance.join('\n').length<=4000,'CORRECTION_TOO_LARGE_FOR_MODAL');
  const field=(id,label,value,style,max,required=true)=>({type:18,label,component:{type:4,custom_id:id,style,value,max_length:max,required}});
  return {custom_id:correctionId(target,'submit'),title:'依頼を訂正して実行',components:[
    field('title','件名',task.title,1,120),field('request','元の依頼（訂正後）',source.text,2,4000),field('acceptance','できたと判断する条件（1行ずつ）',task.acceptance.join('\n'),2,4000,false)
  ]};
}
const notice=error=>error.code==='TASK_CORRECTION_BUSY'?'関連する仕事の処理が終わってから訂正してください。実行中なら停止し、終了を確認してください。':['SOURCE_CHANGED','TASK_CHANGED'].includes(error.code)?'内容が更新されています。仕事の一覧を開き直してから訂正してください。':`訂正できませんでした：${errorCode(error)}`;

export class NativeCorrections {
  constructor(adapter){this.adapter=adapter;}
  owns(i){return (i.isButton?.()||i.isStringSelectMenu?.()||i.isModalSubmit?.())&&i.customId?.startsWith('kc:');}
  async target(id,actor,expected={}){return this.adapter.pipeline.correctionTarget(id,actor,expected);}
  async buttons(id,actor,revision){
    if(!Number.isSafeInteger(revision)||revision<1)return [];
    try{const target=await this.target(id,actor,{taskRevision:revision});return [{type:1,components:[{type:2,style:2,label:'依頼を訂正',custom_id:correctionId(target)}]}];}catch{return [];}
  }
  async menu(tasks,actor){
    const options=[];for(const task of tasks.slice(0,15))try{const target=await this.target(task.id,actor,{taskRevision:task.revision});options.push({label:shortText(target.task.title,100),value:correctionId(target)});}catch{}
    return options.length?[{type:1,components:[{type:3,custom_id:'kc:select',placeholder:'訂正する仕事を選ぶ',min_values:1,max_values:1,options}]}]:[];
  }
  async handle(i){
    const adapter=this.adapter;
    try{
      check(adapter.verifiedInstallation&&i.guildId===adapter.policy().discord.guildId,'SOURCE_ACCESS_DENIED');adapter.operator(i.user.id);await adapter.member(i.user.id);
      if(i.isModalSubmit?.()){
        await i.deferReply({flags:MessageFlags.Ephemeral});const {id,...expected}=parseCorrectionId(i.customId,'submit');
        const acceptance=i.fields.getTextInputValue('acceptance').split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
        const task=await adapter.pipeline.correctTask(id,i.user.id,{...expected,title:i.fields.getTextInputValue('title').trim(),request:i.fields.getTextInputValue('request').trim(),acceptance,interactionId:i.id,at:i.createdTimestamp});
        await i.editReply({content:`訂正を同じ仕事へ反映しました。\n${task.id}\n結果は「result」で確認できます。`,components:[],allowedMentions:{parse:[]}});return;
      }
      const value=i.isStringSelectMenu?.()?(check(i.customId==='kc:select'&&i.values?.length===1,'CORRECTION_ID_INVALID'),i.values[0]):i.customId;
      const {id,...expected}=parseCorrectionId(value,'edit'),target=await this.target(id,i.user.id,expected);
      const current=adapter.pipeline.currentCorrectionTarget(id,i.user.id,{taskRevision:target.task.revision,sourceRevision:target.source.revision});
      await i.showModal(correctionModal(current));
    }catch(error){const body={content:notice(error),allowedMentions:{parse:[]}};if(i.deferred)await i.editReply({...body,components:[]});else if(!i.replied)await i.reply({...body,flags:MessageFlags.Ephemeral});}
  }
}
