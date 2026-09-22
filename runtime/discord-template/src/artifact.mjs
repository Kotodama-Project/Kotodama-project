import {lstat,open} from 'node:fs/promises';
import {constants} from 'node:fs';
import {check} from './common.mjs';

// Check both the opened descriptor and the directory entry. O_NONBLOCK also
// bounds open itself when a regular file is replaced by a FIFO between checks.
export async function readArtifact(file,maxBytes){
  check(Number.isSafeInteger(maxBytes)&&maxBytes>=0&&maxBytes<=1073741824,'ARTIFACT_SIZE_LIMIT');
  const entry=await lstat(file,{bigint:true});
  const regular=s=>s.isFile()&&s.nlink===1n&&s.size<=BigInt(maxBytes);
  const same=(a,b)=>a.dev===b.dev&&a.ino===b.ino&&a.size===b.size&&a.mtimeNs===b.mtimeNs&&a.ctimeNs===b.ctimeNs;
  check(regular(entry),'ARTIFACT_SIZE_LIMIT');
  const handle=await open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));
  try{
    const before=await handle.stat({bigint:true});
    check(regular(before),'ARTIFACT_SIZE_LIMIT');check(same(entry,before),'ARTIFACT_CHANGED');
    const size=Number(before.size),bytes=Buffer.alloc(size+1);let total=0;
    while(total<bytes.length){const read=await handle.read(bytes,total,bytes.length-total,total);if(!read.bytesRead)break;total+=read.bytesRead;}
    const after=await handle.stat({bigint:true}),current=await lstat(file,{bigint:true});
    check(total===size&&regular(after)&&regular(current)&&same(before,after)&&same(after,current),'ARTIFACT_CHANGED');
    return bytes.subarray(0,total);
  }finally{await handle.close();}
}
