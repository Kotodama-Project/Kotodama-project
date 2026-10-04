import {check,uid} from './common.mjs';

const height=node=>node?.height??0;
function refresh(node){node.height=1+Math.max(height(node.left),height(node.right));node.maxEnd=Math.max(node.end,node.left?.maxEnd??-Infinity,node.right?.maxEnd??-Infinity);return node;}
function rotateLeft(node){const next=node.right;node.right=next.left;next.left=refresh(node);return refresh(next);}
function rotateRight(node){const next=node.left;node.left=next.right;next.right=refresh(node);return refresh(next);}
function insert(node,entry){
  if(!node)return refresh({...entry,left:null,right:null});
  const order=entry.start-node.start||entry.order-node.order;
  if(order<0)node.left=insert(node.left,entry);else if(order>0)node.right=insert(node.right,entry);else{node.end=entry.end;node.value=entry.value;}
  refresh(node);const balance=height(node.left)-height(node.right);
  if(balance>1){if(height(node.left.left)<height(node.left.right))node.left=rotateLeft(node.left);return rotateRight(node);}
  if(balance<-1){if(height(node.right.right)<height(node.right.left))node.right=rotateRight(node.right);return rotateLeft(node);}
  return node;
}
// Start-time ordering plus subtree end bounds also finds late, out-of-order
// deltas and overlapping utterances without walking the entire session.
class IntervalIndex {
  constructor(){this.root=null;this.next=0;}
  add(start,end,value){const key={start,order:this.next++};this.set(key,end,value);return key;}
  set(key,end,value){this.root=insert(this.root,{...key,end,value});}
  overlapping(start,end){
    const values=[];
    const visit=node=>{if(!node||node.maxEnd<=start)return;visit(node.left);if(node.start>=end)return;if(node.end>start)values.push(node.value);visit(node.right);};
    visit(this.root);return values;
  }
}

/** Local utterance grouping is provisional semantics, not a provider turn receipt. */
export class TranscriptTurns {
  constructor({onTurn,onError=()=>{},settleMs=1500,clock=Date.now}){
    this.onTurn=onTurn;this.onError=onError;this.settleMs=settleMs;this.clock=clock;
    this.fragments=new Map();this.turns=[];this.pending=new Set();this.closed=false;this.revision=0;
    this.fragmentIntervals=new IntervalIndex();this.endedTurns=new IntervalIndex();this.turnKeys=new WeakMap();this.dirty=new Set();this.closing=null;
  }
  begin(startMs){check(!this.closed,'TRANSCRIPT_CLOSED');check(Number.isFinite(startMs),'TRANSCRIPT_INVALID');const turn={id:uid('utterance'),startMs,endMs:Infinity,revision:0,timer:null};this.turns.push(turn);return turn;}
  end(turn,endMs){
    if(this.closed)return;check(Number.isFinite(endMs)&&endMs>=turn.startMs,'TRANSCRIPT_INVALID');turn.endMs=endMs;
    let key=this.turnKeys.get(turn);if(key)this.endedTurns.set(key,endMs,turn);else{key=this.endedTurns.add(turn.startMs,endMs,turn);this.turnKeys.set(turn,key);}
    this.#schedule(turn);
  }
  fragment(f){
    if(this.closed)return;check(f.id&&typeof f.text==='string'&&Number.isFinite(f.startMs)&&Number.isFinite(f.endMs)&&f.endMs>=f.startMs,'TRANSCRIPT_INVALID');
    const old=this.fragments.get(f.id);if(old){check(JSON.stringify(old)===JSON.stringify(f),'TRANSCRIPT_EVENT_CONFLICT');return;}
    this.fragments.set(f.id,f);this.fragmentIntervals.add(f.startMs,f.endMs,f);
    for(const turn of this.endedTurns.overlapping(f.startMs,f.endMs))this.#schedule(turn);
  }
  #schedule(turn){
    this.dirty.add(turn);clearTimeout(turn.timer);turn.timer=setTimeout(()=>{if(!this.closed)this.#emit(turn);},this.settleMs);turn.timer.unref?.();
  }
  #emit(turn){
    this.dirty.delete(turn);clearTimeout(turn.timer);turn.timer=null;
    const fragments=this.fragmentIntervals.overlapping(turn.startMs,turn.endMs).sort((a,b)=>a.startMs-b.startMs||a.endMs-b.endMs);
    const text=fragments.map(f=>f.text).join('');if(!text.trim()||turn.lastText===text)return;turn.lastText=text;turn.revision=++this.revision;
    const event={id:turn.id,text,startMs:turn.startMs,endMs:turn.endMs,revision:turn.revision,final:true,finality:'vad_and_settled_transcript',providerTurnComplete:false};
    // Register work before calling consumer code, including synchronous throws
    // and consumers which request close during delivery.
    const work=Promise.resolve().then(()=>this.onTurn(event));
    this.pending.add(work);
    work.then(()=>this.pending.delete(work),error=>{this.pending.delete(work);try{Promise.resolve(this.onError(error)).catch(()=>{});}catch{}});
  }
  async #drain(close){
    // A delivery may admit a correction while an earlier callback is draining.
    // Repeat until those already admitted deltas and callbacks are complete.
    do{for(const turn of [...this.dirty])this.#emit(turn);if(this.pending.size)await Promise.allSettled([...this.pending]);}while(this.dirty.size||this.pending.size);
    if(close)this.closed=true;
  }
  flush(){return this.#drain(false);}
  close(){if(!this.closing)this.closing=this.#drain(true);return this.closing;}
}
