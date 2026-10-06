import {uid} from './common.mjs';

export const ROTATION_MS=900000;
const MAX_TURNS=1024,MAX_SEGMENTS=4;
const scope=config=>JSON.stringify([config.discord.guildId,config.discord.voiceChannelId,config.voice.rotation]);

// Owns interval metadata only. Transcript Sources and their revisions stay in Store.
export class VoiceRotation {
  constructor({store,config,policy=()=>config,deliver,now=()=>Date.now(),onError=()=>{}}){
    Object.assign(this,{store,config,policy,deliver,now,onError});this.boundScope=scope(config);
    this.periods=new Map();this.turns=new Map();this.inflight=new Set();this.started=false;this.stopped=false;
  }
  start({timer=true}={}){
    if(this.started||!this.config.voice.rotation?.enabled)return;
    this.started=true;
    this.store.db.exec(`CREATE TABLE IF NOT EXISTS voice_rotations(id TEXT PRIMARY KEY,guild TEXT NOT NULL,channel TEXT NOT NULL,target TEXT NOT NULL,started_ms INTEGER NOT NULL,ended_ms INTEGER,state TEXT NOT NULL,source_count INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS voice_rotations_room ON voice_rotations(guild,channel,state);`);
    this.store.statement("UPDATE voice_rotations SET state='interrupted' WHERE guild=? AND channel=? AND state IN ('open','sealed','posting')").run(this.config.discord.guildId,this.config.discord.voiceChannelId);
    this.open(this.now());
    if(timer){this.timer=setInterval(()=>{try{this.tick();}catch{this.halt();this.onError('VOICE_ROTATION_FAILED');}},1000);this.timer.unref();}
  }
  open(at){
    if(this.periods.size>=MAX_SEGMENTS){this.halt();this.onError('VOICE_ROTATION_BACKLOG_LIMIT');return;}
    const period={id:uid('voice-rotation'),guildId:this.config.discord.guildId,channelId:this.config.discord.voiceChannelId,
      targetChannelId:this.config.voice.rotation.channelId,startedAt:at,endedAt:null,state:'open',entries:[],pending:new Set(),overflow:false,count:0};
    this.store.statement('INSERT INTO voice_rotations(id,guild,channel,target,started_ms,state) VALUES(?,?,?,?,?,?)').run(period.id,period.guildId,period.channelId,period.targetChannelId,at,'open');
    this.periods.set(period.id,period);this.current=period;
  }
  persist(period,state){
    period.state=state;
    this.store.statement('UPDATE voice_rotations SET ended_ms=?,state=?,source_count=? WHERE id=?').run(period.endedAt,state,period.entries.length,period.id);
  }
  begin(actor){
    this.tick();if(!this.started||this.stopped||!this.current)return null;
    const period=this.current;
    if(++period.count>MAX_TURNS){period.overflow=true;return null;}
    const id=uid('rotation-turn'),turn={period,actor,startedAt:this.now(),active:true};
    this.turns.set(id,turn);period.pending.add(id);return id;
  }
  end(id){const turn=this.turns.get(id);if(turn){turn.active=false;this.tick();}}
  complete(id,binding){
    const turn=this.turns.get(id);if(!turn)return;
    this.turns.delete(id);turn.period.pending.delete(id);
    if(binding)turn.period.entries.push({...binding,inputAccountId:turn.actor,startedAt:turn.startedAt});
    this.tick();
  }
  tick(){
    if(!this.started||this.stopped)return;
    if(scope(this.policy())!==this.boundScope){this.halt();return;}
    const at=this.now(),period=this.current;
    if(period&&at>=period.startedAt+ROTATION_MS){
      const speaking=[...this.turns.values()].some(turn=>turn.active&&turn.period===period);
      if(!speaking||at>=period.startedAt+ROTATION_MS+this.config.voice.rotation.maxExtendSeconds*1000){
        period.endedAt=at;this.persist(period,'sealed');this.current=null;this.open(at);
      }
    }
    for(const candidate of this.periods.values())if(candidate.state==='sealed'&&
      (!candidate.pending.size||at>=candidate.endedAt+this.config.voice.rotation.postWaitSeconds*1000))this.dispatch(candidate);
  }
  dispatch(period){
    // Late transcripts remain in the Source store, never retried in a later file.
    for(const id of period.pending)this.turns.delete(id);period.pending.clear();
    if(period.overflow||!period.entries.length){this.persist(period,period.overflow?'blocked':'empty');this.periods.delete(period.id);return;}
    this.persist(period,'posting');
    const operation=(async()=>{
      try{
        const result=await this.deliver({id:period.id,guildId:period.guildId,channelId:period.channelId,targetChannelId:period.targetChannelId,
          startedAt:period.startedAt,endedAt:period.endedAt,entries:period.entries});
        const state=['sent','blocked','empty','unknown'].includes(result?.state)?result.state:'unknown';
        this.persist(period,state);
      }catch{this.persist(period,'unknown');this.onError('VOICE_ROTATION_DELIVERY_FAILED');}
      finally{this.periods.delete(period.id);}
    })();
    this.inflight.add(operation);void operation.finally(()=>this.inflight.delete(operation)).catch(()=>{});
  }
  halt(){
    this.stopped=true;clearInterval(this.timer);this.current=null;
    for(const period of this.periods.values())if(['open','sealed'].includes(period.state)){this.persist(period,'interrupted');this.periods.delete(period.id);}
    this.turns.clear();
  }
  async close(){if(this.started)this.halt();await Promise.allSettled([...this.inflight]);}
}
