"""Actual Work compiler -> v2 adapter -> existing runner with a fixture child."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_knowledge_context_binding import NODE_PROGRAM, AS_OF

ROOT=Path(__file__).resolve().parents[1]
PROGRAM=NODE_PROGRAM.replace(
    "data.knowledge_context.concepts.some(v=>v.description.includes(marker))",
    "data.knowledge_context.work.acceptance_criteria.some(v=>v.description.includes(marker))")


class KnowledgeWorkContextBindingTests(unittest.TestCase):
    def test_revised_acceptance_reaches_stdin_and_old_work_pin_is_refused(self):
        node=shutil.which("node.exe" if sys.platform=="win32" else "node")
        self.assertIsNotNone(node,"Node is required for the real adapter boundary")
        with tempfile.TemporaryDirectory(prefix="work-context-binding-") as temporary:
            root=Path(temporary).resolve()
            package_root=root/"package"
            shutil.copytree(ROOT/"examples/knowledge-work/business-rehearsal",package_root)
            manifest=package_root/"knowledge-work.json"
            package=json.loads(manifest.read_text(encoding="utf-8"))
            def compile_marker(marker):
                package["criteria"][0]["description"]=marker
                manifest.write_text(json.dumps(package,ensure_ascii=False),encoding="utf-8",newline="\n")
                result=subprocess.run([sys.executable,"-B",str(ROOT/"tools/compile_knowledge_context.py"),str(package_root),"--as-of",AS_OF],capture_output=True,timeout=30)
                self.assertEqual(0,result.returncode,result.stderr)
                return result.stdout,json.loads(result.stdout)["source_digest"]
            def invoke(data,pin,source,marker):
                path=root/"context.json";path.write_bytes(data)
                return subprocess.run([node,"--input-type=module","-e",PROGRAM,str(path),pin,source,marker],capture_output=True,timeout=30)
            first,old_source=compile_marker("SYNTHETIC_INITIAL_ACCEPTANCE")
            old=invoke(first,hashlib.sha256(first).hexdigest(),old_source,"SYNTHETIC_INITIAL_ACCEPTANCE")
            self.assertEqual(0,old.returncode,old.stdout+old.stderr)
            second,new_source=compile_marker("SYNTHETIC_REVISED_ACCEPTANCE")
            denied=invoke(first,hashlib.sha256(first).hexdigest(),new_source,"SYNTHETIC_INITIAL_ACCEPTANCE")
            self.assertEqual(1,denied.returncode)
            self.assertEqual("knowledge_source_drift",json.loads(denied.stdout)["reason"])
            accepted=invoke(second,hashlib.sha256(second).hexdigest(),new_source,"SYNTHETIC_REVISED_ACCEPTANCE")
            self.assertEqual(0,accepted.returncode,accepted.stdout+accepted.stderr)
            self.assertNotEqual(json.loads(old.stdout)["stdin_sha256"],json.loads(accepted.stdout)["stdin_sha256"])
            self.assertEqual("not_connected",json.loads(accepted.stdout)["task_binding"])


if __name__=="__main__":
    unittest.main()
