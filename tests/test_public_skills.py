"""Focused regression checks for the public Agent Skills pack."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicSkillsTest(unittest.TestCase):
    @staticmethod
    def _load_auditor():
        path = ROOT / "tools" / "audit_public_skills.py"
        spec = importlib.util.spec_from_file_location("audit_public_skills_test", path)
        if spec is None or spec.loader is None:
            raise AssertionError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _valid_skill(name: str = "kotodama-fixture", body: str = "") -> str:
        return (
            "---\n"
            f"name: {name}\n"
            "description: Use only for the Kotodama public repository test fixture.\n"
            "---\n\n"
            "# Fixture\n\n"
            "## Intent\n"
            "Keep this fixture bounded.\n\n"
            "## Triggers\n"
            "Use the fixture only in tests.\n\n"
            "## Non-triggers\n"
            "Do not use the fixture as a runtime.\n\n"
            "## Procedure\n"
            "1. Inspect the fixture. Done when: the fixture is read.\n"
            "2. Compare the fixture. Done when: the comparison is recorded.\n"
            "3. Check the fixture. Done when: the check is complete.\n"
            "4. Emit the receipt. Done when: the receipt is complete.\n\n"
            "## Completion\n"
            "The fixture emits a local result.\n"
            f"{body}"
        )

    def _audit_temporary_local_skill(
        self, text: str, name: str = "fixture"
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            skill_path = skills_root / name / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text(text, encoding="utf-8")
            auditor = self._load_auditor()
            auditor.ROOT = root
            auditor.SKILLS_ROOT = skills_root
            return auditor.audit()

    @staticmethod
    def _run_cli(
        *external_roots: Path,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        command = [sys.executable, str(ROOT / "tools" / "audit_public_skills.py")]
        for root in external_roots:
            command.extend(["--external-skill-root", str(root)])
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False
        )
        return result, json.loads(result.stdout)

    def test_public_skill_audit_passes_without_mutation(self) -> None:
        command = [sys.executable, str(ROOT / "tools" / "audit_public_skills.py")]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["schema_version"], "kotodama.skill-receipt.v1")
        self.assertEqual(payload["skill"], "kotodama-surface-audit")
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["evidence_tier"], "LOCAL")
        self.assertEqual(payload["changed"], False)
        self.assertEqual(payload["no_op"], True)
        self.assertTrue(payload["no_op_reason"])
        self.assertRegex(payload["target"]["identity_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(payload["source_revision"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(payload["before_sha256"], payload["after_sha256"])
        self.assertEqual(payload["actor"], "UNKNOWN")
        self.assertEqual(payload["model_verification"], "NOT_APPLICABLE")
        self.assertIsNone(payload["approval_ref"])
        self.assertIsNone(payload["rollback_ref"])
        self.assertEqual(payload["evidence_refs"], [])
        self.assertEqual(
            payload["effect_counts"],
            {"files_changed": 0, "network_writes": 0, "external_sends": 0},
        )
        self.assertEqual(payload["no_go_reasons"], [])
        self.assertEqual(payload["audit"]["skill_count"], 9)
        self.assertEqual(payload["audit"]["external_catalog_count"], 0)
        self.assertEqual(payload["audit"]["failures"], [])

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
            result, payload = self._run_cli(external_root)
            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertEqual(payload["status"], "FAILED")
            self.assertEqual(payload["audit"]["external_catalog_count"], 3)
            self.assertTrue(
                any(
                    item["finding"].startswith("external duplicate name:")
                    for item in payload["audit"]["failures"]
                )
            )
            self.assertTrue(
                any(
                    item["finding"] == "external duplicate name: external-collision"
                    for item in payload["audit"]["failures"]
                )
            )

    def test_oversized_external_skill_is_bounded_and_path_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external_root = Path(temporary) / "skills"
            oversized = external_root / "oversized"
            oversized.mkdir(parents=True)
            (oversized / "SKILL.md").write_bytes(b"x" * (64 * 1024 + 1))
            result, payload = self._run_cli(external_root)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(temporary, result.stdout)
            self.assertEqual(
                payload["audit"]["failures"][0]["path"],
                "external[0]/oversized/SKILL.md",
            )
            self.assertIn("exceeds 65536 bytes", payload["audit"]["failures"][0]["finding"])

    def test_malformed_frontmatter_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external_root = Path(temporary) / "skills"
            malformed = external_root / "malformed"
            malformed.mkdir(parents=True)
            (malformed / "SKILL.md").write_text(
                "---\n"
                "name: kotodama-malformed\n"
                "description: \"unterminated\n"
                "---\n",
                encoding="utf-8",
            )
            result, payload = self._run_cli(external_root)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "FAILED")
            self.assertTrue(
                any(
                    item["path"] == "external[0]/malformed/SKILL.md"
                    and "frontmatter" in item["finding"]
                    for item in payload["audit"]["failures"]
                )
            )

    def test_public_skill_namespace_is_enforced(self) -> None:
        payload = self._audit_temporary_local_skill(self._valid_skill(name="research"))
        self.assertEqual(payload["status"], "FAILED")
        self.assertTrue(
            any("kotodama-" in item["finding"] for item in payload["audit"]["failures"])
        )

    def test_fenced_examples_do_not_satisfy_required_sections(self) -> None:
        text = (
            "---\n"
            "name: kotodama-fenced\n"
            "description: Use only for the Kotodama public repository fenced fixture.\n"
            "---\n\n"
            "# Fixture\n\n"
            "```markdown\n"
            "## Intent\n"
            "## Triggers\n"
            "## Non-triggers\n"
            "## Procedure\n"
            "1. Example. Done when: example.\n"
            "2. Example. Done when: example.\n"
            "3. Example. Done when: example.\n"
            "4. Example. Done when: example.\n"
            "## Completion\n"
            "```\n"
        )
        payload = self._audit_temporary_local_skill(text)
        self.assertEqual(payload["status"], "FAILED")
        self.assertTrue(
            any(
                "missing heading: ## Intent" == item["finding"]
                for item in payload["audit"]["failures"]
            )
        )

    def test_generic_fixed_model_claim_is_rejected(self) -> None:
        payload = self._audit_temporary_local_skill(
            self._valid_skill(body="\nThis recipe pins `gpt-4o` without runtime evidence.\n")
        )
        self.assertEqual(payload["status"], "FAILED")
        self.assertTrue(
            any(
                "fixed_model_claim" in item["finding"]
                for item in payload["audit"]["failures"]
            )
        )

    def test_direct_public_mutation_commands_are_rejected(self) -> None:
        payload = self._audit_temporary_local_skill(
            self._valid_skill(
                body="\n```sh\ngit push origin main\ngh release create v1.0.0\n```\n"
            )
        )
        self.assertEqual(payload["status"], "FAILED")
        self.assertTrue(
            any(
                "direct_repository_mutation" in item["finding"]
                for item in payload["audit"]["failures"]
            )
        )

    def test_non_trigger_explanation_does_not_count_as_executable_command(self) -> None:
        text = self._valid_skill().replace(
            "Do not use the fixture as a runtime.",
            "Never run `git push origin main` or `gh release create`.",
        )
        payload = self._audit_temporary_local_skill(text)
        self.assertEqual(payload["status"], "COMPLETED")

    def test_non_regular_skill_file_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external_root = Path(temporary) / "skills"
            special = external_root / "special"
            special.mkdir(parents=True)
            (special / "SKILL.md").mkdir()
            result, payload = self._run_cli(external_root)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                payload["audit"]["failures"][0]["path"],
                "external[0]/special/SKILL.md",
            )
            self.assertIn("not a regular file", payload["audit"]["failures"][0]["finding"])

    def test_skill_enumeration_stops_at_limit_plus_one(self) -> None:
        auditor = self._load_auditor()

        class CountingRoot:
            def exists(self) -> bool:
                return True

            def is_dir(self) -> bool:
                return True

            def resolve(self) -> Path:
                return ROOT

            def glob(self, pattern: str):
                self.requested = 0
                for index in range(auditor.MAX_SKILLS_PER_ROOT + 1):
                    self.requested += 1
                    yield ROOT / f"skill-{index}" / "SKILL.md"
                raise AssertionError("enumeration continued past the bounded limit")

        root = CountingRoot()
        paths, error = auditor._bounded_skill_paths(root)
        self.assertEqual(paths, [])
        self.assertEqual(error, f"skill count exceeds {auditor.MAX_SKILLS_PER_ROOT}")


if __name__ == "__main__":
    unittest.main()
