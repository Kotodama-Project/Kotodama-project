import {check,Refused} from './common.mjs';

function abortReason(signal){return signal.reason instanceof Error?signal.reason:new Refused('OPERATION_CANCELLED');}

// The caller still owns any operation that ignores cancellation. A deadline is
// not evidence that a dispatched write did not happen.
export function awaitWithSignal(value,signal){
  return new Promise((resolve,reject)=>{
    const abort=()=>{cleanup();reject(abortReason(signal));};
    const cleanup=()=>signal?.removeEventListener('abort',abort);
    Promise.resolve(value).then(result=>{cleanup();resolve(result);},error=>{cleanup();reject(error);});
    if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  });
}

export function deadlineScope(timeoutMs,code,parentSignal){
  check(Number.isInteger(timeoutMs)&&timeoutMs>0,'HTTP_DEADLINE_INVALID');
  const controller=new AbortController(),abort=()=>controller.abort(abortReason(parentSignal));
  const timer=setTimeout(()=>controller.abort(new Refused(code)),timeoutMs);
  if(parentSignal?.aborted)abort();else parentSignal?.addEventListener('abort',abort,{once:true});
  return {signal:controller.signal,abort:reason=>controller.abort(reason),dispose:()=>{clearTimeout(timer);parentSignal?.removeEventListener('abort',abort);}};
}

export function readHttpBody(req,{maxBytes,signal,limitCode='BODY_TOO_LARGE',invalidCode='BODY_INVALID'}){
  check(Number.isSafeInteger(maxBytes)&&maxBytes>0,'HTTP_BODY_LIMIT_INVALID');
  const length=req.headers['content-length'];
  check(length===undefined||/^\d+$/.test(length),invalidCode);
  check(length===undefined||Number(length)<=maxBytes,limitCode);
  return new Promise((resolve,reject)=>{
    const chunks=[];let size=0;
    const cleanup=()=>{req.removeListener('data',data);req.removeListener('end',end);req.removeListener('error',fail);req.removeListener('aborted',aborted);signal?.removeEventListener('abort',abort);};
    const fail=error=>{cleanup();req.pause();reject(error);};
    const aborted=()=>fail(new Refused('HTTP_CLIENT_DISCONNECTED'));
    const abort=()=>fail(abortReason(signal));
    const data=chunk=>{size+=chunk.length;if(size>maxBytes){fail(new Refused(limitCode));return;}chunks.push(chunk);};
    const end=()=>{cleanup();resolve(Buffer.concat(chunks,size));};
    req.on('data',data);req.once('end',end);req.once('error',fail);req.once('aborted',aborted);
    if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
  });
}

export function sendHttpJson(res,status,value,{close=false}={}){
  if(res.destroyed||res.writableEnded)return false;
  const body=JSON.stringify(value);
  res.writeHead(status,{'content-type':'application/json; charset=utf-8','cache-control':'no-store',...(close?{connection:'close'}:{}),'content-length':Buffer.byteLength(body)});
  res.end(body);return true;
}
