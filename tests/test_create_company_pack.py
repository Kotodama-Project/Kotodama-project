import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / "tools" / "create_company_pack.py"
VALIDATOR = ROOT / "tools" / "validate_template_pack.py"
STARTER = ROOT / "examples" / "company-starter"


class CreateCompanyPackCliTests(unittest.TestCase):
    def run_creator(
        self, pack_id: str, target: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CREATOR), pack_id, str(target)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_creates_a_valid_pack_and_rebinds_every_manifest_moc(self) -> None:
        source_before = {
            path.relative_to(STARTER).as_posix(): path.read_bytes()
            for path in STARTER.rglob("*")
            if path.is_file()
        }
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            target = parent / "my-company"
            result = self.run_creator("my-company", target)

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["pack_id"], "my-company")
            self.assertEqual(summary["validated_files"], 22)
            self.assertEqual(summary["rebound_mocs"], 3)

            manifest = json.loads(
                (target / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["id"], "my-company")
            for relative in manifest["mocs"]:
                moc = json.loads((target / relative).read_text(encoding="utf-8"))
                self.assertEqual(moc["refs"][0], "my-company")

            validation = subprocess.run(
                [sys.executable, str(VALIDATOR), str(target)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout)

        source_after = {
            path.relative_to(STARTER).as_posix(): path.read_bytes()
            for path in STARTER.rglob("*")
            if path.is_file()
        }
        self.assertEqual(source_after, source_before)

    def test_rejects_an_invalid_pack_id_without_creating_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "work"
            parent.mkdir()
            target = parent / "invalid-pack"
            result = self.run_creator("Invalid Pack", target)

            self.assertEqual(result.returncode, 1)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("pack id must match", summary["errors"][0])
            self.assertFalse(target.exists())

    def test_refuses_to_overwrite_an_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "existing-company"
            target.mkdir()
            sentinel = target / "keep.txt"
            sentinel.write_text("user-owned\n", encoding="utf-8")
            result = self.run_creator("my-company", target)

            self.assertEqual(result.returncode, 1)
            summary = json.loads(result.stdout)
            self.assertIn("target already exists", summary["errors"][0])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned\n")
            self.assertEqual([path.name for path in target.iterdir()], ["keep.txt"])

    def test_requires_an_existing_parent_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing_parent = Path(temporary) / "missing"
            target = missing_parent / "my-company"
            result = self.run_creator("my-company", target)

            self.assertEqual(result.returncode, 1)
            summary = json.loads(result.stdout)
            self.assertIn("target parent is unavailable", summary["errors"][0])
            self.assertFalse(missing_parent.exists())

    def test_refuses_to_create_a_target_inside_the_shipped_starter(self) -> None:
        target = STARTER / "nested-company-test"
        self.assertFalse(target.exists())
        result = self.run_creator("my-company", target)

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertIn("outside the shipped starter", summary["errors"][0])
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
