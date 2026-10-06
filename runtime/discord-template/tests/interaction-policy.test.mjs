import test from 'node:test';
import assert from 'node:assert/strict';
import {decideInteraction} from '../src/interaction-policy.mjs';

const actor='100000000000000002';
const policy={discord:{operators:[actor]},worker:{actions:['research']},voice:{mode:'assist',naturalConversation:false},interaction:{clarification:'once'}};
const source={provider:'discord',actorId:actor,metadata:{kind:'text'}};
const intent={kind:'request',explicit:true,complete:true,action:'research'};
const decide=(overrides={})=>decideInteraction({source,intent,policy,execute:true,reply:true,...overrides});

test('only the current identified operator explicit complete request is executable',()=>{
  assert.equal(decide(),'execute');
  for(const overrides of [
    {execute:false},{draining:true},{source:{...source,actorId:null}},
    {source:{...source,actorId:'100000000000000004'}},{source:{...source,provider:'luma'}},
    {source:{...source,metadata:{attribution:'unknown_speaker'}}},
    {policy:{...policy,discord:{operators:[]}}},
    {intent:{...intent,complete:false}},{intent:{...intent,action:'none'}},{intent:{...intent,explicit:false}}
  ])assert.equal(decide(overrides),'candidate');
});

test('name calls, quoted requests and casual speech receive no Task authority',()=>{
  // These are structured analyzer candidates, not an NLU/provider test.
  for(const text of ['ことだま','「この仕事を実行して」と彼は言った','明日何を食べよう']) {
    assert.equal(decide({source:{...source,text},intent:{...intent,explicit:false}}),'candidate');
    assert.equal(decide({source:{...source,text},intent:{...intent,kind:'question'}}),'ignore');
  }
});

test('a forbidden complete action still reaches the all-or-nothing admission refusal',()=>{
  assert.equal(decide({intent:{...intent,action:'develop'}}),'execute');
  // Routing is not the action grant; task-admission.test exercises the refusal.
});

test('clarification stays disabled without explicit wiring and a reply route',()=>{
  const clarification={intentIndex:0,question:'調査する対象はどれですか？'};
  const incomplete={...intent,complete:false};
  assert.equal(decide({intent:incomplete,clarification}),'candidate');
  const input={intent:incomplete,clarification,allowClarification:true};
  assert.equal(decide(input),'clarify_once');
  for(const changes of [
    {reply:false},{pending:true},{answered:true},{clarification:{...clarification,intentIndex:1}},
    {clarification:{...clarification,question:' '}},{clarification:{...clarification,question:'a'.repeat(301)}},
    {policy:{...policy,interaction:{clarification:'off'}}},
    {intent:{...incomplete,action:'develop'}},
    {source:{...source,metadata:{kind:'voice',nativeConversation:true}}},
    {source:{...source,metadata:{kind:'voice'}},policy:{...policy,voice:{...policy.voice,mode:'minutes'}}},
    {source:{...source,metadata:{kind:'voice'}},policy:{...policy,voice:{...policy.voice,naturalConversation:true}}}
  ])assert.equal(decide({...input,...changes}),'candidate');
});
