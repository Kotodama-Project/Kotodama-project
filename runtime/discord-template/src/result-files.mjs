import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {check,digest,safePath} from './common.mjs';

// Only designated deliverables go to the requesting operator, never every changed file.
export async function resultFiles(result){
  const files=[];let size=0;
  for(const a of result?.artifacts??[]){
    if(a.deleted||!/^deliverables\/[A-Za-z0-9_-]+\.(md|html|txt|pdf)$/.test(a.relative))continue;
    check(files.length<8,'RESULT_FILE_COUNT_LIMIT');
    const file=await safePath(result.workspace,a.relative);
    check(path.resolve(a.path)===file,'RESULT_FILE_PATH_MISMATCH');
    check(a.bytes<=2000000,'RESULT_FILE_SIZE_LIMIT');
    const bytes=await readFile(file);size+=bytes.length;
    check(size<=8000000&&bytes.length===a.bytes&&digest(bytes)===a.sha256,'RESULT_FILE_CHANGED');
    files.push({attachment:bytes,name:path.basename(a.relative)});
  }
  return files;
}
