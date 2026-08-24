import hashlib
import importlib.util
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEW_REPOSITORY = "https://github.com/Kotodama-Project/Kotodama-project"
OLD_REPOSITORY = "https://github.com/" + "dj-thank/" + "Kotodama-project"
WORKFLOW_SCANNER_PATH = ROOT / "tools" / "check_workflow_references.py"
WORKFLOW_SCANNER_SPEC = importlib.util.spec_from_file_location(
    "workflow_reference_hygiene", WORKFLOW_SCANNER_PATH
)
assert WORKFLOW_SCANNER_SPEC is not None and WORKFLOW_SCANNER_SPEC.loader is not None
WORKFLOW_SCANNER = importlib.util.module_from_spec(WORKFLOW_SCANNER_SPEC)
WORKFLOW_SCANNER_SPEC.loader.exec_module(WORKFLOW_SCANNER)


class RepositoryPublicationHygieneTests(unittest.TestCase):
    def tracked_text(self) -> str:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.split(b"\0")
        documents = []
        for relative_bytes in tracked:
            if not relative_bytes:
                continue
            relative = relative_bytes.decode("utf-8")
            documents.append((ROOT / relative).read_text(encoding="utf-8"))
        return "\n".join(documents)

    def test_public_policy_documents_are_linked_from_readme(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for relative in (
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "CODE_OF_CONDUCT.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(f"]({relative})", readme)

    def test_repository_is_explicitly_apache_2_0_licensed(self) -> None:
        license_bytes = (ROOT / "LICENSE").read_bytes()
        license_text = license_bytes.decode("utf-8")
        self.assertEqual(len(license_bytes), 11357)
        self.assertEqual(
            hashlib.sha256(license_bytes).hexdigest(),
            "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        )
        self.assertTrue(license_text.lstrip().startswith("Apache License\n"))
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("http://www.apache.org/licenses/", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)
        self.assertIn("Copyright [yyyy] [name of copyright owner]", license_text)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## License", readme)
        self.assertIn("[Apache License 2.0](LICENSE)", readme)
        self.assertIn("`Apache-2.0`", readme)

    def test_license_bytes_are_pinned_to_lf_on_every_checkout(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("LICENSE text eol=lf", attributes.splitlines())
        self.assertNotIn(b"\r\n", (ROOT / "LICENSE").read_bytes())

    def test_current_tree_uses_the_organization_repository_identity(self) -> None:
        tracked_text = self.tracked_text()
        self.assertNotIn(OLD_REPOSITORY, tracked_text)
        self.assertIn(NEW_REPOSITORY, tracked_text)

    def test_public_status_omits_the_private_runtime_identifier(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        self.assertNotIn("CT200", status)
        self.assertIn("private Voice runtime cutover attempt", status)

    def test_repository_validation_workflow_is_bounded_and_pinned(self) -> None:
        workflow = (ROOT / ".github/workflows/repository-validation.yml").read_text(
            encoding="utf-8"
        )
        smoke_command = "python -S -B tools/smoke_company_pack_review_chain.py"
        runtime_commands = (
            "python -S -B tools/validate_installation_lifecycle.py "
            "examples/installation-lifecycle/compose-minimum.json",
            "python -S -B tools/validate_installation_lifecycle.py "
            "examples/installation-lifecycle/proxmox-segmented.json",
            "python -S -B tools/validate_compose_minimum_skeleton.py "
            "runtime/compose-minimum",
        )
        install_command = (
            "python -m pip install --require-hashes -r requirements-ci.txt"
        )
        workflow_reference_command = (
            "python -S -B tools/check_workflow_references.py"
        )
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn(smoke_command, workflow)
        for runtime_command in runtime_commands:
            with self.subTest(runtime_command=runtime_command):
                self.assertIn(runtime_command, workflow)
                self.assertLess(workflow.index(runtime_command), workflow.index(install_command))
        self.assertIn(install_command, workflow)
        self.assertLess(workflow.index(smoke_command), workflow.index(install_command))
        self.assertIn(workflow_reference_command, workflow)
        self.assertLess(
            workflow.index(workflow_reference_command), workflow.index(install_command)
        )
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn(
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", workflow
        )
        self.assertIn(
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            workflow,
        )

    def test_actionlint_is_checksum_verified_outside_the_worktree(self) -> None:
        workflow = (ROOT / ".github/workflows/repository-validation.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('ACTIONLINT_VERSION: "1.7.12"', workflow)
        self.assertIn(
            'ACTIONLINT_SHA256: "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"',
            workflow,
        )
        self.assertIn('${RUNNER_TEMP}/actionlint.tar.gz', workflow)
        self.assertIn('${RUNNER_TEMP}/actionlint', workflow)
        self.assertIn("sha256sum -c -", workflow)
        self.assertIn('"$install_dir/actionlint" .github/workflows/*.yml', workflow)

    def test_all_external_actions_are_pinned_to_immutable_shas(self) -> None:
        self.assertEqual([], WORKFLOW_SCANNER.scan_workflows(ROOT))

    def test_workflow_reference_gate_rejects_mutable_docker_tags(self) -> None:
        action_sha = "owner/action@" + ("a" * 40)
        docker_digest = "docker://vendor/tool@sha256:" + ("b" * 64)

        for reference in ("./local-action", action_sha, docker_digest):
            with self.subTest(reference=reference):
                self.assertIsNone(WORKFLOW_SCANNER.reference_violation(reference))

        for reference in ("owner/action@v1", "docker://vendor/tool:latest"):
            with self.subTest(reference=reference):
                self.assertIsNotNone(WORKFLOW_SCANNER.reference_violation(reference))

    def test_ci_dependency_lock_is_hashed_current_and_public_safe(self) -> None:
        lock = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
        self.assertIn("jsonschema[format-nongpl]==4.26.0", lock)
        self.assertIn("idna==3.19", lock)
        self.assertIn("--hash=sha256:", lock)
        self.assertNotIn("C:\\Users\\", lock)
        self.assertNotIn("C:/Users/", lock)
        self.assertNotIn("/home/", lock)

    def test_dependabot_has_a_review_cooldown(self) -> None:
        dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertEqual(dependabot.count("default-days: 7"), 2)

    def test_dependency_review_is_pinned_and_bounded(self) -> None:
        dependency_review = (
            ROOT / ".github/workflows/dependency-review.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", dependency_review)
        self.assertIn(
            "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294",
            dependency_review,
        )
        self.assertIn("fail-on-severity: moderate", dependency_review)

    def test_codeql_advanced_workflow_does_not_conflict_with_default_setup(self) -> None:
        self.assertFalse((ROOT / ".github/workflows/codeql.yml").exists())


if __name__ == "__main__":
    unittest.main()
