import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "tools/check_tracked_secret_hygiene.py"
SPEC = importlib.util.spec_from_file_location("tracked_secret_hygiene", SCANNER_PATH)
assert SPEC is not None and SPEC.loader is not None
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)


class TrackedSecretHygieneTests(unittest.TestCase):
    def test_safe_placeholders_pass(self) -> None:
        text = (
            "OPENAI" + "_API_KEY=${OPENAI_API_KEY}\n"
            "GITHUB" + "_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path(".env.example"), text))

    def test_sensitive_filenames_are_blocked_but_templates_are_allowed(self) -> None:
        for name in (
            ".env",
            ".env.local",
            ".dev.vars",
            ".dev.vars.production",
            "server.pem",
            "credentials.prod.json",
            "terraform.tfstate",
            "terraform.tfstate.backup",
            ".terraform/providers/cache.bin",
            ".wrangler/state.json",
            "work/private-review.json",
        ):
            with self.subTest(name=name):
                self.assertTrue(SCANNER.sensitive_filename(Path(name)))
        for name in (
            ".env.example",
            ".env.sample",
            ".env.template",
            ".env.production.example",
            ".dev.vars.example",
            ".dev.vars.production.example",
        ):
            with self.subTest(name=name):
                self.assertFalse(SCANNER.sensitive_filename(Path(name)))

        for name in (
            "work/.env.example",
            ".terraform/.env.example",
            ".wrangler/.dev.vars.example",
        ):
            with self.subTest(name=name):
                self.assertTrue(SCANNER.sensitive_filename(Path(name)))

    def test_live_token_is_detected_without_becoming_a_static_fixture(self) -> None:
        token = "gh" + "p_" + ("A" * 40)
        findings = SCANNER.scan_text(Path("config.txt"), f"token={token}\n")
        self.assertEqual([("config.txt", 1, "GitHub token")], findings)
        self.assertNotIn(token, repr(findings))

    def test_live_named_assignment_is_detected(self) -> None:
        name = "CF_API" + "_TOKEN"
        token = "Ab9_" + ("z" * 44)
        findings = SCANNER.scan_text(Path("config.txt"), f"{name}={token}\n")
        self.assertEqual(
            [("config.txt", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(token, repr(findings))

    def test_placeholder_marker_inside_live_url_does_not_bypass_assignment_gate(
        self,
    ) -> None:
        name = "DATABASE" + "_URL"
        value = "postgres://admin:S3cretPassword@demo.internal/prod"
        findings = SCANNER.scan_text(Path("config.txt"), f"{name}={value}\n")

        self.assertEqual(
            [("config.txt", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_placeholder_expression_must_cover_the_entire_assignment_value(
        self,
    ) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "${" + name + "}Ab9_" + ("z" * 40)

        findings = SCANNER.scan_text(
            Path("config.txt"), f"{name}={value}\n"
        )

        self.assertEqual(
            [("config.txt", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_named_assignment_detects_literal_values(self) -> None:
        cases = (
            ("CF_API_TOKEN", "abcdefghijklmnopqrstuvwxyzabcdefghijklmnop"),
            ("CF_API_TOKEN", "abc123"),
            ("N8N_ENCRYPTION_KEY", "correct horse battery staple"),
        )
        for name, value in cases:
            with self.subTest(name=name):
                findings = SCANNER.scan_text(Path("config.txt"), f"{name}={value}\n")
                self.assertEqual(
                    [("config.txt", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_repository_database_password_assignments_are_detected(self) -> None:
        value = "correct horse battery staple"
        for name in (
            "KOTODAMA_COMPANY_DB_PASSWORD",
            "KOTODAMA_EVIDENCE_DB_PASSWORD",
            "POSTGRES_PASSWORD",
        ):
            with self.subTest(name=name):
                findings = SCANNER.scan_text(Path("config.txt"), f"{name}={value}\n")
                self.assertEqual(
                    [("config.txt", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_prefixed_environment_assignment_forms_are_detected(self) -> None:
        name = "OPENAI_API_KEY"
        value = "Ab9_" + ("z" * 44)
        lines = (
            f"- {name}={value}",
            f"$env:{name} = '{value}'",
            f"ENV {name}={value}",
            f"ENV {name} {value}",
            f"ARG {name}={value}",
            f"set {name}={value}",
            f"setx {name} {value}",
        )
        for line in lines:
            with self.subTest(prefix=line.split(name)[0]):
                findings = SCANNER.scan_text(Path("config.txt"), line + "\n")
                self.assertEqual(
                    [("config.txt", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_placeholder_references_must_match_the_entire_value(self) -> None:
        safe = (
            "env.OPENAI_API_KEY",
            "process.env.OPENAI_API_KEY",
            'os.environ["OPENAI_API_KEY"]',
            "secrets.OPENAI_API_KEY",
            "vars.OPENAI_API_KEY",
            "your-api-key",
            "{runtime_secret}",
        )
        for value in safe:
            with self.subTest(value=value):
                self.assertTrue(SCANNER.placeholder(value))

        for value in (
            "env.OPENAI_API_KEY-live-production-suffix",
            "process.env.OPENAI_API_KEY-live-production-suffix",
            "secrets.OPENAI_API_KEY-live-production-suffix",
            "vars.OPENAI_API_KEY-live-production-suffix",
            "hardcoded-comment-bypass-live-secret",
            "Tr0ub4dor.Horse.Battery.Staple",
        ):
            with self.subTest(value=value):
                self.assertFalse(SCANNER.placeholder(value))

    def test_shell_fallback_literals_are_not_placeholders(self) -> None:
        safe = "${POSTGRES_" + "PASSWORD:?set in private environment}"
        unsafe = "${POSTGRES_" + "PASSWORD:-ProdSecret2026}"

        self.assertTrue(SCANNER.placeholder(safe))
        self.assertFalse(SCANNER.placeholder(unsafe))
        findings = SCANNER.scan_text(
            Path("compose.yaml"), "POSTGRES_" + f'PASSWORD: "{unsafe}"\n'
        )
        self.assertEqual(
            [("compose.yaml", 1, "live-looking value assigned to POSTGRES_PASSWORD")],
            findings,
        )

    def test_compact_json_named_assignment_is_detected(self) -> None:
        value = "correct horse battery staple"
        text = '{"POSTGRES_' + 'PASSWORD":"' + value + '"}\n'

        findings = SCANNER.scan_text(Path("settings.json"), text)

        self.assertEqual(
            [("settings.json", 1, "live-looking value assigned to POSTGRES_PASSWORD")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_unquoted_flow_mapping_named_assignment_is_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        findings = SCANNER.scan_text(
            Path("settings.yaml"), "{" + name + ": " + value + "}\n"
        )

        self.assertEqual(
            [("settings.yaml", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_multiline_structured_and_equals_assignments_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = {
            "json": "{\n  \"" + name + "\":\n    \"" + value + "\"\n}\n",
            "split-json": (
                "{\n  \"" + name + "\"\n  :\n    \"" + value + "\"\n}\n"
            ),
            "split-json-inline-value": (
                "{\n  \"" + name + "\"\n  : \"" + value + "\"\n}\n"
            ),
            "yaml": name + ":\n  " + value + "\n",
            "explicit-yaml": "? " + name + "\n: " + value + "\n",
            "equals": "const " + name + " =\n  \"" + value + "\";\n",
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                findings = SCANNER.scan_text(Path("settings.txt"), text)
                self.assertEqual(
                    [
                        (
                            "settings.txt",
                            2
                            if label.startswith(("json", "split-json"))
                            else 1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_multiline_safe_reference_and_null_sibling_pass(self) -> None:
        name = "OPENAI_" + "API_KEY"
        safe_reference = name + ":\n  ${{ secrets." + name + " }}\n"
        safe_reference_after_comment = (
            name
            + ": # resolved by the private secret store\n  ${{ secrets."
            + name
            + " }}\n"
        )
        null_with_sibling = name + ":\nOTHER_SETTING: ordinary\n"
        split_null = (
            "{\n  \""
            + name
            + "\"\n  : null,\n  \"OTHER_SETTING\": true\n}\n"
        )

        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), safe_reference)
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(
                Path("settings.yaml"), safe_reference_after_comment
            ),
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), null_with_sibling)
        )
        self.assertEqual([], SCANNER.scan_text(Path("settings.json"), split_null))

    def test_multiline_scheme_relative_url_is_not_treated_as_a_comment(self) -> None:
        name = "DATABASE" + "_URL"
        value = "//user:SyntheticSecretValue2026@example.invalid/database"

        findings = SCANNER.scan_text(
            Path("settings.yaml"), name + ":\n  " + value + "\n"
        )

        self.assertEqual(
            [("settings.yaml", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_commented_multiline_assignment_start_is_ignored(self) -> None:
        name = "OPENAI_" + "API_KEY"
        text = "// " + name + " =\nordinaryCall()\n"

        self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

    def test_multiline_assignment_scans_continued_expression(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "-ProdSecret2026"
        text = (
            "const "
            + name
            + " =\n  secrets."
            + name
            + "\n  + \""
            + value
            + "\";\n"
        )

        findings = SCANNER.scan_text(Path("config.js"), text)

        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        ternary = (
            "const "
            + name
            + " =\n  secrets."
            + name
            + "\n  ? \""
            + value
            + "\"\n  : secrets."
            + name
            + "\n"
        )
        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), ternary),
        )

        with_comment = (
            "const "
            + name
            + " =\n  secrets."
            + name
            + "\n  // continue after this comment\n  + \""
            + value
            + "\";\n"
        )
        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), with_comment),
        )

    def test_yaml_document_boundaries_end_null_assignment(self) -> None:
        name = "OPENAI_" + "API_KEY"
        for marker in ("---", "..."):
            with self.subTest(marker=marker):
                text = name + ":\n" + marker + "\nOTHER_SETTING: ordinary\n"
                self.assertEqual(
                    [], SCANNER.scan_text(Path("settings.yaml"), text)
                )

    def test_json_semantic_scan_decodes_escaped_sensitive_key(self) -> None:
        name = "OPENAI_" + "API_KEY"
        escaped_name = "OPENAI_API_" + "\\u004b" + "EY"
        value = "SyntheticSecretValue2026"
        text = '{"' + escaped_name + '": "' + value + '"}\n'

        findings = SCANNER.scan_text(Path("settings.json"), text)

        self.assertEqual(
            [("settings.json", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        invalid = '{"' + escaped_name + '": "' + value + '",}\n'
        self.assertEqual(
            [("settings.json", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("settings.json"), invalid),
        )

    def test_yaml_scan_decodes_escaped_sensitive_key(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for escape in ("\\x4b", "\\u004b", "\\U0000004b"):
            with self.subTest(escape=escape):
                escaped_name = "OPENAI_API_" + escape + "EY"
                text = '"' + escaped_name + '":\n  "' + value + '"\n'

                findings = SCANNER.scan_text(Path("settings.yaml"), text)

                self.assertEqual(
                    [
                        (
                            "settings.yaml",
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_deep_and_repeated_escaped_json_keys_fail_closed(self) -> None:
        name = "OPENAI_" + "API_KEY"
        escaped_name = "OPENAI_API_" + "\\u004b" + "EY"
        value = "SyntheticSecretValue2026"
        deep = (
            "[" * 1100
            + '{"'
            + escaped_name
            + '":"'
            + value
            + '"}'
            + "]" * 1100
        )
        self.assertEqual(
            [("settings.json", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("settings.json"), deep),
        )

        entries = [f'  "{escaped_name}": null' for _ in range(99)]
        entries.append(f'  "{escaped_name}": "{value}"')
        repeated = "{\n" + ",\n".join(entries) + "\n}\n"
        self.assertEqual(
            [("settings.json", 101, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("settings.json"), repeated),
        )

    def test_regex_api_does_not_exempt_later_named_assignment(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        text = (
            're.compile("x"); settings={"'
            + name
            + '":"'
            + value
            + '"}\n'
        )

        findings = SCANNER.scan_text(Path("detector.py"), text)

        self.assertEqual(
            [("detector.py", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_inline_equals_named_assignments_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        lines = (
            f'prefix = 1; {name} = "{value}"',
            f'config.{name}="{value}"',
            f'const {name} = "{value}"',
        )
        for line in lines:
            with self.subTest(line=line.split(value)[0]):
                findings = SCANNER.scan_text(Path("config.js"), line + "\n")
                self.assertEqual(
                    [("config.js", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_inline_placeholder_must_cover_the_entire_expression(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        text = f'prefix = 1; {name} = "placeholder" + "{value}"\n'

        findings = SCANNER.scan_text(Path("config.js"), text)

        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_properties_whitespace_assignment_remains_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"

        findings = SCANNER.scan_text(
            Path("application.properties"), f"{name} {value}\n"
        )

        self.assertEqual(
            [
                (
                    "application.properties",
                    1,
                    f"live-looking value assigned to {name}",
                )
            ],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_comparison_and_arrow_operators_are_not_assignments(self) -> None:
        name = "OPENAI_" + "API_KEY"
        for operator in ("==", "===", "!=", "<=", ">=", "=>", "=~"):
            with self.subTest(operator=operator):
                self.assertEqual(
                    [],
                    SCANNER.scan_text(
                        Path("config.js"), f'{name} {operator} "ordinary"\n'
                    ),
                )

    def test_shell_parameter_defaults_and_assignments_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for operator in (":-", "-", ":=", "=", ":+", "+"):
            with self.subTest(operator=operator):
                text = "echo ${" + name + operator + value + "}\n"
                findings = SCANNER.scan_text(Path("script.sh"), text)
                self.assertEqual(
                    [("script.sh", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        nested = "echo ${" + name + ":-${OTHER:-" + value + "}}\n"
        self.assertEqual(
            [("script.sh", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("script.sh"), nested),
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(
                Path("script.sh"), "echo ${" + name + ":?set privately}\n"
            ),
        )

    def test_complete_private_key_block_is_detected(self) -> None:
        begin = "-----BEGIN " + "PRIVATE KEY-----\n"
        end = "-----END " + "PRIVATE KEY-----\n"
        private_key = begin + ((("A" * 64) + "\n") * 3) + end
        findings = SCANNER.scan_text(Path("private.txt"), private_key)
        self.assertEqual([("private.txt", 1, "private key block")], findings)

    def test_encrypted_pkcs8_private_key_block_is_detected(self) -> None:
        begin = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----\n"
        end = "-----END " + "ENCRYPTED PRIVATE KEY-----\n"
        private_key = begin + ((("A" * 64) + "\n") * 3) + end

        findings = SCANNER.scan_text(Path("private.txt"), private_key)

        self.assertEqual([("private.txt", 1, "private key block")], findings)

    def test_private_key_header_is_detected_even_when_the_block_is_incomplete(
        self,
    ) -> None:
        private_key = "-----BEGIN " + "PRIVATE KEY-----\n" + ("A" * 48)

        findings = SCANNER.scan_text(Path("private.txt"), private_key)

        self.assertEqual([("private.txt", 1, "private key block")], findings)

    def test_openpgp_private_key_armor_is_detected(self) -> None:
        private_key = (
            "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\n" + ("A" * 96)
        )

        findings = SCANNER.scan_text(Path("private.txt"), private_key)

        self.assertEqual([("private.txt", 1, "private key block")], findings)

    def test_putty_private_key_file_and_header_are_detected(self) -> None:
        self.assertTrue(SCANNER.sensitive_filename(Path("deploy.ppk")))
        header = "PuTTY-User-Key-" + "File-3: ssh-rsa\n"

        findings = SCANNER.scan_text(Path("private.txt"), header)

        self.assertEqual([("private.txt", 1, "private key block")], findings)

    def test_repository_scans_head_index_worktree_and_utf16_snapshots(self) -> None:
        name = "CF_API" + "_TOKEN"
        value = "abcdefghijklmnopqrstuvwxyzabcdefghijklmnop"
        placeholder = "${CF_API_TOKEN}"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def run_git(*arguments: str) -> None:
                completed = subprocess.run(
                    ["git", *arguments], cwd=root, capture_output=True, check=False
                )
                self.assertEqual(0, completed.returncode, completed.stderr.decode())

            run_git("init", "--quiet")
            run_git("config", "user.name", "Test")
            run_git("config", "user.email", "test@example.invalid")
            (root / "head.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            (root / "index.txt").write_text(
                f"{name}={placeholder}\n", encoding="utf-8"
            )
            (root / "working.txt").write_text(
                f"{name}={placeholder}\n", encoding="utf-8"
            )
            (root / "utf16.txt").write_text(
                f"{name}={value}\n", encoding="utf-16"
            )
            (root / "latin1.properties").write_bytes(
                ("# café\n" + f"{name}={value}\n").encode("latin-1")
            )
            run_git("add", ".")
            run_git("commit", "--quiet", "-m", "seed")

            (root / "head.txt").write_text(
                f"{name}={placeholder}\n", encoding="utf-8"
            )
            (root / "index.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            run_git("add", "index.txt")
            (root / "index.txt").write_text(
                f"{name}={placeholder}\n", encoding="utf-8"
            )
            (root / "working.txt").write_text(
                f"{name}={value}\n", encoding="utf-8"
            )

            findings, tracked, text_files = SCANNER.scan_repository(root)

        paths = {path for path, _line, detector in findings if "CF_API_TOKEN" in detector}
        self.assertEqual(
            {"head.txt", "index.txt", "working.txt", "utf16.txt"}, paths
        )
        self.assertTrue(
            any(
                path == "latin1.properties" and "not UTF-8" in detector
                for path, _line, detector in findings
            ),
            findings,
        )
        self.assertEqual(5, tracked)
        self.assertGreaterEqual(text_files, 4)
        self.assertNotIn(value, repr(findings))

    def test_current_tracked_tree_passes(self) -> None:
        findings, tracked, text_files = SCANNER.scan_repository(ROOT)
        self.assertEqual([], findings)
        self.assertGreater(tracked, 0)
        self.assertGreater(text_files, 0)

    def test_repository_wires_gate_before_dependency_installation(self) -> None:
        workflow = (ROOT / ".github/workflows/repository-validation.yml").read_text(
            encoding="utf-8"
        )
        command = "python -S -B tools/check_tracked_secret_hygiene.py"
        install = "python -m pip install --require-hashes -r requirements-ci.txt"
        self.assertIn(command, workflow)
        self.assertLess(workflow.index(command), workflow.index(install))

    def test_ignore_and_policy_contracts_are_documented(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            ".env", ".env.*", "!.env.example", "!.env.sample", "!.env.template",
            "*.pem", "*.key", "*.p12", "*.pfx", "credentials.json",
            "service-account*.json", "service_account*.json", "id_rsa", "id_ed25519",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

        command = "python -S -B tools/check_tracked_secret_hygiene.py"
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(command, contributing)
        self.assertIn(command, security)
        self.assertIn("current tracked tree", security)
        self.assertIn("does not scan history older than HEAD", security)


if __name__ == "__main__":
    unittest.main()
