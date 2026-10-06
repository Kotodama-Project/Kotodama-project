// One intent's route, not an authorization or semantic interpretation of speech.
// The admission gate still checks every action in the complete batch.
export const identifiedOperator=(source,policy)=>source.provider==='discord'&&Boolean(source.actorId)&&
  source.metadata?.attribution!=='unknown_speaker'&&policy.discord.operators.includes(source.actorId);

export function decideInteraction({source,intent,policy,execute=false,reply=false,draining=false,
  clarification=null,intentIndex=0,pending=false,answered=false,allowClarification=false}) {
  if(intent.kind!=='request')return 'ignore';
  const identified=identifiedOperator(source,policy);
  if(!identified||!execute||draining||!intent.explicit||intent.action==='none')return 'candidate';
  if(intent.complete)return 'execute';
  const voice=source.metadata?.kind==='voice';
  const canReply=reply&&(!voice||(policy.voice.mode==='assist'&&!policy.voice.naturalConversation&&!source.metadata?.nativeConversation));
  if(allowClarification&&canReply&&policy.interaction?.clarification==='once'&&
    policy.worker.actions.includes(intent.action)&&!pending&&!answered&&
    clarification?.intentIndex===intentIndex&&typeof clarification.question==='string'&&
    clarification.question.trim()&&clarification.question.length<=300)return 'clarify_once';
  return 'candidate';
}
