"""Exercise repository guard failures using disposable files, never invented live docs."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'validate_repository', Path(__file__).resolve().parents[1] / 'tools' / 'validate_repository.py'
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class RepositoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = set(validator.REQUIRED)
        for name in self.files:
            self.write(name, '# Fixture\n' if name.endswith('.md') else '')
        self.write('.github/workflows/repository-validation.yml',
                   'jobs:\n  check:\n    steps:\n      - uses: actions/checkout@' + 'a' * 40 + '\n')

    def write(self, name, content):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding='utf-8')
        self.files.add(name)

    def check(self):
        return validator.validate_repository(self.root, self.files)

    def test_minimum_fixture_is_valid(self):
        self.assertEqual(self.check(), [])

    def test_missing_required_file_is_rejected(self):
        self.files.remove('AGENTS.md')
        self.assertIn('missing required file: AGENTS.md', self.check())

    def test_broken_link_is_rejected(self):
        self.write('README.md', '[missing](docs/missing.md)\n')
        self.assertTrue(any('broken Markdown link' in e for e in self.check()))

    def test_relative_and_reference_links_are_checked(self):
        self.write('docs/WORKFLOW.md', '[Home](../README.md#fixture)\n[brief][b]\n[Root](../)\n\n[b]: ../templates/project-brief.md\n')
        self.assertEqual(self.check(), [])
        self.write('docs/WORKFLOW.md', '[brief][b]\n\n[b]: missing.md\n')
        self.assertTrue(any('broken Markdown link' in e for e in self.check()))

    def test_broken_anchor_and_case_are_rejected(self):
        self.write('README.md', '[missing](docs/WORKFLOW.md#absent)\n[case](docs/workflow.md)\n')
        errors = self.check()
        self.assertTrue(any('broken Markdown anchor' in e for e in errors))
        self.assertTrue(any('broken Markdown link' in e for e in errors))

    def test_code_examples_and_remote_links_do_not_require_local_targets(self):
        self.write('README.md', '```md\n[x](missing.md)\n```\n`[x](missing.md)`\n[x](https://example.com/page)\n')
        self.assertEqual(self.check(), [])

    def test_retired_runtime_manifest_and_tool_are_rejected(self):
        for name in ('runtime/discord-template/package.json', 'pyproject.toml', 'tools/knowledge_base.py'):
            self.write(name, '')
        self.assertEqual(sum('retired surface' in e for e in self.check()), 3)

    def test_retirement_document_can_name_old_paths(self):
        self.write('docs/RETIREMENT.md', 'Retired: `runtime/task_swarm` and `pyproject.toml`.\n')
        self.assertEqual(self.check(), [])

    def test_unpinned_actions_and_new_workflows_are_rejected(self):
        self.write('.github/workflows/retired-release.yml', 'steps:\n  - uses: actions/checkout@v7\n')
        errors = self.check()
        self.assertTrue(any('unapproved workflow' in e for e in errors))
        self.assertTrue(any('full commit SHA' in e for e in errors))

    def test_quoted_action_with_comment_is_valid(self):
        self.write('.github/workflows/repository-validation.yml',
                   'steps:\n  - uses: "actions/checkout@' + 'a' * 40 + '" # pinned\n')
        self.assertEqual(self.check(), [])

    def test_quoted_keys_and_flow_action_syntax_cannot_hide_unpinned_action(self):
        self.write('.github/workflows/repository-validation.yml',
                   'steps:\n  - "uses": actions/checkout@main\n  - { uses: actions/checkout@main }\n')
        errors = self.check()
        self.assertTrue(any('full commit SHA' in e for e in errors))
        self.assertTrue(any('plain action syntax' in e for e in errors))

    def test_inline_code_in_heading_keeps_its_anchor(self):
        self.write('README.md', '# Use `Codex`\n\n[Here](#use-codex)\n')
        self.assertEqual(self.check(), [])

    def test_privileged_pr_trigger_is_rejected(self):
        self.write('.github/workflows/repository-validation.yml', 'on:\n  pull_request_target:\n')
        self.assertTrue(any('privileged PR trigger' in e for e in self.check()))

    def test_secret_and_database_filenames_are_rejected(self):
        for name in ('.env.local', 'credentials.json', 'local/kotodama.sqlite-wal', 'private.key'):
            self.write(name, '')
        self.assertEqual(sum('secret or runtime-state filename' in e for e in self.check()), 4)

    def test_missing_tracked_bytes_are_rejected(self):
        (self.root / 'AGENTS.md').unlink()
        self.assertIn('tracked path is not a regular file: AGENTS.md', self.check())


if __name__ == '__main__':
    unittest.main()
