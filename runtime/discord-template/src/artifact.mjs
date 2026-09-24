import {lstat,open} from 'node:fs/promises';
import {constants} from 'node:fs';
import {check,Refused} from './common.mjs';

// Open first, then prove that the directory entry still names the opened
// descriptor. Checking the path before opening it would leave a window in which
// the entry could be replaced. O_NOFOLLOW refuses a final symbolic link and
// O_NONBLOCK keeps open itself bounded when the entry is a FIFO.
const notRegular=new Set(['ELOOP','EMLINK','EFTYPE','EISDIR','ENXIO']);
export async function readArtifact(file,maxBytes){
  check(Number.isSafeInteger(maxBytes)&&maxBytes>=0&&maxBytes<=1073741824,'ARTIFACT_SIZE_LIMIT');
  let handle;
  try{handle=await open(file,constants.O_RDONLY|(constants.O_NOFOLLOW??0)|(constants.O_NONBLOCK??0));}
  catch(error){if(notRegular.has(error?.code))throw new Refused('ARTIFACT_SIZE_LIMIT');throw error;}
  const regular=s=>s.isFile()&&s.nlink===1n&&s.size<=BigInt(maxBytes);
  const same=(a,b)=>a.dev===b.dev&&a.ino===b.ino&&a.size===b.size&&a.mtimeNs===b.mtimeNs&&a.ctimeNs===b.ctimeNs;
  try{
    const before=await handle.stat({bigint:true});
    check(regular(before),'ARTIFACT_SIZE_LIMIT');
    const entry=await lstat(file,{bigint:true});
    check(regular(entry),'ARTIFACT_SIZE_LIMIT');check(same(entry,before),'ARTIFACT_CHANGED');
    const size=Number(before.size),bytes=Buffer.alloc(size+1);let total=0;
    while(total<bytes.length){const read=await handle.read(bytes,total,bytes.length-total,total);if(!read.bytesRead)break;total+=read.bytesRead;}
    const after=await handle.stat({bigint:true}),current=await lstat(file,{bigint:true});
    check(total===size&&regular(after)&&regular(current)&&same(before,after)&&same(after,current),'ARTIFACT_CHANGED');
    return bytes.subarray(0,total);
  }finally{await handle.close();}
}
