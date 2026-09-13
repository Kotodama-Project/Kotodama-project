import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {resultFiles} from '../src/result-files.mjs';
import {digest} from '../src/common.mjs';
test('only selected deliverables are attached and changed bytes are rejected',async t=>{
  const workspace=await mkdtemp(path.join(os.tmpdir(),'result-files-'));t.after(()=>rm(workspace,{recursive:true,force:true}));
  await mkdir(path.join(workspace,'deliverables'));const file=path.join(workspace,'deliverables/invitation.md');await writeFile(file,'hello');
  const result={workspace,artifacts:[{relative:'review-notes.md',path:'/unrelated/private'},{relative:'deliverables/invitation.md',path:file,sha256:digest('hello'),bytes:5}]};
  const files=await resultFiles(result);assert.equal(files.length,1);assert.equal(files[0].name,'invitation.md');assert.equal(files[0].attachment.toString(),'hello');
  await writeFile(file,'changed');await assert.rejects(resultFiles(result),/RESULT_FILE_CHANGED/);
});
