// Conversation-only state in the existing local event/intent store. No Task owner.
const roomOf=source=>`${source.provider}:${source.guildId}:${source.channelId}`;
const eventTypes="('interaction.clarification_asked','interaction.clarification_closed')";

export class InteractionState {
  constructor(store){this.store=store;}
  last(source){
    if(!source.actorId)return null;
    const row=this.store.statement(`SELECT seq,body FROM events WHERE type IN ${eventTypes} AND json_extract(body,'$.room')=? AND json_extract(body,'$.actor')=? ORDER BY seq DESC LIMIT 1`).get(roomOf(source),source.actorId);
    return row?{...JSON.parse(row.body),sequence:row.seq}:null;
  }
  snapshot(source,windowSeconds=600,now=Date.now()){
    const state=this.last(source);if(!state)return null;
    if(state.phase==='closed')return state.session_id&&state.session_id===source.metadata?.sessionId?{...state,phase:'ended'}:null;
    if(now>=state.asked_at+Math.min(state.window_ms,windowSeconds*1000))return null;
    return now<state.asked_at?{...state,phase:'held'}:state;
  }
  pending(source,windowSeconds){
    const state=this.snapshot(source,windowSeconds);
    if(state?.phase!=='pending'||state.source_key===source.key)return null;
    try{
      const original=this.store.source(state.source_key,source.actorId);
      if(original.revision!==state.source_revision||original.actorId!==source.actorId)return null;
      const row=this.store.statement('SELECT revision,body FROM intents WHERE id=?').get(state.intent_id);
      if(!row||row.revision!==state.source_revision)return null;
      const intent=JSON.parse(row.body),question=intent.clarification_question;
      if(typeof question!=='string'||!question.trim()||question.length>300)return null;
      const bindings=intent.contextSources??[{key:original.key,revision:original.revision}];
      for(const binding of bindings)if(this.store.source(binding.key,source.actorId).revision!==binding.revision)return null;
      return {sequence:state.sequence,bindings,context:{question,intentId:state.intent_id,sourceKey:state.source_key,sourceRevision:state.source_revision}};
    }catch{return null;}
  }
  consume(source,sequence,windowSeconds){
    return this.store.transaction(()=>{
      const state=this.snapshot(source,windowSeconds);
      if(state?.phase!=='pending'||state.sequence!==sequence||state.source_key===source.key)return false;
      const {sequence:unused,...body}=state;
      this.store.event('interaction.clarification_closed',{...body,phase:'answered',answer_key:source.key,reason:'next_source'});
      return true;
    });
  }
  claim(source,intentId,windowSeconds=600,now=Date.now()){
    return this.store.transaction(()=>{
      if(!source.actorId||this.snapshot(source,windowSeconds,now))return false;
      const latest=this.store.source(source.key,source.actorId);if(latest.revision!==source.revision)return false;
      this.store.event('interaction.clarification_asked',{room:roomOf(source),actor:source.actorId,phase:'pending',source_key:source.key,source_revision:source.revision,intent_id:intentId,session_id:source.metadata?.sessionId??null,asked_at:now,window_ms:windowSeconds*1000});
      return true;
    });
  }
  close(source,reason){
    if(!source.actorId)return;
    const last=this.last(source),sessionId=source.metadata?.sessionId??null;
    if(reason==='voice_end'&&last?.session_id&&sessionId!==last.session_id&&last.phase!=='closed')return;
    this.store.event('interaction.clarification_closed',{room:roomOf(source),actor:source.actorId,phase:'closed',session_id:sessionId,reason});
  }
  decision(source,intentId,route){
    this.store.event('interaction.decision',{room:roomOf(source),actor:source.actorId??null,source_key:source.key,source_revision:source.revision,intent_id:intentId,route});
  }
}
