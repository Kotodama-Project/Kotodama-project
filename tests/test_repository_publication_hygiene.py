import hashlib
import importlib.util
import subprocess
import tempfile
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
            "python -B tools/check_workflow_references.py"
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
            workflow.index(install_command), workflow.index(workflow_reference_command)
        )
        self.assertLess(
            workflow.index(workflow_reference_command),
            workflow.index("python -m unittest discover -s tests -v"),
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
        self.assertIn("shopt -s nullglob", workflow)
        self.assertIn(".github/workflows/*.yml", workflow)
        self.assertIn(".github/workflows/*.yaml", workflow)
        self.assertIn('"$install_dir/actionlint" "${workflow_files[@]}"', workflow)

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

    def test_workflow_reference_gate_parses_supported_yaml_representations(
        self,
    ) -> None:
        mutable = "docker://vendor/tool:latest"
        cases = {
            "standard": f"      - uses: {mutable}\n",
            "quoted-key": f'      - "uses" : {mutable}\n',
            "spaced-key": f"      - uses : {mutable}\n",
            "flow-map": f"      - {{ name: mutable, uses: {mutable} }}\n",
        }

        for name, step in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workflows = root / ".github" / "workflows"
                workflows.mkdir(parents=True)
                (workflows / "candidate.yml").write_text(
                    "name: Candidate\n"
                    "on: push\n"
                    "jobs:\n"
                    "  verify:\n"
                    "    runs-on: ubuntu-latest\n"
                    "    steps:\n"
                    + step,
                    encoding="utf-8",
                )

                violations = WORKFLOW_SCANNER.scan_workflows(root)

                self.assertEqual(1, len(violations), violations)
                self.assertIn("Docker action image", violations[0][2])

    def test_workflow_reference_gate_accepts_structured_immutable_references(
        self,
    ) -> None:
        action_sha = "owner/action@" + ("a" * 40)
        docker_digest = "docker://vendor/tool@sha256:" + ("b" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            local_action = root / "local-action"
            workflows.mkdir(parents=True)
            local_action.mkdir()
            (workflows / "candidate.yml").write_text(
                "name: Candidate\n"
                "on: push\n"
                "jobs:\n"
                "  verify:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                f"      - 'uses' : {action_sha}\n"
                f"      - uses: >-\n          {docker_digest}\n"
                "      - { uses: ./local-action }\n",
                encoding="utf-8",
            )
            (local_action / "action.yml").write_text(
                "name: Local\n"
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                "    - run: echo ok\n"
                "      shell: bash\n",
                encoding="utf-8",
            )

            self.assertEqual([], WORKFLOW_SCANNER.scan_workflows(root))

    def test_workflow_reference_gate_covers_reusable_jobs_but_not_arbitrary_keys(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "candidate.yml").write_text(
                "name: Candidate\n"
                "on: push\n"
                "jobs:\n"
                "  reusable:\n"
                "    \"uses\" : owner/repository/.github/workflows/reuse.yml@v1\n"
                "  ordinary:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: 'echo uses: docker://vendor/tool:latest'\n"
                "        with: { uses: docker://vendor/tool:latest }\n",
                encoding="utf-8",
            )

            violations = WORKFLOW_SCANNER.scan_workflows(root)

            self.assertEqual(1, len(violations), violations)
            self.assertIn("full commit SHA", violations[0][2])

    def test_workflow_reference_gate_requires_digest_pinned_job_images(self) -> None:
        mutable = "vendor/runtime:latest"
        pinned = "vendor/runtime@sha256:" + ("b" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "candidate.yml").write_text(
                "name: Candidate\n"
                "on: push\n"
                "jobs:\n"
                "  mutable:\n"
                "    runs-on: ubuntu-latest\n"
                f"    container: {mutable}\n"
                "    services:\n"
                "      database:\n"
                f"        image: {mutable}\n"
                "    steps:\n"
                "      - run: echo no\n"
                "  pinned:\n"
                "    runs-on: ubuntu-latest\n"
                "    container:\n"
                f"      image: {pinned}\n"
                "    services:\n"
                f"      database: {{ image: {pinned} }}\n"
                "    steps:\n"
                "      - run: echo ok\n",
                encoding="utf-8",
            )

            violations = WORKFLOW_SCANNER.scan_workflows(root)

            self.assertEqual(2, len(violations), violations)
            self.assertTrue(
                all(
                    "container image" in violation
                    for _path, _line, violation in violations
                ),
                violations,
            )

    def test_workflow_reference_gate_scans_nested_composite_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            action = root / "actions" / "local"
            workflows.mkdir(parents=True)
            action.mkdir(parents=True)
            (workflows / "candidate.yml").write_text(
                "name: Candidate\n"
                "on: push\n"
                "jobs:\n"
                "  verify:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: ./actions/local\n",
                encoding="utf-8",
            )
            (action / "action.yml").write_text(
                "name: Local\n"
                "runs:\n"
                "  using: composite\n"
                "  steps:\n"
                "    - uses: owner/action@v1\n",
                encoding="utf-8",
            )

            violations = WORKFLOW_SCANNER.scan_workflows(root)

            self.assertEqual(1, len(violations), violations)
            self.assertEqual("actions/local/action.yml", violations[0][0])
            self.assertIn("full commit SHA", violations[0][2])

    def test_workflow_reference_gate_rejects_invalid_local_reusable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "caller.yml").write_text(
                "name: Caller\n"
                "on: push\n"
                "jobs:\n"
                "  reuse:\n"
                "    uses: ./outside.yml\n",
                encoding="utf-8",
            )

            violations = WORKFLOW_SCANNER.scan_workflows(root)

            self.assertEqual(1, len(violations), violations)
            self.assertIn("directly under .github/workflows", violations[0][2])

    def test_workflow_gate_scans_referenced_untracked_reusable_workflow(self) -> None:
        pinned = "owner/action@" + ("a" * 40)
        mutable = "owner/action@v1"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)

            def run_git(*arguments: str) -> None:
                completed = subprocess.run(
                    ["git", *arguments], cwd=root, capture_output=True, check=False
                )
                self.assertEqual(0, completed.returncode, completed.stderr.decode())

            caller = workflows / "caller.yml"
            caller.write_text(
                "name: Caller\n"
                "on: push\n"
                "jobs:\n"
                "  verify:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                f"      - uses: {pinned}\n",
                encoding="utf-8",
            )
            run_git("init", "--quiet")
            run_git("config", "user.name", "Test")
            run_git("config", "user.email", "test@example.invalid")
            run_git("add", ".")
            run_git("commit", "--quiet", "-m", "seed")

            caller.write_text(
                "name: Caller\n"
                "on: push\n"
                "jobs:\n"
                "  reuse:\n"
                "    uses: ./.github/workflows/untracked.yml\n",
                encoding="utf-8",
            )
            (workflows / "untracked.yml").write_text(
                "name: Reusable\n"
                "on: workflow_call\n"
                "jobs:\n"
                "  verify:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                f"      - uses: {mutable}\n",
                encoding="utf-8",
            )

            violations = WORKFLOW_SCANNER.scan_workflows(root)

            self.assertEqual(1, len(violations), violations)
            self.assertEqual(".github/workflows/untracked.yml", violations[0][0])
            self.assertIn("full commit SHA", violations[0][2])
            self.assertIn("[working tree]", violations[0][2])

    def test_workflow_reference_gate_scans_head_index_and_worktree(self) -> None:
        mutable = "docker://vendor/tool:latest"
        pinned = "docker://vendor/tool@sha256:" + ("b" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)

            def workflow(reference: str) -> str:
                return (
                    "name: Candidate\n"
                    "on: push\n"
                    "jobs:\n"
                    "  verify:\n"
                    "    runs-on: ubuntu-latest\n"
                    "    steps:\n"
                    f"      - uses: {reference}\n"
                )

            def run_git(*arguments: str) -> None:
                completed = subprocess.run(
                    ["git", *arguments], cwd=root, capture_output=True, check=False
                )
                self.assertEqual(0, completed.returncode, completed.stderr.decode())

            run_git("init", "--quiet")
            run_git("config", "user.name", "Test")
            run_git("config", "user.email", "test@example.invalid")
            head_path = workflows / "head.yml"
            index_path = workflows / "index.yaml"
            working_path = workflows / "working.yml"
            for path in (head_path, index_path, working_path):
                path.write_text(workflow(pinned), encoding="utf-8")
            head_path.write_text(workflow(mutable), encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "--quiet", "-m", "seed")

            head_path.write_text(workflow(pinned), encoding="utf-8")
            index_path.write_text(workflow(mutable), encoding="utf-8")
            run_git("add", str(index_path.relative_to(root)))
            index_path.write_text(workflow(pinned), encoding="utf-8")
            working_path.write_text(workflow(mutable), encoding="utf-8")

            violations = WORKFLOW_SCANNER.scan_workflows(root)

        paths = {path for path, _line, _violation in violations}
        self.assertEqual(
            {
                ".github/workflows/head.yml",
                ".github/workflows/index.yaml",
                ".github/workflows/working.yml",
            },
            paths,
        )

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
