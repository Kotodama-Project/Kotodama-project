"""Focused regression checks for the public Agent Skills pack."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicSkillsTest(unittest.TestCase):
    def test_public_skill_audit_passes_without_mutation(self) -> None:
        command = [sys.executable, str(ROOT / "tools" / "audit_public_skills.py")]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["evidence_tier"], "LOCAL")
        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["skill_count"], 9)
        self.assertEqual(payload["failures"], [])


if __name__ == "__main__":
    unittest.main()
