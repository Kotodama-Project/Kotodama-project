"""Public package naming, single-source mapping, and private import boundary."""
import ast
import json
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"runtime", "kotodama_operator", "kotodama_control_plane", "ktdm"}


class PythonPackageContractTests(unittest.TestCase):
    def test_namespace_mapping_has_one_source_and_no_console_collision(self):
        package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(package["project"]["name"], "kotodama-core")
        self.assertEqual(package["project"]["scripts"], {"kotodama-core": "kotodama_core.cli:main"})
        self.assertEqual(package["tool"]["setuptools"]["packages"], ["kotodama_core", "kotodama_core.task_swarm"])
        self.assertEqual(package["tool"]["setuptools"]["package-dir"]["kotodama_core.task_swarm"], "runtime/task_swarm")
        node = json.loads((ROOT / "runtime/discord-template/package.json").read_text(encoding="utf-8"))
        self.assertIn("kotodama", node["bin"])
        self.assertTrue(set(node["bin"]).isdisjoint(package["project"]["scripts"]))
        self.assertEqual(package["project"]["dependencies"], [])

    def test_public_source_has_no_private_imports_or_dynamic_private_targets(self):
        files = list((ROOT / "python/src/kotodama_core").glob("*.py")) + list((ROOT / "runtime/task_swarm").glob("*.py"))
        for path in files:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name.split(".")[0] not in PRIVATE_NAMES for alias in node.names), path.name)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn((node.module or "").split(".")[0], PRIVATE_NAMES, path.name)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"}:
                    self.fail(f"unreviewed dynamic code/import in {path.name}")


if __name__ == "__main__":
    unittest.main()
