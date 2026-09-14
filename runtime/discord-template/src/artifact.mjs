import {lstat,open} from 'node:fs/promises';
import {constants} from 'node:fs';
import {check} from './common.mjs';

const sameFile=(a,b)=>a.dev===b.dev&&a.ino===b.ino;
const regular=(s,cap)=>s.isFile()&&s.nlink===1&&Number.isSafeInteger(s.size)&&s.size>=0&&s.size<=cap;

export async function readArtifact(file,maxBytes){
  check(Number.isSafeInteger(maxBytes)&&maxBytes>=0&&maxBytes<=50000000,'ARTIFACT_SIZE_LIMIT');
  // The descriptor check, not this precheck, is the authority after open.
  const entry=await lstat(file);check(regular(entry,maxBytes),'ARTIFACT_SIZE_LIMIT');
  const handle=await open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));
  try{
    const before=await handle.stat();
    check(regular(before,maxBytes)&&sameFile(entry,before),'ARTIFACT_CHANGED');
    const bytes=Buffer.alloc(before.size+1);let total=0;
    while(total<bytes.length){const read=await handle.read(bytes,total,bytes.length-total,total);if(!read.bytesRead)break;total+=read.bytesRead;}
    const after=await handle.stat(),current=await lstat(file);
    check(regular(after,maxBytes)&&regular(current,maxBytes)&&sameFile(before,after)&&sameFile(before,current)&&
      total===before.size&&after.size===before.size&&after.mtimeMs===before.mtimeMs&&after.ctimeMs===before.ctimeMs&&
      current.size===after.size&&current.mtimeMs===after.mtimeMs&&current.ctimeMs===after.ctimeMs,'ARTIFACT_CHANGED');
    return bytes.subarray(0,total);
  }finally{await handle.close();}
}
