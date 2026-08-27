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

    def test_safe_placeholders_allow_format_comments(self) -> None:
        name = "OPENAI_" + "API_KEY"
        env_text = name + "=${" + name + "} # injected at runtime\n"
        yaml_text = (
            name
            + ": ${{ secrets."
            + name
            + " }} # injected at runtime\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path(".env.example"), env_text)
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), yaml_text)
        )

        quoted_live = name + '="Synthetic # Secret Value" # local only\n'
        self.assertEqual(
            [
                (
                    ".env.example",
                    1,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(Path(".env.example"), quoted_live),
        )

        non_comment_suffix = name + "=${" + name + "} # literal suffix\n"
        for filename in ("notes.md", "settings.properties"):
            with self.subTest(filename=filename):
                self.assertEqual(
                    [
                        (
                            filename,
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    SCANNER.scan_text(Path(filename), non_comment_suffix),
                )

        for suffix in ("// runtime", "/* runtime */"):
            with self.subTest(hcl_comment=suffix):
                hcl = name + ' = "<injected-at-runtime>" ' + suffix + "\n"
                self.assertEqual(
                    [], SCANNER.scan_text(Path("settings.hcl"), hcl)
                )

        self.assertEqual(
            [],
            SCANNER.scan_text(
                Path("config.go"),
                "var " + name + ' = os.Getenv("' + name + '")\n',
            ),
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(
                Path("main.tf"), name + " = var.openai_api_key\n"
            ),
        )

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

        value = "SyntheticSecretValue2026"
        after_embedded_indicator = (
            "description: ordinary-'text\n"
            + "- {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [
                (
                    "after-indicator.yaml",
                    2,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(
                Path("after-indicator.yaml"), after_embedded_indicator
            ),
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), null_with_sibling)
        )
        self.assertEqual([], SCANNER.scan_text(Path("settings.json"), split_null))

        safe_block = name + ": >-\n  ${{ secrets." + name + " }}\n"
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), safe_block)
        )

        empty_block = name + ": >-\nOTHER_SETTING: ordinary\n"
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), empty_block)
        )

        next_item = (
            "- name: "
            + name
            + "\n- other: ordinary\n  value: "
            + value
            + "\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), next_item)
        )

        unrelated_mapping = (
            "entry:\n  name: "
            + name
            + "\nother:\n  value: "
            + value
            + "\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), unrelated_mapping)
        )

        unsafe_block = name + ": |2-\n    " + value + "\n"
        findings = SCANNER.scan_text(Path("settings.yaml"), unsafe_block)
        self.assertEqual(
            [("settings.yaml", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        block_hash_literal = (
            name + ": >-\n  ${" + name + "} # " + value + "\n"
        )
        hash_findings = SCANNER.scan_text(
            Path("settings.yaml"), block_hash_literal
        )
        self.assertEqual(
            [("settings.yaml", 1, f"live-looking value assigned to {name}")],
            hash_findings,
        )
        self.assertNotIn(value, repr(hash_findings))

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

    def test_structured_environment_entries_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = {
            "settings.yaml": (
                "- name: " + name + "\n  value: " + value + "\n"
            ),
            "flow.yaml": "- {name: " + name + ", value: " + value + "}\n",
            "reverse-flow.yaml": (
                "- {value: " + value + ", name: " + name + "}\n"
            ),
            "flow-extra-before-name.yaml": (
                "- {value: "
                + value
                + ", other: ordinary, name: "
                + name
                + "}\n"
            ),
            "flow-extra-before-value.yaml": (
                "- {name: "
                + name
                + ", other: ordinary, value: "
                + value
                + "}\n"
            ),
            "flow-nested-extra-before-name.yaml": (
                "- {value: "
                + value
                + ", metadata: {enabled: true}, name: "
                + name
                + "}\n"
            ),
            "flow-nested-extra-before-value.yaml": (
                "- {name: "
                + name
                + ", metadata: {enabled: true}, value: "
                + value
                + "}\n"
            ),
            "flow-quoted-brace-extra.yaml": (
                '- {name: '
                + name
                + ', description: "closing } brace", value: '
                + value
                + "}\n"
            ),
            "flow-escaped-field-keys.yaml": (
                '- {"na\\u006de": "'
                + name
                + '", "val\\u0075e": "'
                + value
                + '"}\n'
            ),
            "multiline-flow.yaml": (
                "- {value: " + value + ",\n  name: " + name + "}\n"
            ),
            "multiline-flow-reverse.yaml": (
                "- {name: " + name + ",\n  value: " + value + "}\n"
            ),
            "multiline-flow-comment.yaml": (
                "- {name: "
                + name
                + ", # ignored } brace\n  value: "
                + value
                + "}\n"
            ),
            "cr-only-flow-comment.yaml": (
                "- {name: "
                + name
                + ", # comment\r  value: "
                + value
                + "}\r"
            ),
            "flow-nbsp-hash.yaml": (
                "- {name: "
                + name
                + ", value: <injected-at-runtime>\u00a0#"
                + value
                + "}\n"
            ),
            "settings.json": (
                '{"name":"' + name + '","value":"' + value + '"}\n'
            ),
        }
        for filename, text in cases.items():
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        after_plain_apostrophe = (
            "description: it's ordinary\n"
            + "- {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [
                (
                    "after-apostrophe.yaml",
                    2,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(
                Path("after-apostrophe.yaml"), after_plain_apostrophe
            ),
        )

        escaped_block_fields = (
            '- "na\\u006de": '
            + name
            + '\n  "val\\u0075e": '
            + value
            + "\n"
        )
        self.assertEqual(
            [
                (
                    "escaped-block.yaml",
                    1,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(Path("escaped-block.yaml"), escaped_block_fields),
        )

        for scalar_property in ("&s", "!!str"):
            with self.subTest(scalar_property=scalar_property):
                block_property = (
                    "- name: "
                    + scalar_property
                    + " "
                    + name
                    + "\n  value: "
                    + value
                    + "\n"
                )
                flow_property = (
                    "- {name: "
                    + scalar_property
                    + " "
                    + name
                    + ", value: "
                    + value
                    + "}\n"
                )
                for filename, text in (
                    ("property-block.yaml", block_property),
                    ("property-flow.yaml", flow_property),
                ):
                    self.assertEqual(
                        [
                            (
                                filename,
                                1,
                                f"live-looking value assigned to {name}",
                            )
                        ],
                        SCANNER.scan_text(Path(filename), text),
                    )

                multiline_property = (
                    "- name: "
                    + scalar_property
                    + "\n    "
                    + name
                    + "\n  value: "
                    + value
                    + "\n"
                )
                self.assertEqual(
                    [
                        (
                            "property-multiline.yaml",
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    SCANNER.scan_text(
                        Path("property-multiline.yaml"), multiline_property
                    ),
                )

        merge_value = (
            "common: &common {value: "
            + value
            + "}\nentry: {name: "
            + name
            + ", <<: *common}\n"
        )
        merge_name = (
            "common: &common {name: "
            + name
            + "}\nentry: {<<: *common, value: "
            + value
            + "}\n"
        )
        for label, text in (("merge-value", merge_value), ("merge-name", merge_name)):
            filename = label + ".yaml"
            with self.subTest(merge=label):
                self.assertEqual(
                    [
                        (
                            filename,
                            2,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    SCANNER.scan_text(Path(filename), text),
                )

        block_merge_value = (
            "common: &common\n  value: "
            + value
            + "\nentry:\n  <<: *common\n  name: "
            + name
            + "\n"
        )
        block_merge_name = (
            "common: &common\n  name: "
            + name
            + "\nentry:\n  <<: *common\n  value: "
            + value
            + "\n"
        )
        for label, text in (
            ("block-merge-value", block_merge_value),
            ("block-merge-name", block_merge_name),
        ):
            filename = label + ".yaml"
            with self.subTest(block_merge=label):
                self.assertEqual(
                    [
                        (
                            filename,
                            4,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    SCANNER.scan_text(Path(filename), text),
                )

        scalar_alias_block = (
            "secret_name: &secret_name "
            + name
            + "\n- name: *secret_name\n  value: "
            + value
            + "\n"
        )
        scalar_alias_flow = (
            "secret_name: &secret_name "
            + name
            + "\n- {name: *secret_name, value: "
            + value
            + "}\n"
        )
        for filename, text in (
            ("alias-block.yaml", scalar_alias_block),
            ("alias-flow.yaml", scalar_alias_flow),
        ):
            self.assertEqual(
                [
                    (
                        filename,
                        2,
                        f"live-looking value assigned to {name}",
                    )
                ],
                SCANNER.scan_text(Path(filename), text),
            )

        flow_collection_alias = (
            "names: [&secret_name "
            + name
            + "]\n- name: *secret_name\n  value: "
            + value
            + "\n"
        )
        self.assertEqual(
            [
                (
                    "flow-alias.yaml",
                    2,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(Path("flow-alias.yaml"), flow_collection_alias),
        )

        reverse_block = "- value: " + value + "\n  name: " + name + "\n"
        self.assertEqual(
            [
                (
                    "reverse-block.yaml",
                    2,
                    f"live-looking value assigned to {name}",
                )
            ],
            SCANNER.scan_text(Path("reverse-block.yaml"), reverse_block),
        )

        value_from = (
            "- name: "
            + name
            + "\n  valueFrom:\n    secretKeyRef:\n      name: private\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), value_from)
        )
        reverse_value_from = (
            "- valueFrom:\n    secretKeyRef:\n      name: private\n  name: "
            + name
            + "\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), reverse_value_from)
        )

        canonical_sequence_scalar = (
            "documentation:\n  - |-\n    {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("settings.yaml"), canonical_sequence_scalar),
        )

        escaped_name = "OPENAI_API_" + "\\u004b" + "EY"
        escaped = (
            '- name: "'
            + escaped_name
            + '"\n  value: "'
            + value
            + '"\n'
        )
        self.assertEqual(
            [("settings.yaml", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("settings.yaml"), escaped),
        )

        safe_block = (
            "- name: "
            + name
            + "\n  value: >-\n    ${{ secrets."
            + name
            + " }}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), safe_block)
        )

        empty_structured_block = (
            "- name: "
            + name
            + "\n  value: >-\n- name: OTHER_SETTING\n  value: ordinary\n"
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("settings.yaml"), empty_structured_block),
        )

        safe_flow = (
            "- {name: "
            + name
            + ", metadata: {enabled: true}, value: ${{ secrets."
            + name
            + " }}}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), safe_flow)
        )

        separate_flow_records = (
            "- {name: " + name + "}\n- {value: " + value + "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), separate_flow_records)
        )

        commented_flow_record = (
            "# {name: " + name + ", value: " + value + "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), commented_flow_record)
        )

        single_quoted_escape_key = (
            "- {'na\\u006de': "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("settings.yaml"), single_quoted_escape_key),
        )

        flow_example_block = (
            "documentation: |-\n  {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), flow_example_block)
        )

        flow_example_sequence = (
            "documentation:\n  - |-\n      {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("settings.yaml"), flow_example_sequence),
        )

        nested_unrelated_value = (
            "- {name: "
            + name
            + ", metadata: {other: ordinary, value: "
            + value
            + "}}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), nested_unrelated_value)
        )

        flow_value_from = (
            "- {metadata: {enabled: true}, name: "
            + name
            + ", valueFrom: {secretKeyRef: {name: private, key: token}}}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), flow_value_from)
        )

        merge_override = (
            "common: &common\n  value: "
            + value
            + "\nentry:\n  <<: *common\n  name: "
            + name
            + "\n  value: ${{ secrets."
            + name
            + " }}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("settings.yaml"), merge_override)
        )

    def test_commented_multiline_assignment_start_is_ignored(self) -> None:
        name = "OPENAI_" + "API_KEY"
        text = "// " + name + " =\nordinaryCall()\n"

        self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))
        block = "/*\n" + name + " =\n*/\nordinaryCall()\n"
        self.assertEqual([], SCANNER.scan_text(Path("config.js"), block))
        for suffix in (".h", ".hh", ".hpp", ".hxx"):
            with self.subTest(header=suffix):
                self.assertEqual(
                    [], SCANNER.scan_text(Path("config" + suffix), block)
                )

        value = "SyntheticSecretValue2026"
        hcl_heredoc = (
            "description = <<-EOT\n/* literal text\nEOT\n"
            + name
            + " =\n  \""
            + value
            + "\"\n"
        )
        self.assertEqual(
            [("settings.hcl", 4, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("settings.hcl"), hcl_heredoc),
        )

        php_heredoc = (
            "<?php\n$description = <<<'EOT'\n/* literal text\nEOT;\n$"
            + name
            + " =\n  \""
            + value
            + "\";\n"
        )
        self.assertEqual(
            [("config.php", 5, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.php"), php_heredoc),
        )

        php_array_heredoc = (
            "<?php\n$values = [\n<<<'EOT'\n/* literal text\nEOT,\n];\n$"
            + name
            + " =\n  \""
            + value
            + "\";\n"
        )
        self.assertEqual(
            [("array.php", 7, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("array.php"), php_array_heredoc),
        )

        cr_php_heredoc = php_heredoc.replace("\n", "\r")
        self.assertEqual(
            [("cr.php", 5, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("cr.php"), cr_php_heredoc),
        )

        php_define_with_operator = (
            "<?php\n$values = [\n<<<'EOT'\n/* literal text\nEOT,\n];\n$"
            + name
            + " =\n  \""
            + value
            + "\";\n"
        )
        self.assertEqual(
            [("punctuation.php", 7, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("punctuation.php"), php_define_with_operator),
        )

        nested = (
            "/* outer\n/* nested */\n"
            + name
            + " =\nreturn true;\n*/\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.rs"), nested))
        self.assertEqual([], SCANNER.scan_text(Path("migration.sql"), nested))

        javascript_regex = (
            "const expression = /[/*]/\n"
            + name
            + " =\n  \""
            + value
            + "\"\n"
        )
        self.assertEqual(
            [("config.js", 2, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), javascript_regex),
        )

        c_line_splice = (
            "/* comment *\\\n/\n"
            + name
            + " =\n  \""
            + value
            + "\"\n"
        )
        self.assertEqual(
            [("config.c", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.c"), c_line_splice),
        )

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

        split_operator = (
            name
            + "\n= secrets."
            + name
            + "\n+ \""
            + value
            + "\";\n"
        )
        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), split_operator),
        )

    def test_bracketed_named_assignments_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            'process.env["' + name + '"] = "' + value + '"\n',
            "process.env[`" + name + "`] = \"" + value + "\"\n",
            'process.env["' + name + '"] =\n  "' + value + '"\n',
            'process.env["' + name + '"]\n=\n  "' + value + '"\n',
            (
                "process.env[\n  \""
                + name
                + "\"\n] = \""
                + value
                + "\"\n"
            ),
            (
                'process.env["'
                + name
                + '"] /* comment */ = "'
                + value
                + '"\n'
            ),
            (
                'process.env["'
                + name
                + '"] // comment\n= "'
                + value
                + '"\n'
            ),
        )
        for text in cases:
            with self.subTest(lines=len(text.splitlines())):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        reference = 'environment["' + name + '"] = company_secret\n'
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), reference))
        multiline_reference = (
            'environment["' + name + '"] =\n  company_secret\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.py"), multiline_reference)
        )

        indexed_reference = (
            'process.env["'
            + name
            + '"] = secrets["'
            + name
            + '"]\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.js"), indexed_reference)
        )

        dotted_indexed_reference = (
            "process.env."
            + name
            + ' = secrets["'
            + name
            + '"]\n'
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("config.js"), dotted_indexed_reference),
        )

        for reference_value in (
            "secrets." + name,
            'secrets["' + name + '"]',
        ):
            with self.subTest(outer_array=reference_value):
                outer_array = (
                    "const values = [process.env."
                    + name
                    + " = "
                    + reference_value
                    + "]\n"
                )
                self.assertEqual(
                    [], SCANNER.scan_text(Path("config.js"), outer_array)
                )

        callable_literal = (
            'process.env["'
            + name
            + '"] = String("'
            + value
            + '")\n'
        )
        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), callable_literal),
        )

        lookup = name + ' = os.getenv("' + name + '")\n'
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), lookup))
        terminated_lookup = name + ' = System.getenv("' + name + '");\n'
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.java"), terminated_lookup)
        )

    def test_go_environment_setter_calls_detect_literal_values(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        direct = 'os.Setenv("' + name + '", "' + value + '")\n'
        findings = SCANNER.scan_text(Path("config.go"), direct)
        self.assertEqual(
            [("config.go", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        controls = (
            '// os.Setenv("' + name + '", "' + value + '")\n',
            '/* os.Setenv("' + name + '", "' + value + '") */\n',
            'var source = "os.Setenv(\\"' + name + '\\", \\"' + value + '\\")"\n',
            'var source = `os.Setenv("' + name + '", "' + value + '")`\n',
            'os.Setenv("' + name + '", os.Getenv("' + name + '"))\n',
            'os.Setenv("' + name + '", "${' + name + '}")\n',
            'os.Setenv("OTHER", "' + value + '")\n',
            'os.Setenv(name, "' + value + '")\n',
        )
        for text in controls:
            with self.subTest(prefix=text[:20]):
                self.assertEqual([], SCANNER.scan_text(Path("config.go"), text))

    def test_environment_setter_calls_allow_whitespace_equivalent_comments(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            ("config.c", f'setenv /* gap */ ("{name}", "{value}", 1);\n'),
            ("config.cpp", f'setenv /* gap */ ("{name}", "{value}", 1);\n'),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable /* gap */ ("{name}", "{value}");\n',
            ),
            ("config.go", f'os.Setenv /* gap */ ("{name}", "{value}")\n'),
            (
                "config.rs",
                f'std::env::set_var /* gap */ ("{name}", "{value}");\n',
            ),
            ("config.swift", f'setenv /* gap */ ("{name}", "{value}", 1)\n'),
        )
        for filename, text in cases:
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_environment_setter_calls_allow_comments_inside_argument_lists(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        c_family = (
            (
                "config.c",
                f'setenv( /* key\n */ "{name}" /* separator */, /* value */ "{value}", 1);\n',
            ),
            (
                "config.cpp",
                f'setenv( /* key */ "{name}" /* separator */, /* value */ "{value}", 1);\n',
            ),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable( /* key */ "{name}" /* separator */, /* value */ "{value}");\n',
            ),
            (
                "config.go",
                f'os.Setenv( /* key */ "{name}" /* separator */, /* value */ "{value}")\n',
            ),
            (
                "config.rs",
                f'std::env::set_var( /* key */ "{name}" /* separator */, /* value */ "{value}");\n',
            ),
            (
                "config.swift",
                f'setenv( /* key */ "{name}" /* separator */, /* value */ "{value}", 1)\n',
            ),
        )
        python = (
            "os.putenv(\n"
            f"  # key\n  \"\"\"{name}\"\"\"\n"
            "  # separator\n  ,\n"
            f"  # value\n  \"\"\"{value}\"\"\"\n"
            ")\n"
        )
        for filename, text in (*c_family, ("config.py", python)):
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_environment_setter_calls_detect_static_language_literals(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                "config.cpp",
                f'setenv(R"({name})", R"({value})", 1);\n',
            ),
            (
                "config.cpp",
                f'setenv("OPENAI_" "API_KEY", "Synthetic" "SecretValue2026", 1);\n',
            ),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable(@"{name}", @"{value}");\n',
            ),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable("""{name}""", """{value}""");\n',
            ),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable($"{name}", $"{value}");\n',
            ),
            ("config.py", f'os.putenv("""{name}""", """{value}""")\n'),
            (
                "config.py",
                f'os.putenv("OPENAI_" "API_KEY", "Synthetic" "SecretValue2026")\n',
            ),
            (
                "config.py",
                f'os.putenv(f"{name}", f"{value}")\n',
            ),
            (
                "config.rs",
                f'std::env::set_var(r#"{name}"#, r#"{value}"#);\n',
            ),
            ("config.swift", f'setenv(#"{name}"#, #"{value}"#, 1)\n'),
            (
                "config.swift",
                f'setenv("""{name}""", """{value}""", 1)\n',
            ),
        )
        for filename, text in cases:
            with self.subTest(filename=filename, literal=text.split("(", 1)[1][:12]):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        dynamic_controls = (
            (
                "config.cs",
                'Environment.SetEnvironmentVariable($"OPENAI_{suffix}", $"{value}");\n',
            ),
            ("config.py", 'os.putenv(f"OPENAI_{suffix}", f"{value}")\n'),
            (
                "config.swift",
                'setenv(#"OPENAI_\\#(suffix)"#, #"SyntheticSecretValue2026"#, 1)\n',
            ),
        )
        for filename, text in dynamic_controls:
            with self.subTest(dynamic=filename):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_environment_setter_static_literals_preserve_internal_delimiters(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = 'Synthetic "quoted", (paren) SecretValue2026'
        cases = (
            (
                "config.cpp",
                f'setenv(R"tag({name})tag", R"tag({value})tag", 1);\n',
            ),
            (
                "config.rs",
                f'std::env::set_var(r##"{name}"##, r##"{value}"##);\n',
            ),
            ("config.py", f'os.putenv("""{name}""", """{value}""")\n'),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable("""{name}""", """{value}""");\n',
            ),
            (
                "config.swift",
                f'setenv("""{name}""", """{value}""", 1)\n',
            ),
        )
        for filename, text in cases:
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_csharp_fully_qualified_environment_setter_calls_detect_literals(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for qualifier in ("System.", "global::System."):
            text = (
                f'{qualifier}Environment.SetEnvironmentVariable("{name}", "{value}");\n'
            )
            with self.subTest(qualifier=qualifier):
                findings = SCANNER.scan_text(Path("config.cs"), text)
                self.assertEqual(
                    [("config.cs", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_csharp_named_environment_setter_arguments_are_bounded(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        target = "EnvironmentVariableTarget.Process"
        positives = (
            (
                f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}");\n',
                1,
            ),
            (
                f'Environment.SetEnvironmentVariable(value: "{value}", variable: "{name}");\n',
                1,
            ),
            (
                f'Environment.SetEnvironmentVariable(target: {target}, value: "{value}", variable: "{name}");\n',
                1,
            ),
        )
        for text, line in positives:
            with self.subTest(positive=text[:32]):
                findings = SCANNER.scan_text(Path("config.cs"), text)
                self.assertEqual(
                    [("config.cs", line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            f'Environment.SetEnvironmentVariable(variable: "{name}", value: secretValue);\n',
            f'Environment.SetEnvironmentVariable(name: "{name}", value: "{value}");\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", variable: "OTHER", value: "{value}");\n',
            f'Environment.SetEnvironmentVariable(Variable: "{name}", Value: "{value}");\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", target: target);\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", target: "Process");\n',
        )
        for text in negatives:
            with self.subTest(negative=text[:32]):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), text))

    def test_csharp_mixed_positional_named_setter_arguments_are_bounded(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        target = "EnvironmentVariableTarget.Process"
        positives = (
            f'Environment.SetEnvironmentVariable("{name}", value: "{value}");\n',
            f'Environment.SetEnvironmentVariable("{name}", value: "{value}", target: {target});\n',
            f'Environment.SetEnvironmentVariable("{name}", target: {target}, value: "{value}");\n',
            f'Environment.SetEnvironmentVariable("{name}", "{value}", target: {target});\n',
        )
        for text in positives:
            with self.subTest(positive=text[:36]):
                findings = SCANNER.scan_text(Path("config.cs"), text)
                self.assertEqual(
                    [("config.cs", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            f'Environment.SetEnvironmentVariable(value: "{value}", "{name}");\n',
            f'Environment.SetEnvironmentVariable("{name}", value: dynamicValue);\n',
            f'Environment.SetEnvironmentVariable("{name}", value: "{value}", target: dynamicTarget);\n',
            f'Environment.SetEnvironmentVariable("{name}", value: "{value}", value: "OTHER");\n',
            f'Environment.SetEnvironmentVariable("{name}", variable: "OTHER", value: "{value}");\n',
        )
        for text in negatives:
            with self.subTest(negative=text[:36]):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), text))

    def test_csharp_named_prefixes_allow_only_correct_parameter_position(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        target = "EnvironmentVariableTarget.Process"
        positives = (
            f'Environment.SetEnvironmentVariable(variable: "{name}", "{value}");\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", "{value}", {target});\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", {target});\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", "{value}", target: {target});\n',
        )
        for text in positives:
            with self.subTest(positive=text[:40]):
                findings = SCANNER.scan_text(Path("config.cs"), text)
                self.assertEqual(
                    [("config.cs", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            f'Environment.SetEnvironmentVariable(value: "{value}", "{name}");\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", dynamicValue);\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", "{value}", target: dynamicTarget);\n',
            f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", "{target}");\n',
        )
        for text in negatives:
            with self.subTest(negative=text[:40]):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), text))

    def test_environment_setter_values_resolve_prior_local_literal_aliases(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            (
                "config.go",
                f'secret := "{value}"\nos.Setenv("{name}", secret)\n',
            ),
            (
                "config.cs",
                f'var secret = "{value}";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
            (
                "config.cs",
                f'string secret = "{value}";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
            (
                "config.py",
                f'secret = "{value}"\nos.putenv("{name}", secret)\n',
            ),
        )
        for filename, text in positives:
            with self.subTest(positive=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 2, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            (
                "config.go",
                f'secret := "{value}"\nsecret = getSecret()\nos.Setenv("{name}", secret)\n',
            ),
            (
                "config.go",
                f'os.Setenv("{name}", secret)\nsecret := "{value}"\n',
            ),
            (
                "config.go",
                f'secret := "{value}"\n{{\n  secret := getSecret()\n  os.Setenv("{name}", secret)\n}}\n',
            ),
            (
                "config.cs",
                f'var secret = "{value}";\nvoid Use(string secret) {{ Environment.SetEnvironmentVariable("{name}", secret); }}\n',
            ),
            (
                "config.py",
                f'def use(secret):\n    os.putenv("{name}", secret)\n',
            ),
            (
                "config.go",
                f'var source = `os.Setenv("{name}", "{value}")`\n',
            ),
        )
        for filename, text in negatives:
            with self.subTest(negative=filename, prefix=text[:24]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_environment_setter_name_and_value_aliases_resolve_bounded(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            (
                "config.go",
                f'name := "{name}"\nsecret := "{value}"\nos.Setenv(name, secret)\n',
            ),
            (
                "config.go",
                f'prefix := "OPENAI_"\nname := prefix + "API_KEY"\nsecret := "{value}"\nos.Setenv(name, secret)\n',
            ),
            (
                "config.cs",
                f'var name = "{name}";\nvar secret = "{value}";\nEnvironment.SetEnvironmentVariable(variable: name, value: secret);\n',
            ),
            (
                "config.py",
                f'name = "{name}"\nsecret = "{value}"\nos.putenv(name, secret)\n',
            ),
        )
        for filename, text in positives:
            with self.subTest(positive=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, text.count("\n"), f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            (
                "config.go",
                f'name := "NOT_A_SECRET"\nsecret := "{value}"\nos.Setenv(name, secret)\n',
            ),
            (
                "config.go",
                f'name := getName()\nsecret := "{value}"\nos.Setenv(name, secret)\n',
            ),
            (
                "config.go",
                f'name := "{name}"\nsecret := "{value}"\nname = getName()\nos.Setenv(name, secret)\n',
            ),
            (
                "config.cs",
                f'var name = "{name}";\nvar secret = "{value}";\nname = GetName();\nEnvironment.SetEnvironmentVariable(name, secret);\n',
            ),
            (
                "config.py",
                f'name = "{name}"\nsecret = "{value}"\nname = get_name()\nos.putenv(name, secret)\n',
            ),
        )
        for filename, text in negatives:
            with self.subTest(negative=filename, prefix=text[:24]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_python_lambda_parameter_scopes_block_outer_aliases(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        lambda_cases = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda secret: os.putenv(name, secret))(secret)\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda secret, /: os.putenv(name, secret))(secret)\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda *, secret: os.putenv(name, secret))(secret=secret)\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda *secret: os.putenv(name, secret))(secret)\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda **secret: os.putenv(name, secret))(secret=secret)\n",
        )
        for text in lambda_cases:
            with self.subTest(lambda_case=text.split("lambda", 1)[1][:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

        outside_after_lambda = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda other: os.putenv(name, other))(secret)\n"
            f'os.putenv("{name}", secret)\n'
        )
        findings = SCANNER.scan_text(Path("config.py"), outside_after_lambda)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_environment_setter_values_decode_native_local_string_initializers(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            (
                "config.go",
                f'secret := `{value}`\nos.Setenv("{name}", secret)\n',
            ),
            (
                "config.cs",
                f'var secret = @"{value}";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
            (
                "config.cs",
                f'string secret = """{value}""";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
        )
        for filename, text in positives:
            with self.subTest(positive=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 2, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        semicolon_value = "Synthetic;SecretValue2026"
        semicolon_cases = (
            (
                "config.go",
                f'secret := `{semicolon_value}`\nos.Setenv("{name}", secret)\n',
            ),
            (
                "config.cs",
                f'var secret = @"{semicolon_value}";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
            (
                "config.cs",
                f'string secret = """{semicolon_value}""";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
        )
        for filename, text in semicolon_cases:
            with self.subTest(semicolon=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 2, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(semicolon_value, repr(findings))

        negatives = (
            (
                "config.go",
                f'secret := getSecret()\nos.Setenv("{name}", secret)\n',
            ),
            (
                "config.cs",
                f'var secret = $"Synthetic{{suffix}}";\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
            (
                "config.cs",
                f'var secret = GetSecret();\nEnvironment.SetEnvironmentVariable("{name}", secret);\n',
            ),
        )
        for filename, text in negatives:
            with self.subTest(negative=filename, prefix=text[:24]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_csharp_constructor_and_default_parameters_block_outer_aliases(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        constructor = (
            "class Holder {\n"
            f'    private string secret = "{value}";\n'
            "    Holder(string secret) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.cs"), constructor))

        default_parameter = (
            "class Holder {\n"
            f'    private const string outer = "{value}";\n'
            "    void Use(string secret = outer) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.cs"), default_parameter)
        )

        outer_const = (
            "class Holder {\n"
            f'    private const string secret = "{value}";\n'
            "    void Use(string other = DefaultSecret) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        findings = SCANNER.scan_text(Path("config.cs"), outer_const)
        self.assertEqual(
            [("config.cs", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        configure_invocation = (
            "class Holder {\n"
            f'    private string secret = "{value}";\n'
            "    void Use() {\n"
            "        Configure(secret);\n"
            "        if (condition) {\n"
            f'            Environment.SetEnvironmentVariable("{name}", secret);\n'
            "        }\n"
            "    }\n"
            "}\n"
        )
        findings = SCANNER.scan_text(Path("config.cs"), configure_invocation)
        self.assertEqual(
            [("config.cs", 6, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        true_constructor = (
            "class Holder {\n"
            f'    private string secret = "{value}";\n'
            "    Holder(string other) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        findings = SCANNER.scan_text(Path("config.cs"), true_constructor)
        self.assertEqual(
            [("config.cs", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        same_line_attribute = (
            "class Holder {\n"
            f'    private string secret = "{value}";\n'
            "    [Obsolete] Holder(string secret) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.cs"), same_line_attribute)
        )

        multiline_attribute = (
            "class Holder {\n"
            f'    private string secret = "{value}";\n'
            "    [Obsolete(\n"
            '        "constructor"\n'
            "    )]\n"
            "    Holder(string secret) {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.cs"), multiline_attribute)
        )

        attribute_on_other_member = (
            "class Holder {\n"
            f'    private const string secret = "{value}";\n'
            "    [Configure(secret)]\n"
            "    void Use() {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        findings = SCANNER.scan_text(Path("config.cs"), attribute_on_other_member)
        self.assertEqual(
            [("config.cs", 5, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_csharp_primary_constructor_headers_are_anchored_before_bases(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        primary = (
            "class Holder(string secret) : Base<(string Left, string Right)> {\n"
            f'    Environment.SetEnvironmentVariable("{name}", secret);\n'
            "}\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.cs"), primary))

        generic_primary = (
            "class Holder<T>(string secret) : Base<(string Left, string Right)> {\n"
            f'    Environment.SetEnvironmentVariable("{name}", secret);\n'
            "}\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.cs"), generic_primary)
        )

        base_tuple_only = (
            "class Holder : Base<(string Left, string secret)> {\n"
            f'    private const string secret = "{value}";\n'
            "    void Use() {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n"
            "}\n"
        )
        findings = SCANNER.scan_text(Path("config.cs"), base_tuple_only)
        self.assertEqual(
            [("config.cs", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_c_family_setter_calls_normalize_translation_phase_splices(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            ("config.c", f'set\\\nenv("{name}", "{value}", 1);\n'),
            ("config.cpp", f'set\\\nenv("{name}", "{value}", 1);\n'),
            ("config.c", f'setenv\\\n("{name}", "{value}", 1);\n'),
            ("config.cpp", f'setenv("OPENAI_API_\\\nKEY", "{value}", 1);\n'),
        )
        for filename, text in positives:
            with self.subTest(positive=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            ("config.c", f'// setenv\\\n("{name}", "{value}", 1);\n'),
            ("config.cpp", f'/* setenv\\\n("{name}", "{value}", 1); */\n'),
            (
                "config.c",
                f'const char *source = "setenv\\\n(\\"{name}\\", \\"{value}\\", 1)";\n',
            ),
            (
                "config.cpp",
                f'auto source = R"(setenv\\\n("{name}", "{value}", 1))";\n',
            ),
        )
        for filename, text in negatives:
            with self.subTest(negative=filename):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_unsupported_setter_literal_delimiters_fail_closed(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable(""""{name}"""", """"{value}"""");\n',
            ),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable($$"""{name}""", $$"""{value}""");\n',
            ),
            (
                "config.rs",
                f'std::env::set_var(br#"{name}"#, br#"{value}"#);\n',
            ),
        )
        for filename, text in cases:
            with self.subTest(filename=filename, literal=text.split("(", 1)[1][:10]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_supported_environment_setter_call_equivalents_detect_literals(
        self,
    ) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            ("config.c", f'setenv("{name}", "{value}", 1);\n'),
            ("config.cpp", f'setenv("{name}", "{value}", 1);\n'),
            (
                "config.cs",
                f'Environment.SetEnvironmentVariable("{name}", "{value}");\n',
            ),
            ("config.py", f'os.putenv("{name}", "{value}")\n'),
            (
                "config.rs",
                f'std::env::set_var("{name}", "{value}");\n',
            ),
            ("config.swift", f'setenv("{name}", "{value}", 1)\n'),
        )
        for filename, text in cases:
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        non_executable = (
            (
                "config.cpp",
                f'auto source = R"(setenv("{name}", "{value}", 1))";\n',
            ),
            ("config.py", f'source = """os.putenv("{name}", "{value}")"""\n'),
            ("config.rs", f'let source = r#"std::env::set_var("{name}", "{value}")"#;\n'),
            ("config.swift", f'let source = """setenv("{name}", "{value}", 1)"""\n'),
        )
        for filename, text in non_executable:
            with self.subTest(non_executable=filename):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

        for escape in ("\\x4b", "\\u004b", "\\u{4b}"):
            with self.subTest(escaped_bracket=escape):
                escaped_name = "OPENAI_API_" + escape + "EY"
                text = (
                    'process.env["'
                    + escaped_name
                    + '"] = "'
                    + value
                    + '"\n'
                )
                self.assertEqual(
                    [("config.js", 1, f"live-looking value assigned to {name}")],
                    SCANNER.scan_text(Path("config.js"), text),
                )

        dotted_escaped = (
            "process.env.OPENAI_API_\\u004bEY = \"" + value + "\"\n"
        )
        self.assertEqual(
            [("config.js", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), dotted_escaped),
        )

    def test_constant_computed_javascript_environment_keys_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                'process.env["OPENAI_" + "API_KEY"] = "' + value + '"\n',
                1,
            ),
            (
                "process.env[`OPENAI_${\"API_KEY\"}`] = \""
                + value
                + "\"\n",
                1,
            ),
            (
                'const key = "OPENAI_" + "API_KEY";\n'
                'process.env[key] = "' + value + '"\n',
                2,
            ),
            (
                'environment["OPENAI_" + "API_KEY"] = "' + value + '"\n',
                1,
            ),
        )
        for text, line in cases:
            with self.subTest(lines=len(text.splitlines())):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        escaped = (
            'process.env["OPENAI_API_\\u004bEY" + ""] = "'
            + value
            + '"\n'
        )
        self.assertEqual(
            [("config.ts", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ts"), escaped),
        )

    def test_executable_javascript_extensions_cover_computed_keys_only(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        source = (
            'const key = "OPENAI_" + "API_KEY";\n'
            'process.env[key] = "' + value + '"\n'
        )
        direct = f'process.env.{name} = "{value}"\n'

        for suffix in (".mjs", ".cjs"):
            with self.subTest(suffix=suffix):
                findings = SCANNER.scan_text(
                    Path("config" + suffix), source
                )
                self.assertEqual(
                    [
                        (
                            "config" + suffix,
                            2,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

                findings = SCANNER.scan_text(Path("config" + suffix), direct)
                self.assertEqual(
                    [
                        (
                            "config" + suffix,
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

                controls = (
                    f'// process.env.{name} = "{value}"\n',
                    f'/* process.env.{name} = "{value}" */\n',
                    f'const ordinary = \'process.env.{name} = "{value}"\'\n',
                    f'const template = `process.env.{name} = "{value}"`\n',
                )
                for control in controls:
                    with self.subTest(control=control[:18]):
                        self.assertEqual(
                            [], SCANNER.scan_text(Path("config" + suffix), control)
                        )

        for suffix in (".txt", ".md", ".json"):
            with self.subTest(non_executable_suffix=suffix):
                self.assertEqual(
                    [], SCANNER.scan_text(Path("config" + suffix), source)
                )

    def test_executable_javascript_extensions_mask_multiline_template_text(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        template_text = (
            "const source = `\n"
            + name
            + " =\n  \""
            + value
            + "\"\n`;\n"
        )
        bracket_template_text = (
            "const source = `\nprocess.env[\""
            + name
            + "\"] =\n  \""
            + value
            + "\"\n`;\n"
        )
        outer_bracket_template_text = (
            "const values = [`"
            + name
            + " =\n  \""
            + value
            + "\"\n`];\n"
        )
        outer_call_template_text = (
            "emit(`"
            + name
            + " =\n  \""
            + value
            + "\"\n`);\n"
        )
        executable_assignment = (
            "const "
            + name
            + " =\n  \""
            + value
            + "\";\n"
        )
        for suffix in (".mjs", ".cjs"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    [], SCANNER.scan_text(Path("config" + suffix), template_text)
                )
                self.assertEqual(
                    [],
                    SCANNER.scan_text(
                        Path("config" + suffix), bracket_template_text
                    ),
                )
                self.assertEqual(
                    [],
                    SCANNER.scan_text(
                        Path("config" + suffix), outer_bracket_template_text
                    ),
                )
                self.assertEqual(
                    [],
                    SCANNER.scan_text(
                        Path("config" + suffix), outer_call_template_text
                    ),
                )
                findings = SCANNER.scan_text(
                    Path("config" + suffix), executable_assignment
                )
                self.assertEqual(
                    [
                        (
                            "config" + suffix,
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_dynamic_javascript_environment_keys_and_references_remain_safe(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        dynamic = (
            "const suffix = getSecretName();\n"
            'process.env["OPENAI_" + suffix] = "' + value + '"\n'
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.js"), dynamic))
        indexed_reference = (
            'process.env["OPENAI_" + "API_KEY"] = secrets["'
            + name
            + '"]\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.js"), indexed_reference)
        )
        comments = (
            '// process.env["OPENAI_" + "API_KEY"] = "'
            + value
            + '"\n'
            '/* process.env["OPENAI_" + "API_KEY"] = "'
            + value
            + '" */\n'
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.js"), comments))

    def test_successor_computed_keys_cover_join_and_multiline_const(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        joined = (
            'process.env[["OPENAI_", "API_KEY"].join("")] = "'
            + value
            + '"\n'
        )
        nested_join = (
            'process.env[(["OPENAI_", "API_KEY"]).join("")] = "'
            + value
            + '"\n'
        )
        method_wrappers = (
            'process.env[("OPENAI_" + "API_KEY")] = "' + value + '"\n',
            'process.env[(("OPENAI_" + "API_KEY"))] = "' + value + '"\n',
            'process.env[String.raw("OPENAI_API_KEY")] = "' + value + '"\n',
            'process.env[String.raw`OPENAI_API_KEY`] = "' + value + '"\n',
            'process.env[("OPENAI_API_KEY").toString()] = "' + value + '"\n',
            'process.env["OPENAI_".concat("API_KEY")] = "' + value + '"\n',
        )
        multiline_const = (
            "const key =\n"
            '  "OPENAI_" +\n'
            '  "API_KEY";\n'
            'process.env[key] = "'
            + value
            + '"\n'
        )
        for text, line in ((joined, 1), (nested_join, 1), (multiline_const, 4)):
            with self.subTest(line=line):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))
        for text in method_wrappers:
            with self.subTest(wrapper=text.split("process.env[", 1)[1][:12]):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_successor_computed_key_normalization_stays_executable_only(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        string_literal = (
            'const source = \'process.env["OPENAI_" + "API_KEY"] = "'
            + value
            + '"\'\n'
        )
        template_literal = (
            "const source = `process.env[\"OPENAI_\" + \"API_KEY\"] = \""
            + value
            + "\"`\n"
        )
        regex_literal = (
            'const matcher = /process\\.env\\["OPENAI_" \\+ "API_KEY"\\] = "'
            + value
            + '"/;\n'
        )
        malformed = (
            'process.env["OPENAI_" + suffix] = "' + value + '"\n'
        )
        unbounded = (
            'process.env["' + ("A" * 513) + '"] = "' + value + '"\n'
        )
        for text in (
            string_literal,
            template_literal,
            regex_literal,
            malformed,
            unbounded,
        ):
            with self.subTest(prefix=text[:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

    def test_second_successor_isolates_aliases_and_scans_template_code(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        source_literals = (
            "const text = 'payload; const key=\"OPENAI_API_KEY\"';\n"
            'process.env[key] = "' + value + '"\n',
            "const text = `payload; const key=\"OPENAI_API_KEY\"`;\n"
            'process.env[key] = "' + value + '"\n',
            'const matcher = /payload; const key="OPENAI_API_KEY"/;\n'
            'process.env[key] = "' + value + '"\n',
        )
        for text in source_literals:
            with self.subTest(prefix=text[:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

        wrappers = (
            'const key = "OPENAI_API_KEY";\n'
            'process.env[String.raw(key)] = "' + value + '"\n',
            'const key = "OPENAI_API_KEY";\n'
            'process.env[key.toString()] = "' + value + '"\n',
            'const output = `${(process.env["OPENAI_" + "API_KEY"] = "'
            + value
            + '")}`;\n',
        )
        for text in wrappers:
            with self.subTest(wrapper=text.split("process.env[", 1)[1][:14]):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", 2 if "const key" in text else 1,
                      f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        controls = (
            "// const key=\"OPENAI_API_KEY\";\nprocess.env[key] =\n",
            "/* const key=\"OPENAI_API_KEY\"; */\nprocess.env[key] =\n",
            'const text = "ordinary"; // const key="OPENAI_API_KEY"\n'
            "process.env[key] =\n",
            "const text = `escaped "
            + r"\`"
            + "; const key=\"OPENAI_API_KEY\"`;\n"
            "process.env[key] =\n",
            "const text = `outer ${`inner; const key=\"OPENAI_API_KEY\"`}`;\n"
            "process.env[key] =\n",
        )
        for text in controls:
            with self.subTest(control=text[:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

    def test_literal_rhs_aliases_are_classified_as_live_values(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                'const value = "' + value + '";\n'
                + name
                + " = value\n",
                2,
            ),
            (
                'const value = "Synthetic" + "SecretValue2026";\n'
                + name
                + " = value\n",
                2,
            ),
            (
                'const value = `Synthetic${"SecretValue2026"}`;\n'
                + name
                + " = value\n",
                2,
            ),
            (
                'const first = "' + value + '";\n'
                "const second = first;\n"
                + name
                + " = second\n",
                3,
            ),
            (
                'const value: string =\n'
                '  "Synthetic" +\n'
                '  "SecretValue2026";\n'
                + name
                + " = value\n",
                4,
            ),
        )
        for text, line in cases:
            with self.subTest(line=line):
                findings = SCANNER.scan_text(Path("config.js"), text)
                self.assertEqual(
                    [("config.js", line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        controls = (
            'const value = process.env.OTHER;\n' + name + " = value\n",
            'const value = secrets["' + name + '"];\n' + name + " = value\n",
            'const text = \'const value = "' + value + '";\';\n'
            + name
            + " = value\n",
            'const matcher = /const value="' + value + '"/;\n'
            + name
            + " = value\n",
            'const value = "' + value + '";\n'
            'function read(value) {\n'
            + name
            + " = value\n}\n",
        )
        for text in controls:
            with self.subTest(control=text[:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

    def test_scope_aware_aliases_bind_nearest_prior_declaration(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        false_positive = (
            'const value = "' + value + '";\n'
            "{ let value = process.env.OTHER;\n"
            + name
            + " = value;\n}\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.js"), false_positive))

        outer_literal = (
            'const value = "' + value + '";\n'
            "{ const value = process.env.OTHER; }\n"
            + name
            + " = value;\n"
        )
        self.assertEqual(
            [("config.js", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), outer_literal),
        )

        computed_false_positive = (
            'const key = "' + name + '";\n'
            "{ let key = process.env.OTHER;\n"
            'process.env[key] = "' + value + '";\n}\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.js"), computed_false_positive)
        )
        computed_outer_literal = (
            'const key = "' + name + '";\n'
            "{ const key = process.env.OTHER; }\n"
            'process.env[key] = "' + value + '";\n'
        )
        self.assertEqual(
            [("config.js", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), computed_outer_literal),
        )

        controls = (
            name + ' = value;\nconst value = "' + value + '";\n',
            'function use(value) {\n' + name + " = value;\n}\n",
            "try {} catch (value) {\n" + name + " = value;\n}\n",
            'const value = "' + value + '";\n'
            "{ { let value = process.env.OTHER;\n"
            + name
            + " = value;\n} }\n",
        )
        for text in controls:
            with self.subTest(control=text[:22]):
                self.assertEqual([], SCANNER.scan_text(Path("config.js"), text))

        outer_after_inner = (
            'const value = "' + value + '";\n'
            "{ let value = process.env.OTHER; }\n"
            + name
            + " = value;\n"
        )
        self.assertEqual(
            [("config.js", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.js"), outer_after_inner),
        )

    def test_non_javascript_literal_rhs_aliases_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                'value = "' + value + '"\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
                2,
            ),
            (
                'value: str = "Synthetic" + "SecretValue2026"\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
                2,
            ),
            (
                'value = "Synthetic" "SecretValue2026"\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
                2,
            ),
            (
                'value = "Synthetic" + "SecretValue2026"\n'
                'ENV["' + name + '"] = value\n',
                "config.rb",
                2,
            ),
            (
                '$value = "Synthetic" + "SecretValue2026"\n'
                '$env:' + name + ' = $value\n',
                "config.ps1",
                2,
            ),
        )
        for text, filename, line in cases:
            with self.subTest(filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [(filename, line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

    def test_non_javascript_alias_controls_remain_unresolved(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            (
                'value = os.getenv("' + name + '")\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
            ),
            (
                'value = ENV["' + name + '"]\n'
                'ENV["' + name + '"] = value\n',
                "config.rb",
            ),
            (
                '$value = Get-Secret\n'
                '$env:' + name + ' = $value\n',
                "config.ps1",
            ),
            (
                'text = """value = "' + value + '"""\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
            ),
            (
                "@'\n$value = \"" + value + "\"\n'@\n"
                "$env:" + name + " = $value\n",
                "config.ps1",
            ),
            (
                'text = /value = "' + value + '"/\n'
                'ENV["' + name + '"] = value\n',
                "config.rb",
            ),
            (
                'os.environ["' + name + '"] = value\n'
                'value = "' + value + '"\n',
                "config.py",
            ),
            (
                'value = "' + value + '"\n'
                'value = os.getenv("OTHER")\n'
                'os.environ["' + name + '"] = value\n',
                "config.py",
            ),
        )
        for text, filename in cases:
            with self.subTest(filename=filename, prefix=text[:16]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

    def test_non_javascript_alias_scope_and_multiline_literals_are_isolated(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        outer_python = (
            'value = "' + value + '"\n'
            "def inner():\n"
            '    value = os.getenv("OTHER")\n'
            'os.environ["' + name + '"] = value\n'
        )
        outer_ruby = (
            'value = "' + value + '"\n'
            "def inner\n"
            '  value = ENV["OTHER"]\n'
            "end\n"
            'ENV["' + name + '"] = value\n'
        )
        for text, filename, line in (
            (outer_python, "config.py", 4),
            (outer_ruby, "config.rb", 5),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(
                    [(filename, line, f"live-looking value assigned to {name}")],
                    SCANNER.scan_text(Path(filename), text),
                )

        fake_python = (
            'text = """\n'
            'value = "' + value + '"\n'
            '"""\n'
            'os.environ["' + name + '"] = value\n'
        )
        fake_powershell = (
            "@'\n"
            '$value = "' + value + '"\n'
            "'@\n"
            '$env:' + name + ' = $value\n'
        )
        fake_powershell_block = (
            "<#\n"
            '$value = "' + value + '"\n'
            "#>\n"
            '$env:' + name + ' = $value\n'
        )
        fake_ruby = (
            "=begin\n"
            'value = "' + value + '"\n'
            "=end\n"
            'ENV["' + name + '"] = value\n'
        )
        for text, filename in (
            (fake_python, "config.py"),
            (fake_powershell, "config.ps1"),
            (fake_powershell_block, "config.ps1"),
            (fake_ruby, "config.rb"),
        ):
            with self.subTest(fake=filename, prefix=text[:12]):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

        powershell_outer = (
            '$value = "' + value + '"\n'
            "function inner {\n"
            "  $value = Get-Secret\n"
            "}\n"
            '$env:' + name + ' = $value\n'
        )
        self.assertEqual(
            [("config.ps1", 5, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), powershell_outer),
        )

    def test_powershell_one_line_scope_respects_statement_boundaries(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        dynamic_inner = (
            '$value = "' + value + '";\n'
            'function f { $value=Get-Secret; $env:' + name + '=$value }\n'
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.ps1"), dynamic_inner))

        top_level = '$value = "' + value + '"; $env:' + name + '=$value\n'
        self.assertEqual(
            [("config.ps1", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), top_level),
        )
        inner_literal = (
            'function f { $value="' + value + '"; $env:' + name + '=$value }\n'
        )
        self.assertEqual(
            [("config.ps1", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), inner_literal),
        )
        outer_after_inner = (
            '$value = "' + value + '";\n'
            'function f { $value=Get-Secret; $null=$value }\n'
            '$env:' + name + '=$value\n'
        )
        self.assertEqual(
            [("config.ps1", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), outer_after_inner),
        )

        controls = (
            '$text = "semicolon; $value = "' + value + '"";\n'
            '$env:' + name + '=$value\n',
            '# $value = "' + value + '";\n$env:' + name + '=$value\n',
            "@'\n$value = \"" + value + "\";\n'@\n"
            '$env:' + name + '=$value\n',
        )
        for text in controls:
            with self.subTest(prefix=text[:18]):
                self.assertEqual([], SCANNER.scan_text(Path("config.ps1"), text))

    def test_powershell_alias_names_are_case_insensitive(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            '$VaLuE = "' + value + '"\n$env:' + name + ' = $value\n',
            '$value = "' + value + '"\n$env:' + name + ' = $VaLuE\n',
            '$VaLuE = "' + value + '"\n$other = $VALUE\n'
            '$env:' + name + ' = $OTHER\n',
            '$value = Get-Secret\n$VALUE = "' + value + '"\n'
            '$env:' + name + ' = $VaLuE\n',
        )
        for text in cases:
            with self.subTest(prefix=text[:24]):
                self.assertEqual(
                    [("config.ps1", text.count("\n"),
                      f"live-looking value assigned to {name}")],
                    SCANNER.scan_text(Path("config.ps1"), text),
                )

        dynamic_latest = (
            '$value = "' + value + '"\n$VALUE = Get-Secret\n'
            '$env:' + name + ' = $VaLuE\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.ps1"), dynamic_latest)
        )

        case_sensitive_controls = (
            (
                'value = "' + value + '"\n'
                'os.environ["' + name + '"] = VALUE\n',
                "config.py",
            ),
            (
                'value = "' + value + '"\n'
                'ENV["' + name + '"] = VALUE\n',
                "config.rb",
            ),
        )
        for text, filename in case_sensitive_controls:
            with self.subTest(filename=filename):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))

        nested_dynamic = (
            '$Value = "' + value + '"\nfunction f {\n'
            '  $VALUE = Get-Secret\n  $env:' + name + ' = $value\n}\n'
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.ps1"), nested_dynamic)
        )
        nested_literal = (
            '$value = Get-Secret\nfunction f {\n'
            '  $VALUE = "' + value + '"\n'
            '  $env:' + name + ' = $VaLuE\n}\n'
        )
        self.assertEqual(
            [("config.ps1", 4, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), nested_literal),
        )

    def test_powershell_braced_alias_reference_is_resolved(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        text = (
            '$VaLuE = "' + value + '"\n'
            '$env:' + name + ' = ${value}\n'
        )
        self.assertEqual(
            [("config.ps1", 2, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.ps1"), text),
        )

    def test_powershell_interpolated_alias_reference_is_resolved(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for reference in ('$value', '${VaLuE}'):
            with self.subTest(reference=reference):
                text = (
                    '$VaLuE = "' + value + '"\n'
                    '$env:' + name + ' = "' + reference + '"\n'
                )
                self.assertEqual(
                    [("config.ps1", 2,
                      f"live-looking value assigned to {name}")],
                    SCANNER.scan_text(Path("config.ps1"), text),
                )

        controls = ("'${value}'",)
        for expression in controls:
            with self.subTest(control=expression):
                text = (
                    '$value = "' + value + '"\n'
                    '$env:' + name + ' = ' + expression + '\n'
                )
                self.assertEqual(
                    [], SCANNER.scan_text(Path("config.ps1"), text)
                )

    def test_powershell_braced_alias_declaration_is_resolved(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for reference in ('$value', '${VaLuE}'):
            with self.subTest(reference=reference):
                text = (
                    '${Value} = "' + value + '"\n'
                    '$env:' + name + ' = ' + reference + '\n'
                )
                self.assertEqual(
                    [("config.ps1", 2,
                      f"live-looking value assigned to {name}")],
                    SCANNER.scan_text(Path("config.ps1"), text),
                )

    def test_postgres_dollar_quote_does_not_hide_later_assignment(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        text = (
            "SELECT $$/*$$;\nSET "
            + name
            + " =\n  '"
            + value
            + "';\n"
        )

        findings = SCANNER.scan_text(Path("migration.sql"), text)

        self.assertEqual(
            [("migration.sql", 2, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_raw_strings_do_not_hide_later_assignments(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        prefixes = {
            "rust.rs": 'let text = r#"text " /* still raw"#;\n',
            "swift.swift": 'let text = #"text " /* still raw"#\n',
            "cpp.cpp": 'auto text = R"tag(text " /* still raw)tag";\n',
            "header.h": 'auto text = R"tag(text " /* still raw)tag";\n',
            "header.hh": 'auto text = R"tag(text " /* still raw)tag";\n',
            "header.hpp": 'auto text = R"tag(text " /* still raw)tag";\n',
            "header.hxx": 'auto text = R"tag(text " /* still raw)tag";\n',
            "java.java": 'var text = """text " /* still raw""";\n',
        }
        for filename, prefix in prefixes.items():
            with self.subTest(filename=filename):
                text = prefix + name + " =\n  \"" + value + "\"\n"
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(
                    [
                        (
                            filename,
                            2,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        swift_escaped_delimiter = (
            'let text = """\nembedded \\\"""\n/* still text */\n"""\n'
            + name
            + " =\n  \""
            + value
            + "\"\n"
        )
        self.assertEqual(
            [("escaped.swift", 5, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("escaped.swift"), swift_escaped_delimiter),
        )

    def test_escaped_java_text_block_delimiter_does_not_hide_assignment(
        self,
    ) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for escaped_backslash in ("\\", "\\u005c"):
            with self.subTest(escaped_backslash=escaped_backslash):
                text_block = (
                    'var text = """\n'
                    + "embedded "
                    + escaped_backslash
                    + '"""\n'
                    + "/* still text */\n"
                    + '""";\n'
                )
                text = text_block + name + " =\n  \"" + value + "\"\n"

                findings = SCANNER.scan_text(Path("config.java"), text)

                self.assertEqual(
                    [
                        (
                            "config.java",
                            5,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        unicode_quotes = "\\u0022" * 3
        unicode_text_block = (
            "var text = "
            + unicode_quotes
            + "\nliteral /* text\n"
            + unicode_quotes
            + ";\n"
            + name
            + " =\n  \""
            + value
            + "\"\n"
        )
        self.assertEqual(
            [("unicode.java", 4, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("unicode.java"), unicode_text_block),
        )

        unicode_line_terminators = (
            "class X { // ordinary \\u000a String "
            + name
            + " \\u000a = \""
            + value
            + "\"; }\n"
        )
        self.assertEqual(
            [("terminator.java", 2, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("terminator.java"), unicode_line_terminators),
        )

        generated_prefix = 'var text = """\nordinary\n""";\n' * 2_000
        generated = generated_prefix + name + " =\n  \"" + value + "\"\n"
        generated_findings = SCANNER.scan_text(Path("generated.java"), generated)
        self.assertEqual(
            [
                (
                    "generated.java",
                    6_001,
                    f"live-looking value assigned to {name}",
                )
            ],
            generated_findings,
        )

    def test_yaml_document_boundaries_end_null_assignment(self) -> None:
        name = "OPENAI_" + "API_KEY"
        for marker in ("---", "..."):
            with self.subTest(marker=marker):
                text = name + ":\n" + marker + "\nOTHER_SETTING: ordinary\n"
                self.assertEqual(
                    [], SCANNER.scan_text(Path("settings.yaml"), text)
                )

        for value in ("---", "..."):
            with self.subTest(indented_value=value):
                text = name + ":\n  " + value + "\n"
                self.assertEqual(
                    [
                        (
                            "settings.yaml",
                            1,
                            f"live-looking value assigned to {name}",
                        )
                    ],
                    SCANNER.scan_text(Path("settings.yaml"), text),
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

    def test_toml_scan_decodes_escaped_sensitive_key(self) -> None:
        name = "OPENAI_" + "API_KEY"
        escaped_name = "OPENAI_API_" + "\\u004b" + "EY"
        value = "SyntheticSecretValue2026"
        text = '"' + escaped_name + '" = "' + value + '"\n'

        findings = SCANNER.scan_text(Path("settings.toml"), text)

        self.assertEqual(
            [("settings.toml", 1, f"live-looking value assigned to {name}")],
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

    def test_compound_named_assignments_are_detected(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        for operator in ("??=", "||=", "&&=", "+=", "**="):
            with self.subTest(operator=operator):
                findings = SCANNER.scan_text(
                    Path("config.js"),
                    name + " " + operator + ' "' + value + '"\n',
                )
                self.assertEqual(
                    [("config.js", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        make_findings = SCANNER.scan_text(
            Path("Makefile"), name + " ?= " + value + "\n"
        )
        self.assertEqual(
            [("Makefile", 1, f"live-looking value assigned to {name}")],
            make_findings,
        )

        make_define = (
            "define " + name + "\n" + value + "\nendef\n"
        )
        self.assertEqual(
            [("Makefile", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("Makefile"), make_define),
        )
        safe_define = (
            "define " + name + "\n${" + name + "}\nendef\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("Makefile"), safe_define)
        )

        make_shell_define = (
            "define "
            + name
            + " !=\nprintf "
            + value
            + "\nendef\n"
        )
        self.assertEqual(
            [("Makefile", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("Makefile"), make_shell_define),
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

    def test_shell_backslash_newline_splices_are_detected_with_origin_line(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            "OPENAI_API_\\\nKEY=" + value + "\n",
            "export OPENAI_API_\\\nKEY=" + value + "\n",
            "OPENAI_API_KEY\\\n= " + value + "\n",
            "echo ${OPENAI_API_\\\nKEY:-" + value + "}\n",
        )
        for text in cases:
            with self.subTest(lines=len(text.splitlines())):
                findings = SCANNER.scan_text(Path("script.sh"), text)
                self.assertEqual(
                    [("script.sh", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        crlf = "OPENAI_API_\\\r\nKEY=" + value + "\r\n"
        self.assertEqual(
            [("script.sh", 1, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("script.sh"), crlf),
        )

    def test_shell_continuations_preserve_quotes_comments_heredocs_and_safe_values(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        escaped_backslash = "OPENAI_API_\\\\\nKEY=" + value + "\n"
        self.assertEqual(
            [], SCANNER.scan_text(Path("script.sh"), escaped_backslash)
        )
        single_quoted = "printf '%s' 'OPENAI_API_\\\nKEY=" + value + "'\n"
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), single_quoted))
        double_quoted = 'printf "%s" "OPENAI_API_\\\nKEY=' + value + '"\n'
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), double_quoted))
        comment = "# OPENAI_API_\\\nKEY=" + value + "\n"
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), comment))
        heredoc = (
            "cat <<'EOF'\n"
            "OPENAI_API_\\\n"
            "KEY=" + value + "\n"
            "EOF\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), heredoc))
        ordinary = "printf '%s ' \\\n'ordinary continuation'\n"
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), ordinary))
        safe_parameter = "echo ${OPENAI_API_\\\nKEY:?set privately}\n"
        self.assertEqual([], SCANNER.scan_text(Path("script.sh"), safe_parameter))

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
