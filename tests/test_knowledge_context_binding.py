"""Actual KB CLI -> current context pin -> existing runner stdin (fixture child)."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_knowledge_base as base

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-09-09T00:00:00Z"
NODE_PROGRAM = r'''
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {prepareKnowledgeBriefInput} from __KNOWLEDGE__;
import {runCodexBrief} from __RUNNER__;
const [path,pin,source,marker] = process.argv.slice(1);
const hash = x => createHash('sha256').update(x).digest('hex');
try {
 const prepared=prepareKnowledgeBriefInput({request:'Synthetic corrected development brief',contextJson:readFileSync(path,'utf8'),expectedContextSha256:pin,expectedSourceDigest:source,now:Date.parse('2026-09-09T00:00:00Z')});
 const executable=join(dirname(path),'synthetic-runner');writeFileSync(executable,'synthetic');
 let captured='',binding,session;
 const spawnImpl=()=>{
  const c=new EventEmitter();c.stdin=new PassThrough();c.stdout=new PassThrough();c.stderr=new PassThrough();
  c.kill=()=>{setImmediate(()=>c.emit('close',1));return true;};
  c.stdin.on('data',b=>captured+=b.toString('utf8'));
  c.stdin.on('finish',()=>setImmediate(()=>{
   const envelope=JSON.parse(captured.slice(captured.indexOf('\n')+1));
   const data=JSON.parse(envelope.request);
   assert.ok(data.knowledge_context.concepts.some(v=>v.description.includes(marker)));
   const thread_id=randomUUID();
   for(const e of [{type:'thread.started',thread_id},{type:'turn.started'},
    {type:'item.completed',item:{type:'agent_message',text:JSON.stringify({objective:'合成要件',deliverable:'要件案',constraints:[marker],acceptance_criteria:['同じ入力を確認する'],open_questions:[]})}},
    {type:'turn.completed'}]) c.stdout.write(JSON.stringify(e)+'\n');
   c.emit('close',0);
  }));return c;
 };
 const result=await runCodexBrief({executable,expectedExecutableSha256:hash('synthetic'),cwd:dirname(path),model:'gpt-6-astra',input:prepared.input,
  onInputPrepared:x=>{binding=x;},onSessionStarted:x=>{session=x;}},{spawnImpl});
 assert.equal(result.stdin_sha256,hash(captured));assert.equal(binding.stdin_sha256,result.stdin_sha256);assert.equal(session.stdin_sha256,result.stdin_sha256);
 console.log(JSON.stringify({status:'pass',context_sha256:prepared.knowledge_context_sha256,stdin_sha256:result.stdin_sha256,constraints:result.brief.constraints,task_binding:prepared.task_binding,synthetic_runner:true}));
}catch(e){console.log(JSON.stringify({status:'refused',reason:e.message}));process.exitCode=1;}
'''.replace("__KNOWLEDGE__", json.dumps((ROOT / "runtime/codex-task-bridge/knowledge-input.mjs").as_uri())).replace(
    "__RUNNER__", json.dumps((ROOT / "runtime/codex-task-bridge/codex-runner.mjs").as_uri()))


class KnowledgeContextBindingTests(unittest.TestCase):
    def test_correction_changes_real_context_and_stdin_old_pin_is_refused(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required; do not silently skip the bridge")
        with tempfile.TemporaryDirectory(prefix="kb-runner-binding-") as tmp:
            root = base.KnowledgeBaseTests._minimal_copy(Path(tmp))
            concept = root / "knowledge/project/current-state.md"
            original = concept.read_text(encoding="utf-8")
            def generate(marker):
                lines = original.splitlines()
                lines = ["description: " + marker if line.startswith("description:") else line for line in lines]
                concept.write_text("\n".join(lines) + "\n", encoding="utf-8")
                result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/knowledge_base.py"), "context", "--root", str(root),
                    "--as-of", AS_OF, "--goal", "OUT-INTENT", "--max-concepts", "8", "--json"], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data["state"], "ready_candidate")
                return result.stdout, data["source_digest"]
            first, first_source = generate("SYNTHETIC_INITIAL_SMARTPHONE_AND_BLE")
            path = Path(tmp) / "context.json"
            def run(raw, pin, source, marker):
                path.write_bytes(raw)
                return subprocess.run([node, "--input-type=module", "-e", NODE_PROGRAM, str(path), pin, source, marker], capture_output=True, timeout=30)
            old = run(first, hashlib.sha256(first).hexdigest(), first_source, "SYNTHETIC_INITIAL")
            self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
            second, second_source = generate("SYNTHETIC_CORRECTION_SMARTPHONE_ONLY_BLE_EXCLUDED")
            self.assertNotEqual(first_source, second_source)
            old_context = run(first, hashlib.sha256(first).hexdigest(), second_source, "SYNTHETIC_INITIAL")
            self.assertEqual(old_context.returncode, 1)
            self.assertEqual(json.loads(old_context.stdout)["reason"], "knowledge_source_drift")
            stale = run(second, hashlib.sha256(first).hexdigest(), first_source, "SYNTHETIC_CORRECTION")
            self.assertEqual(stale.returncode, 1)
            self.assertEqual(json.loads(stale.stdout)["reason"], "knowledge_context_drift")
            new = run(second, hashlib.sha256(second).hexdigest(), second_source, "SYNTHETIC_CORRECTION")
            self.assertEqual(new.returncode, 0, new.stdout + new.stderr)
            result = json.loads(new.stdout)
            self.assertNotEqual(json.loads(old.stdout)["stdin_sha256"], result["stdin_sha256"])
            self.assertEqual(result["task_binding"], "not_connected")


if __name__ == "__main__":
    unittest.main()
