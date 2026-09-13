import test from 'node:test';
import assert from 'node:assert/strict';
import {DiscordAdapter} from '../src/discord.mjs';
import {exampleConfig} from '../src/config.mjs';
test('ask returns the answer and rechecks source access before the ephemeral reply',async t=>{
  const config=exampleConfig(),actor=config.discord.operators[0],replies=[];let allowed=true;
  const adapter=new DiscordAdapter({config,store:{source:()=>({revision:1,provider:'discord',channelId:config.discord.resultChannelId})},pipeline:{ingest:async(_s,flags)=>{assert.equal(flags.execute,false);assert.equal(flags.reply,false);return {summary:'相談の要約',answer:'相談への回答',contextSources:[{key:'source',revision:1}]};}}});
  t.after(()=>adapter.client.destroy());adapter.verifiedInstallation=true;adapter.member=async()=>({});adapter.canRead=async()=>allowed;adapter.client.channels.fetch=async()=>({});
  const i={guildId:config.discord.guildId,channelId:config.discord.resultChannelId,id:'interaction',createdTimestamp:1,commandName:'kotodama',user:{id:actor},isButton:()=>false,isChatInputCommand:()=>true,options:{getSubcommand:()=> 'ask',getString:()=> 'どう思う？'},deferReply:async()=>{},editReply:async v=>replies.push(v.content)};
  await adapter.interaction(i);assert.equal(replies[0],'相談への回答');allowed=false;await adapter.interaction(i);assert(replies[1].includes('SOURCE_ACCESS_DENIED'));assert(!replies[1].includes('相談への回答'));
});
