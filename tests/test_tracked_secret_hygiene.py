import importlib.util
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

    def test_live_token_is_detected_without_becoming_a_static_fixture(self) -> None:
        token = "gh" + "p_" + ("A" * 40)
        findings = SCANNER.scan_text(Path("config.txt"), f"token={token}\n")
        self.assertEqual([("config.txt", 1, "GitHub token")], findings)
        self.assertNotIn(token, repr(findings))

    def test_live_named_assignment_is_detected(self) -> None:
        token = "Ab9_" + ("z" * 44)
        findings = SCANNER.scan_text(Path("config.txt"), f"CF_API_TOKEN={token}\n")
        self.assertEqual(
            [("config.txt", 1, "live-looking value assigned to CF_API_TOKEN")],
            findings,
        )
        self.assertNotIn(token, repr(findings))

    def test_placeholder_marker_inside_live_url_does_not_bypass_assignment_gate(
        self,
    ) -> None:
        value = "postgres://admin:S3cretPassword@demo.internal/prod"
        findings = SCANNER.scan_text(Path("config.txt"), f"DATABASE_URL={value}\n")

        self.assertEqual(
            [("config.txt", 1, "live-looking value assigned to DATABASE_URL")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_placeholder_expression_must_cover_the_entire_assignment_value(
        self,
    ) -> None:
        value = "${OPENAI_API_KEY}Ab9_" + ("z" * 40)

        findings = SCANNER.scan_text(
            Path("config.txt"), f"OPENAI_API_KEY={value}\n"
        )

        self.assertEqual(
            [("config.txt", 1, "live-looking value assigned to OPENAI_API_KEY")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_named_assignment_detects_long_lowercase_and_passphrase_values(self) -> None:
        cases = (
            ("CF_API_TOKEN", "abcdefghijklmnopqrstuvwxyzabcdefghijklmnop"),
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
        self.assertIn("does not scan Git history", security)


if __name__ == "__main__":
    unittest.main()
