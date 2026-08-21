"""Focused regression checks for the public Agent Skills pack."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
        self.assertEqual(payload["external_catalog_count"], 0)
        self.assertEqual(payload["failures"], [])

    def test_public_skill_descriptions_and_steps_are_repository_scoped(self) -> None:
        for skill_path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
            text = skill_path.read_text(encoding="utf-8")
            description = next(
                line.removeprefix("description: ")
                for line in text.splitlines()
                if line.startswith("description: ")
            )
            self.assertTrue(
                description.startswith("Use only for the Kotodama public repository "),
                msg=skill_path.as_posix(),
            )
            procedure = text.split("## Procedure\n", 1)[1].split("\n## ", 1)[0]
            for step in range(1, 5):
                start = procedure.index(f"{step}. ")
                end = procedure.find(f"\n{step + 1}. ", start) if step < 4 else len(procedure)
                body = procedure[start:end]
                self.assertIn("Done when:", body, msg=f"{skill_path.as_posix()} step {step}")

    def test_declared_external_catalog_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external_root = Path(temporary) / "skills"
            collision = external_root / "research"
            collision.mkdir(parents=True)
            (collision / "SKILL.md").write_text(
                "---\n"
                "name: kotodama-research\n"
                "description: Research a topic.\n"
                "---\n",
                encoding="utf-8",
            )
            for directory in ("external-one", "external-two"):
                duplicate = external_root / directory
                duplicate.mkdir()
                (duplicate / "SKILL.md").write_text(
                    "---\n"
                    "name: external-collision\n"
                    f"description: {directory} description.\n"
                    "---\n",
                    encoding="utf-8",
                )
            command = [
                sys.executable,
                str(ROOT / "tools" / "audit_public_skills.py"),
                "--external-skill-root",
                str(external_root),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["external_catalog_count"], 3)
            self.assertTrue(
                any(item["finding"].startswith("external duplicate name:") for item in payload["failures"])
            )
            self.assertTrue(
                any(item["finding"] == "external duplicate name: external-collision" for item in payload["failures"])
            )

    def test_oversized_external_skill_is_bounded_and_path_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external_root = Path(temporary) / "skills"
            oversized = external_root / "oversized"
            oversized.mkdir(parents=True)
            (oversized / "SKILL.md").write_bytes(b"x" * (64 * 1024 + 1))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "audit_public_skills.py"),
                    "--external-skill-root",
                    str(external_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(temporary, result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["failures"][0]["path"], "external[0]/oversized/SKILL.md")
            self.assertIn("exceeds 65536 bytes", payload["failures"][0]["finding"])


if __name__ == "__main__":
    unittest.main()
