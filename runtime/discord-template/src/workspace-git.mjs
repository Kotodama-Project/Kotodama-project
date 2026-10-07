import {runCommand} from './command.mjs';
import {check} from './common.mjs';

// Per-command flags preserve the operator's Git configuration.
export const runWorkspaceGit=(args,options)=>runCommand('git',['-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null',...args],options);
export async function assertWorkspaceFiltersSafe(cwd,signal){
  const options={cwd,signal,timeoutMs:30000,maxBytes:4000000};
  const tracked=await runWorkspaceGit(['ls-files','--cached','--others','--exclude-standard','-z'],options);check(tracked.code===0,'CHANNEL_WORKSPACE_GIT_FAILED');
  for(const from of [[],['--source=HEAD']]){
    const result=await runWorkspaceGit(['check-attr',...from,'-z','--stdin','filter'],{...options,input:tracked.stdout});
    check(result.code===0,'CHANNEL_WORKSPACE_GIT_FAILED');const attributes=result.stdout.split('\0');
    for(let index=2;index<attributes.length;index+=3)check(['unspecified','unset'].includes(attributes[index]),'CHANNEL_WORKSPACE_FILTER_REFUSED');
  }
}
