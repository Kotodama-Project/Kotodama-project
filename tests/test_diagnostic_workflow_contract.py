"""Static fail-visible workflow and classification contracts (not a deployment)."""
from pathlib import Path
import fnmatch
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/control-plane-audit.yml').read_text(encoding='utf-8')

    def test_independent_read_only_audits_run_after_test_failure(self):
        for step in ('knowledge', 'control_plane', 'maintenance'):
            with self.subTest(step=step):
                self.assertIn(f"id: {step}\n        if: ${{{{ !cancelled() && steps.dependencies.outcome == 'success' }}}}", self.workflow)
        self.assertIn('python -m unittest discover -s tests -v', self.workflow)
        self.assertNotIn('continue-on-error', self.workflow)
        self.assertNotIn('|| true', self.workflow)

    def test_each_gate_outcome_is_reported_without_inventing_success(self):
        for step in ('dependencies', 'regression', 'knowledge', 'control_plane', 'maintenance'):
            self.assertIn('${{ steps.' + step + '.outcome }}', self.workflow)
        self.assertIn('GITHUB_STEP_SUMMARY', self.workflow)
        self.assertIn('"not_reported"', self.workflow)

    def test_read_only_pinned_and_bounded_jobs(self):
        self.assertIn('contents: read', self.workflow)
        self.assertNotIn('pull_request_target', self.workflow)
        for action in re.findall(r'uses:\s*(\S+)', self.workflow):
            self.assertRegex(action, r'^[^@]+@[0-9a-f]{40}$')
        self.assertEqual(self.workflow.count('persist-credentials: false'), 2)
        self.assertEqual(self.workflow.count('timeout-minutes:'), 2)

    def test_focused_suite_runs_on_linux_and_windows(self):
        self.assertIn('os: [ubuntu-latest, windows-latest]', self.workflow)
        self.assertIn('fail-fast: false', self.workflow)
        self.assertIn('"test_agent_status*.py"', self.workflow)

    def test_skill_is_classified_without_lowering_or_hiding_unknowns(self):
        registry = json.loads((ROOT / 'governance/knowledge-registry.json').read_text(encoding='utf-8'))
        self.assertEqual(registry['inventory_scope']['minimum_classification_coverage'], 0.98)
        owners = [f['id'] for f in registry['fact_families']
                  if 'skills/kotodama-agent-status/SKILL.md' in f['classification_patterns']]
        self.assertEqual(owners, ['agent_portfolio'])
        for unknown in ('NONEXISTENT', 'NONEXISTENT2', 'NONEXISTENT3', 'docs/.knowledge-tree-probe'):
            self.assertFalse(any(fnmatch.fnmatch(unknown, p) for p in registry['inventory_scope']['exclude']))


if __name__ == '__main__':
    unittest.main()
