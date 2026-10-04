import {errorCode} from './common.mjs';

// An uncertain drain preserves the running owner; a later signal retries close.
export function registerShutdownSignals(runtime,{target=process,exit=code=>process.exit(code),report=code=>console.error(JSON.stringify({event:'runtime_shutdown_failed',code}))}={}){
  let pending;
  const dispose=()=>{target.off('SIGINT',stop);target.off('SIGTERM',stop);};
  const stop=()=>{
    if(pending)return;
    pending=Promise.resolve().then(()=>runtime.close()).then(()=>{dispose();exit(0);},error=>{
      const code=errorCode(error);report(code);
      if(!code.endsWith('_DRAIN_UNCERTAIN')){dispose();exit(1);}
    }).finally(()=>{pending=null;});
  };
  target.on('SIGINT',stop);target.on('SIGTERM',stop);return dispose;
}
