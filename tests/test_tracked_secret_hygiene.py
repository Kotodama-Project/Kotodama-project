import importlib.util
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path


import yaml
from tests.test_local_secret_ignore_policy import _ignored_paths
from tests.document_contract_helpers import assert_links, fenced_blocks, section

ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "tools/check_tracked_secret_hygiene.py"
SPEC = importlib.util.spec_from_file_location("tracked_secret_hygiene", SCANNER_PATH)
assert SPEC is not None and SPEC.loader is not None
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)


class TrackedSecretHygieneTests(unittest.TestCase):
    @staticmethod
    def execute_owned_setter_fixture(text: str) -> list[tuple[str, str]]:
        calls: list[tuple[str, str]] = []
        owned_os = SimpleNamespace(putenv=lambda name, value: calls.append((name, value)))
        exec(compile(text, "owned-setter-fixture", "exec"), {"os": owned_os})
        return calls

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
        'Legacy case ID; labelled positive detections and safe/unsupported controls.'
        scenarios = []
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
        scenarios.append((
            'safe_reference', 'settings.yaml', safe_reference,
            [],
        ))
        scenarios.append((
            'safe_reference_after_comment', 'settings.yaml', safe_reference_after_comment,
            [],
        ))
        value = "SyntheticSecretValue2026"
        after_embedded_indicator = (
            "description: ordinary-'text\n"
            + "- {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'after_embedded_indicator', 'after-indicator.yaml', after_embedded_indicator,
            [('after-indicator.yaml', 2, f'live-looking value assigned to {name}')],
        ))
        scenarios.append((
            'null_with_sibling', 'settings.yaml', null_with_sibling,
            [],
        ))
        scenarios.append((
            'split_null', 'settings.json', split_null,
            [],
        ))
        safe_block = name + ": >-\n  ${{ secrets." + name + " }}\n"
        scenarios.append((
            'safe_block', 'settings.yaml', safe_block,
            [],
        ))
        empty_block = name + ": >-\nOTHER_SETTING: ordinary\n"
        scenarios.append((
            'empty_block', 'settings.yaml', empty_block,
            [],
        ))
        next_item = (
            "- name: "
            + name
            + "\n- other: ordinary\n  value: "
            + value
            + "\n"
        )
        scenarios.append((
            'next_item', 'settings.yaml', next_item,
            [],
        ))
        unrelated_mapping = (
            "entry:\n  name: "
            + name
            + "\nother:\n  value: "
            + value
            + "\n"
        )
        scenarios.append((
            'unrelated_mapping', 'settings.yaml', unrelated_mapping,
            [],
        ))
        unsafe_block = name + ": |2-\n    " + value + "\n"
        scenarios.append((
            'unsafe_block', 'settings.yaml', unsafe_block,
            [('settings.yaml', 1, f'live-looking value assigned to {name}')],
        ))
        block_hash_literal = (
            name + ": >-\n  ${" + name + "} # " + value + "\n"
        )
        scenarios.append((
            'block_hash_literal', 'settings.yaml', block_hash_literal,
            [('settings.yaml', 1, f'live-looking value assigned to {name}')],
        ))
        for (index, (label, filename, text, expected)) in enumerate(scenarios):
            with self.subTest(scenario=f'{label}:{index}', filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(expected, findings)
                self.assertNotIn(value, repr(findings))

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
        'Legacy case ID; labelled positive detections and safe/unsupported controls.'
        scenarios = []
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
        for (filename, text) in cases.items():
            scenarios.append((
                'text', filename, text,
                [(filename, 1, f'live-looking value assigned to {name}')],
            ))
        after_plain_apostrophe = (
            "description: it's ordinary\n"
            + "- {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'after_plain_apostrophe', 'after-apostrophe.yaml', after_plain_apostrophe,
            [('after-apostrophe.yaml', 2, f'live-looking value assigned to {name}')],
        ))
        escaped_block_fields = (
            '- "na\\u006de": '
            + name
            + '\n  "val\\u0075e": '
            + value
            + "\n"
        )
        scenarios.append((
            'escaped_block_fields', 'escaped-block.yaml', escaped_block_fields,
            [('escaped-block.yaml', 1, f'live-looking value assigned to {name}')],
        ))
        for scalar_property in ('&s', '!!str'):
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
            for (filename, text) in (('property-block.yaml', block_property), ('property-flow.yaml', flow_property)):
                scenarios.append((
                    'text', filename, text,
                    [(filename, 1, f'live-looking value assigned to {name}')],
                ))
            multiline_property = (
                "- name: "
                + scalar_property
                + "\n    "
                + name
                + "\n  value: "
                + value
                + "\n"
            )
            scenarios.append((
                'multiline_property', 'property-multiline.yaml', multiline_property,
                [('property-multiline.yaml', 1, f'live-looking value assigned to {name}')],
            ))
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
        for (label, text) in (('merge-value', merge_value), ('merge-name', merge_name)):
            filename = label + ".yaml"
            scenarios.append((
                'text', filename, text,
                [(filename, 2, f'live-looking value assigned to {name}')],
            ))
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
        for (label, text) in (('block-merge-value', block_merge_value), ('block-merge-name', block_merge_name)):
            filename = label + ".yaml"
            scenarios.append((
                'text', filename, text,
                [(filename, 4, f'live-looking value assigned to {name}')],
            ))
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
        for (filename, text) in (('alias-block.yaml', scalar_alias_block), ('alias-flow.yaml', scalar_alias_flow)):
            scenarios.append((
                'text', filename, text,
                [(filename, 2, f'live-looking value assigned to {name}')],
            ))
        flow_collection_alias = (
            "names: [&secret_name "
            + name
            + "]\n- name: *secret_name\n  value: "
            + value
            + "\n"
        )
        scenarios.append((
            'flow_collection_alias', 'flow-alias.yaml', flow_collection_alias,
            [('flow-alias.yaml', 2, f'live-looking value assigned to {name}')],
        ))
        reverse_block = "- value: " + value + "\n  name: " + name + "\n"
        scenarios.append((
            'reverse_block', 'reverse-block.yaml', reverse_block,
            [('reverse-block.yaml', 2, f'live-looking value assigned to {name}')],
        ))
        value_from = (
            "- name: "
            + name
            + "\n  valueFrom:\n    secretKeyRef:\n      name: private\n"
        )
        scenarios.append((
            'value_from', 'settings.yaml', value_from,
            [],
        ))
        reverse_value_from = (
            "- valueFrom:\n    secretKeyRef:\n      name: private\n  name: "
            + name
            + "\n"
        )
        scenarios.append((
            'reverse_value_from', 'settings.yaml', reverse_value_from,
            [],
        ))
        canonical_sequence_scalar = (
            "documentation:\n  - |-\n    {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'canonical_sequence_scalar', 'settings.yaml', canonical_sequence_scalar,
            [],
        ))
        escaped_name = "OPENAI_API_" + "\\u004b" + "EY"
        escaped = (
            '- name: "'
            + escaped_name
            + '"\n  value: "'
            + value
            + '"\n'
        )
        scenarios.append((
            'escaped', 'settings.yaml', escaped,
            [('settings.yaml', 1, f'live-looking value assigned to {name}')],
        ))
        safe_block = (
            "- name: "
            + name
            + "\n  value: >-\n    ${{ secrets."
            + name
            + " }}\n"
        )
        scenarios.append((
            'safe_block', 'settings.yaml', safe_block,
            [],
        ))
        empty_structured_block = (
            "- name: "
            + name
            + "\n  value: >-\n- name: OTHER_SETTING\n  value: ordinary\n"
        )
        scenarios.append((
            'empty_structured_block', 'settings.yaml', empty_structured_block,
            [],
        ))
        safe_flow = (
            "- {name: "
            + name
            + ", metadata: {enabled: true}, value: ${{ secrets."
            + name
            + " }}}\n"
        )
        scenarios.append((
            'safe_flow', 'settings.yaml', safe_flow,
            [],
        ))
        separate_flow_records = (
            "- {name: " + name + "}\n- {value: " + value + "}\n"
        )
        scenarios.append((
            'separate_flow_records', 'settings.yaml', separate_flow_records,
            [],
        ))
        commented_flow_record = (
            "# {name: " + name + ", value: " + value + "}\n"
        )
        scenarios.append((
            'commented_flow_record', 'settings.yaml', commented_flow_record,
            [],
        ))
        single_quoted_escape_key = (
            "- {'na\\u006de': "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'single_quoted_escape_key', 'settings.yaml', single_quoted_escape_key,
            [],
        ))
        flow_example_block = (
            "documentation: |-\n  {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'flow_example_block', 'settings.yaml', flow_example_block,
            [],
        ))
        flow_example_sequence = (
            "documentation:\n  - |-\n      {name: "
            + name
            + ", value: "
            + value
            + "}\n"
        )
        scenarios.append((
            'flow_example_sequence', 'settings.yaml', flow_example_sequence,
            [],
        ))
        nested_unrelated_value = (
            "- {name: "
            + name
            + ", metadata: {other: ordinary, value: "
            + value
            + "}}\n"
        )
        scenarios.append((
            'nested_unrelated_value', 'settings.yaml', nested_unrelated_value,
            [],
        ))
        flow_value_from = (
            "- {metadata: {enabled: true}, name: "
            + name
            + ", valueFrom: {secretKeyRef: {name: private, key: token}}}\n"
        )
        scenarios.append((
            'flow_value_from', 'settings.yaml', flow_value_from,
            [],
        ))
        merge_override = (
            "common: &common\n  value: "
            + value
            + "\nentry:\n  <<: *common\n  name: "
            + name
            + "\n  value: ${{ secrets."
            + name
            + " }}\n"
        )
        scenarios.append((
            'merge_override', 'settings.yaml', merge_override,
            [],
        ))
        for (index, (label, filename, text, expected)) in enumerate(scenarios):
            with self.subTest(scenario=f'{label}:{index}', filename=filename):
                findings = SCANNER.scan_text(Path(filename), text)
                self.assertEqual(expected, findings)
                self.assertNotIn(value, repr(findings))

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
        """Literal guards plus API-invalid/nonliteral/unresolved-target controls; no safety claim."""
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

        negatives = {
            'valid_nonliteral_value': f'Environment.SetEnvironmentVariable(variable: "{name}", value: secretValue);\n',
            'invalid_unknown_parameter': f'Environment.SetEnvironmentVariable(name: "{name}", value: "{value}");\n',
            'invalid_duplicate_parameter': f'Environment.SetEnvironmentVariable(variable: "{name}", variable: "OTHER", value: "{value}");\n',
            'invalid_parameter_case': f'Environment.SetEnvironmentVariable(Variable: "{name}", Value: "{value}");\n',
            'valid_unresolved_target': f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", target: target);\n',
            'invalid_target_type': f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", target: "Process");\n',
        }
        for label, text in negatives.items():
            with self.subTest(resolution=label):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), text))

    def test_csharp_mixed_positional_named_setter_arguments_are_bounded(self) -> None:
        """Literal guards plus API-invalid/nonliteral/unresolved-target controls; no safety claim."""
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

        negatives = {
            'invalid_positional_after_reordered_named': f'Environment.SetEnvironmentVariable(value: "{value}", "{name}");\n',
            'valid_nonliteral_value': f'Environment.SetEnvironmentVariable("{name}", value: dynamicValue);\n',
            'valid_unresolved_target': f'Environment.SetEnvironmentVariable("{name}", value: "{value}", target: dynamicTarget);\n',
            'invalid_duplicate_value': f'Environment.SetEnvironmentVariable("{name}", value: "{value}", value: "OTHER");\n',
            'invalid_duplicate_variable': f'Environment.SetEnvironmentVariable("{name}", variable: "OTHER", value: "{value}");\n',
        }
        for label, text in negatives.items():
            with self.subTest(resolution=label):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), text))

    def test_csharp_named_prefixes_allow_only_correct_parameter_position(self) -> None:
        """Literal guards plus API-invalid/nonliteral/unresolved-target controls; no safety claim."""
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

        negatives = {
            'invalid_named_parameter_position': f'Environment.SetEnvironmentVariable(value: "{value}", "{name}");\n',
            'valid_nonliteral_value': f'Environment.SetEnvironmentVariable(variable: "{name}", dynamicValue);\n',
            'valid_unresolved_target': f'Environment.SetEnvironmentVariable(variable: "{name}", "{value}", target: dynamicTarget);\n',
            'invalid_target_type': f'Environment.SetEnvironmentVariable(variable: "{name}", value: "{value}", "{target}");\n',
        }
        for label, text in negatives.items():
            with self.subTest(resolution=label):
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

        default_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda secret=os.putenv(name, secret): secret)()\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), default_setter),
        )

        keyword_default_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda *, secret=os.putenv(name, secret): secret)()\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), keyword_default_setter),
        )

        nested_default_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(lambda outer=(lambda secret=os.putenv(name, secret): secret)(): outer)()\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), nested_default_setter),
        )

    def test_python_ast_utf8_columns_keep_lambda_and_outer_alias_scopes(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        unicode_prefix = "日本語" * 20
        text = (
            f'prefix = "{unicode_prefix}"; name = "{name}"; secret = "{value}"; '
            "(lambda secret: os.putenv(name, secret))(secret); "
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), text)
        self.assertEqual(
            [("config.py", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_python_function_defaults_and_annotations_use_enclosing_scope(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        default_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "def use(secret=os.putenv(name, secret)):\n"
            "    os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), default_setter),
        )

        keyword_default_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "async def use(*, secret=os.putenv(name, secret)):\n"
            "    os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), keyword_default_setter),
        )

        decorator = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "@decorate(os.putenv(name, secret))\n"
            "def use(secret):\n"
            "    os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), decorator),
        )

        annotation = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "def use(secret: os.putenv(name, secret) = \"default\") -> "
            "os.putenv(name, secret):\n"
            "    os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), annotation),
        )

    def test_python_named_expression_aliases_follow_scope_and_position(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        literal = (
            "(name := \"OPENAI_API_KEY\")\n"
            f'(secret := "{value}")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), literal)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        alias_chain = (
            'prefix = "OPENAI_"\n'
            '(name := prefix + "API_KEY")\n'
            'base = "Synthetic"\n'
            '(secret := base + "SecretValue2026")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), alias_chain)
        self.assertEqual(
            [("config.py", 5, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        latest_rebind = (
            '(name := "OPENAI_API_KEY")\n'
            f'(secret := "{value}")\n'
            "(secret := get_secret())\n"
            "os.putenv(name, secret)\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), latest_rebind))

        comprehension_dynamic = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "[ (secret := get_secret()) for _ in [0] ]\n"
            "os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [], SCANNER.scan_text(Path("config.py"), comprehension_dynamic)
        )

        nested_function = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "def use():\n"
            "    (secret := get_secret())\n"
            "    os.putenv(name, secret)\n"
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), nested_function)
        self.assertEqual(
            [("config.py", 6, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        after_use = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "os.putenv(name, secret)\n"
            f'(secret := "{value}")\n'
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), after_use),
        )

    def test_python_named_expression_rhs_and_nested_values_follow_evaluation_order(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        rhs_setter = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "(secret := os.putenv(name, secret))\n"
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), rhs_setter)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        nested = (
            '(name := "OPENAI_API_KEY")\n'
            f'(secret := "{value}")\n'
            "(outer := (inner := secret))\n"
            "os.putenv(name, outer)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), nested)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_python_compound_expression_aliases_are_left_to_right(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        binop = (
            'name = (name_prefix := "") + name_prefix + "OPENAI_API_KEY"\n'
            f'secret = (secret_prefix := "") + secret_prefix + "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), binop)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        boolop = (
            'name = (name_prefix := "OPENAI_API_KEY") and name_prefix\n'
            f'secret = (secret_prefix := "{value}") and secret_prefix\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), boolop)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        indexed = (
            'name = [(name_prefix := "OPENAI_API_KEY"), name_prefix][1]\n'
            f'secret = [(secret_prefix := "{value}"), secret_prefix][1]\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), indexed)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        call_arguments = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "result = capture((secret := os.putenv(name, secret)), secret)\n"
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), call_arguments)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        dynamic = (
            'name = (name_prefix := get_name()) + name_prefix\n'
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), dynamic))

    def test_python_comprehension_walrus_scopes_are_bounded(self) -> None:
        'Static body detection is separate from compilation and actual generator iteration.'
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            f'name = "{name}"\n'
            f'[os.putenv(name, secret) for secret in ["{value}"]]\n',
            f'name = "{name}"\n'
            f'{{os.putenv(name, secret) for secret in {{"{value}"}}}}\n',
            f'name = "{name}"\n'
            f'{{secret: os.putenv(name, secret) for secret in ("{value}",)}}\n',
            f'name = "{name}"\n'
            f'(os.putenv(name, secret) for secret in ("{value}",))\n',
            f'name = "{name}"\n'
            f'[os.putenv(name, secret) for secret in ["{value}", "{value}"]]\n',
        )
        for text in positives:
            with self.subTest(positive=text[:28]):
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", 2, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        first_iterable = (
            f'name = "{name}"\n'
            f'secret = "{value}"\n'
            "[item for secret in [os.putenv(name, secret)]]\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), first_iterable)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        walrus_in_condition = (
            f'name = "{name}"\n'
            f'[os.putenv(name, secret) for item in [0] if (secret := "{value}")]\n'
        )
        findings = SCANNER.scan_text(Path("config.py"), walrus_in_condition)
        self.assertEqual(
            [("config.py", 2, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        walrus_in_iterable = (
            f'name = "{name}"\n'
            f'[os.putenv(name, secret) for item in [(secret := "{value}")]]\n'
        )
        with self.assertRaises(SyntaxError):
            compile(walrus_in_iterable, "invalid-comprehension-iterable", "exec")
        # Conservative source detection of invalid syntax is not an execution proof.
        findings = SCANNER.scan_text(Path("config.py"), walrus_in_iterable)
        self.assertEqual(
            [("config.py", 2, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        iterated_generator = (
            f'name = "{name}"\n'
            f'list(os.putenv(name, secret) for secret in ("{value}",))\n'
        )
        self.assertEqual([(name, value)], self.execute_owned_setter_fixture(iterated_generator))
        self.assertEqual(
            [("config.py", 2, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), iterated_generator),
        )

        # The preceding malformed-source fixture remains useful to the scanner.
        # CPython forbids a walrus inside a comprehension iterable; this valid
        # counterpart binds the iterable first and actually reaches the setter.
        valid_prebound_iterable = (
            f'name = "{name}"\n'
            f'items = [(secret := "{value}")]\n'
            "[os.putenv(name, secret) for item in items]\n"
        )
        self.assertEqual(
            [(name, value)], self.execute_owned_setter_fixture(valid_prebound_iterable)
        )
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), valid_prebound_iterable),
        )

        negatives = (
            f'name = "{name}"\nsecret = "{value}"\n'
            "[os.putenv(name, secret) for secret in secrets]\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            '[os.putenv(name, secret) for secret in ["other", "' + value + '"]]\n',
            f'name = "{name}"\nsecret = "{value}"\n'
            "[os.putenv(name, secret) for x in [0] for secret in get_secrets()]\n",
            f'name = "{name}"\nsecret = "{value}"\n'
            "[os.putenv(name, secret) for secret in [get_secret()] if secret]\n",
        )
        for text in negatives:
            with self.subTest(negative=text[:28]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

    def test_python_comprehension_targets_destructure_static_literals(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            (
                '[os.putenv(name, secret) for name, secret in '
                f'[("{name}", "{value}")]]\n'
            ),
            (
                '[os.putenv(name, secret) for [name, secret] in '
                f'[["{name}", "{value}"]]]\n'
            ),
            (
                '[os.putenv(name, secret) for name, (prefix, secret) in '
                f'[("{name}", ("prefix", "{value}"))]]\n'
            ),
            (
                '[os.putenv(name, secret) for name, secret in '
                f'[("{name}", "{value}"), ("{name}", "{value}")]]\n'
            ),
        )
        for text in positives:
            with self.subTest(positive=text[:40]):
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", 1, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        negatives = (
            (
                f'name = "{name}"\nsecret = "{value}"\n'
                "[os.putenv(name, secret) for name, secret in pairs]\n"
            ),
            (
                '[os.putenv(name, secret) for name, secret in '
                f'[("{name}",)]]\n'
            ),
            (
                '[os.putenv(name, secret) for name, secret in '
                f'[("{name}", "other"), ("{name}", "{value}")]]\n'
            ),
            (
                '[os.putenv(name, secret) for name, *secret in '
                f'[("{name}", "{value}")]]\n'
            ),
            (
                '[os.putenv(name, secret) for name, (prefix, secret) in '
                f'[("{name}", ("prefix",))]]\n'
            ),
        )
        for text in negatives:
            with self.subTest(negative=text[:40]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

    def test_python_compound_literals_and_comparisons_fail_closed(self) -> None:
        'Legacy fail_closed ID: bounded constant resolution, short circuits and side effects; unknown is not safe.'
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        starred = (
            'name = [*"OPENAI_API_KEY"][0]\n'
            f'secret = [*"{value}"][0]\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), starred))

        converted = (
            'name = f"{(name_part := \'OPENAI_API_KEY\')!r}"\n'
            f'secret = f"{{(secret_part := \'{value}\'):>40}}"\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), converted))

        converted_side_effect = (
            f'name = "{name}"\n'
            f'secret = f"{{(secret_part := \'{value}\')!r}}"\n'
            "os.putenv(name, secret_part)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), converted_side_effect)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        safe_comparison = (
            f'name = "{name}"\n'
            f'secret = ("a" < "z") and (secret_part := "{value}")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), safe_comparison)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        bool_numeric_comparison = (
            f'name = (True == 1) and "{name}"\n'
            f'secret = (False < 1) and "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), bool_numeric_comparison)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        comparison_short_circuit = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = "z" < "a" < (name := "NOT_A_SECRET")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), comparison_short_circuit)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        nested_bool_short_circuit = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = "a" < ("" and (name := "NOT_A_SECRET")) < "z"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), nested_bool_short_circuit)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        unselected_if_branch = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = "a" < ("left" if True else (name := "NOT_A_SECRET")) < "z"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), unselected_if_branch)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        unknown_branch_keeps_earlier_effect = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = (prefix := "known") and '
            '("left" if flag else (name := "NOT_A_SECRET"))\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), unknown_branch_keeps_earlier_effect)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        duplicate_target = (
            '[os.putenv(name, secret) for name, secret, secret in '
            f'[("{name}", "<PLACEHOLDER>", "{value}")]]\n'
        )
        findings = SCANNER.scan_text(Path("config.py"), duplicate_target)
        self.assertEqual(
            [("config.py", 1, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        duplicate_target_placeholder = (
            '[os.putenv(name, secret) for name, secret, secret in '
            f'[("{name}", "{value}", "<PLACEHOLDER>")]]\n'
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("config.py"), duplicate_target_placeholder),
        )

        comparison_unknown = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = get_value() < "z" < (name := "NOT_A_SECRET")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), comparison_unknown)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_python_typed_ephemeral_values_follow_nested_branch_order(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        none_truthiness = (
            'name = (flag := None) or (name_part := "OPENAI_API_KEY")\n'
            f'secret = (secret_flag := None) or (secret_part := "{value}")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), none_truthiness)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        bool_numeric_flags = (
            'name = (false_flag := False) or (name_part := "OPENAI_API_KEY")\n'
            f'secret = (zero_flag := 0) or (secret_part := "{value}")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), bool_numeric_flags)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        cross_type_equality = (
            'name = (none_flag := None) == None and '
            '(name_part := "OPENAI_API_KEY")\n'
            f'secret = (bool_flag := True) == 1 and (secret_part := "{value}")\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), cross_type_equality)
        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        nested_branch = (
            f'name = "{name}"\nsecret = "{value}"\n'
            'result = (flag := None) or '
            '("unused" if flag else (alias := "OPENAI_API_KEY"))\n'
            "os.putenv(alias, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), nested_branch)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        unknown_object = (
            'unknown = object()\n'
            'name = (flag := unknown) or (name_part := "OPENAI_API_KEY")\n'
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), unknown_object))

    def test_python_resolution_preflight_preserves_visitor_state(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        expression = '(x := x or (name := "OPENAI_API_KEY")) and True'

        for initial in ('""', "None", "False", "0"):
            with self.subTest(initial=initial):
                text = (
                    f"x = {initial}\n"
                    f'secret = "{value}"\n'
                    f"result = {expression}\n"
                    "os.putenv(name, secret)\n"
                )
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", 4, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        wrappers = (
            f"result = {expression}",
            f"result: bool = {expression}",
            f"(result := {expression})",
            f'answer = "left" if {expression} else "right"',
            f'result = ({expression}) == "OPENAI_API_KEY"',
            f"consume({expression})",
            expression,
        )
        for wrapped in wrappers:
            with self.subTest(wrapper=wrapped.split("=", 1)[0].strip()):
                text = (
                    'x = ""\n'
                    f'secret = "{value}"\n'
                    f"{wrapped}\n"
                    "os.putenv(name, secret)\n"
                )
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", 4, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        controls = (
            (
                'x = "already"\n'
                f'secret = "{value}"\n'
                f"result = {expression}\n"
                "os.putenv(name, secret)\n"
            ),
            (
                "x = get_value()\n"
                f'secret = "{value}"\n'
                f"result = {expression}\n"
                "os.putenv(name, secret)\n"
            ),
            (
                'x = ""\n'
                f'secret = "{value}"\n'
                'result = (x := x or (name := "NOT_A_SECRET")) and True\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for text in controls:
            with self.subTest(control=text.splitlines()[0]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

    def test_python_boolop_operand_traversal_uses_pre_evaluation_state(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        text = (
            'x = ""; result = (x := x or (name := "OPENAI_API_KEY")) and True\n'
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )

        findings = SCANNER.scan_text(Path("config.py"), text)

        self.assertEqual(
            [("config.py", 3, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

    def test_python_static_destructuring_and_dict_aliases_are_bounded(self) -> None:
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        positives = (
            (
                f'name, secret = ("{name}", "{value}")\n'
                "os.putenv(name, secret)\n",
                2,
            ),
            (
                f'[name, secret] = ["{name}", "{value}"]\n'
                "os.putenv(name, secret)\n",
                2,
            ),
            (
                f'(name, [secret]) = ("{name}", ["{value}"])\n'
                "os.putenv(name, secret)\n",
                2,
            ),
            (
                f'name, secret, secret = ("{name}", "safe", "{value}")\n'
                "os.putenv(name, secret)\n",
                2,
            ),
            (
                f'name = {{"key": "{name}"}}["key"]\n'
                f'secret = {{"key": "{value}"}}["key"]\n'
                "os.putenv(name, secret)\n",
                3,
            ),
        )
        for text, line in positives:
            with self.subTest(positive=text.splitlines()[0]):
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        controls = (
            (
                f'name = "{name}"\nsecret = "{value}"\n'
                "name, secret = get_pair()\n"
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = "{name}"\nsecret = "{value}"\n'
                'name, secret = ("safe",)\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name, *rest, secret = ("{name}", "safe", "{value}")\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{get_key(): "{name}"}}["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{"key": get_name()}}["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{**mapping, "key": "{name}"}}["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{"key": "safe", "key": "{name}"}}["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{True: "{name}"}}[1]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'name = {{"other": "{name}"}}["missing"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for text in controls:
            with self.subTest(control=text.splitlines()[0]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

        mutated_dict_controls = (
            (
                'mapping = {"key": "safe"}\n'
                f'mapping["key"] = "{name}"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                'mapping["key"] = "safe"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for text in mutated_dict_controls:
            with self.subTest(mutated_dict=text.splitlines()[0]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

        container_lifecycle_controls = (
            (
                f'mapping = {{"key": "{name}"}}\n'
                "del mapping\n"
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                'mapping.update({"key": "example"})\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'values = ["{name}"]\n'
                "values.clear()\n"
                "name = values[0]\n"
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for text in container_lifecycle_controls:
            with self.subTest(container_lifecycle=text.splitlines()[1]):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

        non_container_method = (
            f'name = "{name}"\n'
            "name.lower()\n"
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), non_container_method)
        self.assertEqual(
            [("config.py", 4, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        pairwise_dict_order = (
            f'name = "{name}"\n'
            f'y = "{value}"\n'
            'result = {"first": (x := y), (y := "<PLACEHOLDER>"): "example"}\n'
            "secret = x\n"
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), pairwise_dict_order)
        self.assertEqual(
            [("config.py", 5, f"live-looking value assigned to {name}")],
            findings,
        )
        self.assertNotIn(value, repr(findings))

        pairwise_dict_order_control = (
            f'name = "{name}"\n'
            'y = "<PLACEHOLDER>"\n'
            f'result = {{"first": (x := y), (y := "{value}"): "example"}}\n'
            "secret = x\n"
            "os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [],
            SCANNER.scan_text(Path("config.py"), pairwise_dict_order_control),
        )

    def test_python_container_mutations_invalidate_all_static_views(self) -> None:
        'Each alias/side-effect oracle records its real line; incomplete source does not prove execution.'
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        controls = (
            (
                f'mapping = {{"key": "{name}"}}\n'
                "alias = mapping\n"
                'alias["key"] = "safe"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "alias = mapping\n"
                "alias.clear()\n"
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'inner = {{"key": "{name}"}}\n'
                'outer = {"inner": inner}\n'
                'inner["key"] = "safe"\n'
                'name = outer["inner"]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'inner = {{"key": "{name}"}}\n'
                "outer = (inner,)\n"
                'inner["key"] = "safe"\n'
                'name = outer[0]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'values = ["{name}"]\n'
                "alias = values\n"
                "alias.clear()\n"
                "name = values[0]\n"
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'values = ["{name}"]\n'
                "alias = values\n"
                'alias += ["safe"]\n'
                "name = values[0]\n"
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "alias = mapping\n"
                'del alias["key"]\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "alias = mapping\n"
                'alias["key"]: str = "safe"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "def mutate():\n"
                "    alias = mapping\n"
                "    alias.clear()\n"
                '    name = mapping["key"]\n'
                f'    secret = "{value}"\n'
                "    os.putenv(name, secret)\n"
            ),
            (
                "result = (\n"
                f'    (mapping := {{"key": "{name}"}}),\n'
                "    (alias := mapping),\n"
                '    alias.update({"key": "safe"}),\n'
                '    (name := mapping["key"]),\n'
                ")\n"
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'inner = {{"key": "{name}"}}\n'
                "outer = [inner]\n"
                "alias = outer\n"
                "unknown = get_index()\n"
                'outer[unknown]["key"] = "safe"\n'
                'name = alias[0]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'inner = {{"key": "{name}"}}\n'
                "outer = [inner]\n"
                "alias = outer\n"
                "unknown = get_index()\n"
                'outer[unknown].__init__({"key": "safe"})\n'
                'name = alias[0]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'inner = {{"key": "{name}"}}\n'
                "outer = [inner]\n"
                "alias = outer\n"
                "unknown = get_index()\n"
                "outer[unknown].clear()\n"
                'name = alias[0]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "class Mutate:\n"
                "    alias = mapping\n"
                '    alias["key"] = "safe"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                "class Outer:\n"
                "    alias = mapping\n"
                "    class Inner:\n"
                "        nested = alias\n"
                "        nested.clear()\n"
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                'dict.update(mapping, {"key": "safe"})\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'values = ["{name}"]\n'
                'list.__setitem__(values, 0, "safe")\n'
                "name = values[0]\n"
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'(mapping := {{"key": "{name}"}}).update('
                '{"key": "safe"})\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'((mapping := {{"key": "{name}"}})["key"]) = "safe"\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'result = {{"x": (mapping := {{"key": "{name}"}})}}\n'
                'mapping.update({"key": "safe"})\n'
                'name = result["x"]["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
            (
                f'mapping = {{"key": "{name}"}}\n'
                'dict.update(mapping, mapping := {"key": "safe"})\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for index, text in enumerate(controls):
            source_class = "incomplete_nested_scope" if "nested = alias" in text else "bounded_static_mutation"
            with self.subTest(mutation=index, source_class=source_class):
                self.assertEqual([], SCANNER.scan_text(Path("config.py"), text))

        # A nested class does not capture the enclosing class's local aliases.
        # Keep the incomplete-source control above, and also exercise a valid
        # nested class that mutates the same global mapping before a setter.
        reachable_nested_mutation = (
            f'mapping = {{"key": "{name}"}}\n'
            "class Outer:\n"
            "    alias = mapping\n"
            "    class Inner:\n"
            "        nested = mapping\n"
            '        nested["key"] = "ordinary"\n'
            'name = mapping["key"]\n'
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [("ordinary", value)],
            self.execute_owned_setter_fixture(reachable_nested_mutation),
        )
        self.assertEqual([], SCANNER.scan_text(Path("config.py"), reachable_nested_mutation))

        preserved = (
            (
                'independent_container',
                (
                    'mutated = {"key": "safe"}\n'
                    "alias = mutated\n"
                    f'protected = {{"key": "{name}"}}\n'
                    "alias.clear()\n"
                    'name = protected["key"]\n'
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                7,
            ),
            (
                'rebound_alias',
                (
                    f'mapping = {{"key": "{name}"}}\n'
                    "alias = mapping\n"
                    'alias = {"key": "safe"}\n'
                    "alias.clear()\n"
                    'name = mapping["key"]\n'
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                7,
            ),
            (
                'nonmutating_lower',
                (
                    f'mapping = {{"key": "{name}"}}\n'
                    'mapping["key"].lower()\n'
                    'name = mapping["key"]\n'
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                5,
            ),
            (
                'independent_class_alias',
                (
                    f'mapping = {{"key": "{name}"}}\n'
                    "class Preserve:\n"
                    '    alias = {"key": "safe"}\n'
                    "    alias.clear()\n"
                    'name = mapping["key"]\n'
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                7,
            ),
            (
                'nonmutating_get',
                (
                    f'mapping = {{"key": "{name}"}}\n'
                    'mapping.get("key")\n'
                    'name = mapping["key"]\n'
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                5,
            ),
            (
                'nonmutating_count',
                (
                    f'values = ["{name}"]\n'
                    "values.count('ordinary')\n"
                    "name = values[0]\n"
                    f'secret = "{value}"\n'
                    "os.putenv(name, secret)\n"
                ),
                5,
            ),
        )
        for label, text, expected_line in preserved:
            with self.subTest(preserved=label):
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", expected_line, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))
                self.assertEqual([(name, value)], self.execute_owned_setter_fixture(text))

        # The original unfinished-source fixture calls count(name) before name
        # exists. This valid counterpart proves that a nonmutating count leaves
        # the literal alias intact and that its setter is actually reached.
        reachable_nonmutating_count = (
            f'values = ["{name}"]\n'
            'values.count("ordinary")\n'
            "name = values[0]\n"
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        self.assertEqual(
            [(name, value)], self.execute_owned_setter_fixture(reachable_nonmutating_count)
        )
        self.assertEqual(
            [("config.py", 5, f"live-looking value assigned to {name}")],
            SCANNER.scan_text(Path("config.py"), reachable_nonmutating_count),
        )

        target_side_effects = (
            (
                f'key = "{name}"\n'
                'mapping = {key: "safe"}\n'
                'mapping[(alias := key)]: str = "safe"\n'
                f'secret = "{value}"\n'
                "os.putenv(alias, secret)\n"
            ),
            (
                f'key = "{name}"\n'
                'mapping = {key: "safe"}\n'
                'mapping[(alias := key)] += "safe"\n'
                f'secret = "{value}"\n'
                "os.putenv(alias, secret)\n"
            ),
            (
                'old = {"key": "safe"}\n'
                f'new = "{name}"\n'
                'old[(old := new)] = "safe"\n'
                f'secret = "{value}"\n'
                "os.putenv(old, secret)\n"
            ),
            (
                'mapping = {"key": "safe"}\n'
                f'dict.update(mapping, mapping := {{"key": "{name}"}})\n'
                'name = mapping["key"]\n'
                f'secret = "{value}"\n'
                "os.putenv(name, secret)\n"
            ),
        )
        for text in target_side_effects:
            with self.subTest(target=text.splitlines()[2]):
                findings = SCANNER.scan_text(Path("config.py"), text)
                self.assertEqual(
                    [("config.py", 5, f"live-looking value assigned to {name}")],
                    findings,
                )
                self.assertNotIn(value, repr(findings))

        aggregate_positive = (
            f'result = {{"x": (mapping := {{"key": "{name}"}})}}\n'
            'name = result["x"]["key"]\n'
            f'secret = "{value}"\n'
            "os.putenv(name, secret)\n"
        )
        findings = SCANNER.scan_text(Path("config.py"), aggregate_positive)
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
        for class_header in ("class Holder(string secret)", "class Holder<T>(string secret)"):
            # A setter statement belongs in a member body, not directly in a class.
            primary = (class_header + " : Base<(string Left, string Right)> {\n"
                       "    void Use() {\n"
                       f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
                       "    }\n}\n")
            with self.subTest(primary_header=class_header):
                self.assertEqual([], SCANNER.scan_text(Path("config.cs"), primary))
        base_tuple_only = (
            "class Holder : Base<(string Left, string secret)> {\n"
            f'    private const string secret = "{value}";\n'
            "    void Use() {\n"
            f'        Environment.SetEnvironmentVariable("{name}", secret);\n'
            "    }\n}\n")
        findings = SCANNER.scan_text(Path("config.cs"), base_tuple_only)
        self.assertEqual([("config.cs", 4, f"live-looking value assigned to {name}")], findings)
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
        """Legacy fail_closed ID: no finding means unresolved, not a credential refusal."""
        name = "OPENAI_" + "API_KEY"
        value = "SyntheticSecretValue2026"
        cases = (
            ("valid_csharp_four_quote_raw_unresolved", "config.cs",
             f'Environment.SetEnvironmentVariable(""""{name}"""", """"{value}"""");\n'),
            ("valid_csharp_interpolated_raw_unresolved", "config.cs",
             f'Environment.SetEnvironmentVariable($$"""{name}""", $$"""{value}""");\n'),
            ("invalid_rust_byte_arguments", "config.rs",
             f'std::env::set_var(br#"{name}"#, br#"{value}"#);\n'),
        )
        for resolution, filename, text in cases:
            with self.subTest(resolution=resolution):
                self.assertEqual([], SCANNER.scan_text(Path(filename), text))
        # Valid unsupported C# forms carry known sensitive literals. Expanding that
        # grammar requires a separately reviewed detector policy, never a safety claim.

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
        'Unresolved dynamic keys and nonliteral references are coverage limits, not credential safety.'
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
        'Supported computed-key joins and multiline constants; invalid-source detection is labelled separately.'
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
        invalid_raw_call = 'process.env[String.raw("OPENAI_API_KEY")] = "' + value + '"\n'
        with self.subTest(source_class="invalid_String_raw_template_object"):
            findings = SCANNER.scan_text(Path("config.js"), invalid_raw_call)
            self.assertEqual([("config.js", 1, f"live-looking value assigned to {name}")], findings)
            self.assertNotIn(value, repr(findings))
        # String.raw`...` in method_wrappers is the valid tagged counterpart.
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
            run_git("add", "head.txt")  # Retain the leak only in HEAD.
            (root / "index.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            run_git("add", "index.txt")
            (root / "index.txt").write_text(
                f"{name}={placeholder}\n", encoding="utf-8"
            )
            (root / "working.txt").write_text(
                f"{name}={value}\n", encoding="utf-8"
            )

            findings, tracked, text_files = SCANNER.scan_repository(root)
            by_path = {path: detector for path, _line, detector in findings if "CF_API_TOKEN" in detector}
            for filename, source in (("head.txt", "HEAD"), ("index.txt", "index"),
                                     ("working.txt", "working tree"), ("utf16.txt", "HEAD/index/working tree")):
                self.assertEqual(by_path[filename], f"live-looking value assigned to {name} [{source}]")

            # A deleted working file must not erase the still committed leak.
            (root / "head.txt").unlink()
            deleted_findings, _, _ = SCANNER.scan_repository(root)
            self.assertIn(("head.txt", 1, f"live-looking value assigned to {name} [HEAD]"), deleted_findings)
            self.assertFalse(any(path == "head.txt" and "working tree" in detector for path, _, detector in deleted_findings))

            (root / "oversized.txt").write_bytes(b"x" * (SCANNER.MAX_TEXT_BYTES + 1))
            (root / "invalid-bom.txt").write_bytes(b"\xff\xfe\x00")
            run_git("add", "oversized.txt", "invalid-bom.txt")
            run_git("commit", "--quiet", "-m", "owned bounded snapshot fixtures")
            boundary_findings, _, _ = SCANNER.scan_repository(root)
            self.assertEqual({detector for path, _, detector in boundary_findings if path == "oversized.txt"},
                             {f"tracked file exceeds scan size limit [{source}]" for source in ("HEAD", "index", "working tree")})
            self.assertIn(("invalid-bom.txt", 0, "tracked text BOM has invalid encoded content [HEAD/index/working tree]"), boundary_findings)
            self.assertNotIn(value, repr(boundary_findings))

            # Real nonzero-stage index entries must refuse instead of silently
            # choosing one side of an unresolved merge.
            oid = subprocess.run(["git", "rev-parse", "HEAD:utf16.txt"], cwd=root,
                                 capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            stages = "".join(f"100644 {oid} {stage}\tconflict.txt\n" for stage in (1, 2, 3))
            subprocess.run(["git", "update-index", "--index-info"], cwd=root, input=stages.encode("utf-8"),
                           capture_output=True, check=True, timeout=10)
            with self.assertRaisesRegex(ValueError, "unmerged index entry"):
                SCANNER.scan_repository(root)

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

    def test_cli_scans_owned_git_snapshots_and_redacts_values(self) -> None:
        name = "CF_API" + "_TOKEN"
        value = "OwnedCredentialFixture2026"
        placeholder = "${CF_API_TOKEN}"
        environment = {
            key: item for key, item in os.environ.items() if not key.startswith("GIT_")
        }
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "owned-repository"
            root.mkdir()

            def run_git(*arguments: str) -> None:
                result = subprocess.run(
                    ["git", *arguments], cwd=root, env=environment,
                    capture_output=True, check=False, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

            def scan(target: Path) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-S", "-B", str(SCANNER_PATH), "--root", str(target)],
                    cwd=root, env=environment, text=True,
                    capture_output=True, check=False, timeout=10,
                )

            run_git("init", "--quiet")
            run_git("config", "user.name", "Test")
            run_git("config", "user.email", "test@example.invalid")
            run_git("config", "commit.gpgsign", "false")
            run_git("config", "core.autocrlf", "false")
            for filename in ("head.txt", "index.txt", "working.txt"):
                (root / filename).write_text(f"{name}={placeholder}\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "--quiet", "-m", "safe fixture")
            safe = scan(root)
            self.assertEqual(safe.returncode, 0, safe.stdout + safe.stderr)
            self.assertEqual(safe.stderr, "")
            self.assertIn("3 tracked paths; 3 decoded text snapshots", safe.stdout)

            (root / "head.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            run_git("add", "head.txt")
            run_git("commit", "--quiet", "-m", "owned HEAD fixture")
            (root / "head.txt").write_text(f"{name}={placeholder}\n", encoding="utf-8")
            run_git("add", "head.txt")
            (root / "index.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            run_git("add", "index.txt")
            (root / "index.txt").write_text(f"{name}={placeholder}\n", encoding="utf-8")
            (root / "working.txt").write_text(f"{name}={value}\n", encoding="utf-8")
            unsafe = scan(root)
            self.assertEqual(unsafe.returncode, 1)
            self.assertEqual(unsafe.stdout, "")
            self.assertIn("Tracked credential hygiene: FAIL", unsafe.stderr)
            for filename, source in (
                ("head.txt", "HEAD"), ("index.txt", "index"), ("working.txt", "working tree"),
            ):
                self.assertIn(
                    f"{filename}:1: live-looking value assigned to {name} [{source}]",
                    unsafe.stderr,
                )
            self.assertIn("3 tracked paths (6 decoded text snapshots", unsafe.stderr)
            self.assertNotIn(value, safe.stdout + safe.stderr + unsafe.stdout + unsafe.stderr)

            nonrepository = Path(directory) / "not-a-repository"
            nonrepository.mkdir()
            error = scan(nonrepository)
            self.assertEqual(error.returncode, 2)
            self.assertEqual(error.stdout, "")
            self.assertIn("Tracked credential hygiene: ERROR (CalledProcessError)", error.stderr)
            self.assertNotIn(value, error.stdout + error.stderr)

    def test_repository_wires_gate_before_dependency_installation(self) -> None:
        # Follow the repository's executable install paths, including the reusable
        # Task swarm. A gate in the Discord job cannot satisfy the Python job.
        for relative, job_id in (("repository-validation.yml", "repository"),
                                 ("repository-validation.yml", "discord"),
                                 ("task-swarm.yml", "validate"),
                                 ("cloudflare-candidate-validation.yml", "validate"),
                                 ("release.yml", "release")):
            with self.subTest(workflow=relative, job=job_id):
                workflow = yaml.safe_load((ROOT / ".github/workflows" / relative).read_text(encoding="utf-8"))
                job = workflow["jobs"][job_id]
                default = job.get("defaults", {}).get("run", {}).get("working-directory", ".")
                gate_positions = []
                installs = []
                for step_index, step in enumerate(job.get("steps", [])):
                    cwd = step.get("working-directory", default)
                    for line_index, command in enumerate(step.get("run", "").splitlines()):
                        command = command.strip()
                        if not command or command.startswith("#"):
                            continue
                        position = (step_index, line_index)
                        if command == "python -S -B tools/check_tracked_secret_hygiene.py":
                            self.assertEqual(cwd, ".")
                            self.assertNotIn("if", step)
                            self.assertFalse(step.get("continue-on-error", False))
                            gate_positions.append(position)
                        if command.startswith(("python -m pip install", "pnpm install", "npm install")):
                            installs.append(position)
                self.assertTrue(installs, "the install path must be observed, not vacuously accepted")
                self.assertTrue(gate_positions, "the owning job has no executable tracked gate")
                self.assertLess(min(gate_positions), min(installs))

    def test_ignore_and_policy_contracts_are_documented(self) -> None:
        secrets = {".env", ".env.production", "private.pem", "private.key", "private.p12", "private.pfx",
                   "credentials.json", "service-account-owned.json", "service_account_owned.json", "id_rsa", "id_ed25519"}
        examples = {".env.example", ".env.sample", ".env.template", ".env.production.example"}
        secrets |= {"component/" + name for name in secrets}
        examples |= {"component/" + name for name in examples}
        self.assertEqual(_ignored_paths(secrets | examples), secrets)
        command = "python -S -B tools/check_tracked_secret_hygiene.py"
        for relative in ("CONTRIBUTING.md", "SECURITY.md"):
            path = ROOT / relative
            text = path.read_text(encoding="utf-8")
            # 'text' fences are also executable contributor instructions in these docs.
            self.assertIn(command, [line.strip() for block in fenced_blocks(text)
                                    for line in block.splitlines()])
            assert_links(self, path, text)
        security = section((ROOT / "SECURITY.md").read_text(encoding="utf-8"), "credential-hygiene")
        normalized = " ".join(security.split())
        self.assertRegex(normalized, r"HEAD, the index, and tracked working-tree snapshots")
        self.assertRegex(normalized, r"(?:does not|doesn't) scan history older than HEAD")
        self.assertRegex(normalized, r"never prints a detected value")
        self.assertIn("untracked files", normalized)


if __name__ == "__main__":
    unittest.main()
