"""Required-check wiring, not a claim that GitHub branch protection changed."""
from pathlib import Path
import copy
import os
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def validate_gate(repository, discord):
    jobs = repository['jobs']
    assert jobs['discord']['uses'] == './.github/workflows/discord-runtime.yml'
    assert not jobs['discord'].get('continue-on-error')
    gate = jobs['validate']
    assert gate['name'] == 'Trusted repository validation'
    assert gate['needs'] == 'discord'
    assert gate['if'] == '${{ always() }}'
    guard = gate['steps'][0]
    assert guard['env']['DISCORD_RESULT'] == '${{ needs.discord.result }}'
    assert guard['run'] == 'test "$DISCORD_RESULT" = success'
    assert not guard.get('continue-on-error')
    assert not guard.get('if')
    assert set(discord['on']) == {'workflow_call'}
    child = discord['jobs']['test']
    assert set(child['strategy']['matrix']['os']) == {'ubuntu-latest', 'windows-latest'}
    assert not child.get('continue-on-error')
    for command in ('pnpm test', 'pnpm check'):
        step = next(step for step in child['steps'] if step.get('run') == command)
        assert not step.get('continue-on-error')
        assert not step.get('if')
    return guard['run']


class RequiredDiscordGateTests(unittest.TestCase):
    def setUp(self):
        self.repository = yaml.safe_load((ROOT / '.github/workflows/repository-validation.yml').read_text())
        # BaseLoader keeps YAML 1.1's boolean-looking 'on' as a string.
        self.discord = yaml.load((ROOT / '.github/workflows/discord-runtime.yml').read_text(), Loader=yaml.BaseLoader)

    def test_real_workflows_require_both_operating_systems(self):
        validate_gate(self.repository, self.discord)

    @unittest.skipIf(os.name == 'nt', 'The required gate runs on Linux')
    def test_failure_skipped_cancelled_and_missing_do_not_pass(self):
        command = validate_gate(self.repository, self.discord)
        for state in ('success', 'failure', 'skipped', 'cancelled', ''):
            with self.subTest(state=state):
                completed = subprocess.run(['bash', '-c', command], env={**os.environ, 'DISCORD_RESULT': state}, check=False)
                self.assertEqual(completed.returncode == 0, state == 'success')

    def test_removing_dependency_or_guard_is_detected(self):
        for key, value in (('needs', []), ('if', '${{ success() }}')):
            changed = copy.deepcopy(self.repository)
            changed['jobs']['validate'][key] = value
            with self.assertRaises(AssertionError):
                validate_gate(changed, self.discord)
        changed = copy.deepcopy(self.repository)
        changed['jobs']['validate']['steps'][0]['run'] = 'true'
        with self.assertRaises(AssertionError):
            validate_gate(changed, self.discord)

    def test_muting_node_tests_is_detected(self):
        for command in ('pnpm test', 'pnpm check'):
            changed = copy.deepcopy(self.discord)
            step = next(s for s in changed['jobs']['test']['steps'] if s.get('run') == command)
            step['continue-on-error'] = True
            with self.assertRaises(AssertionError):
                validate_gate(self.repository, changed)


if __name__ == '__main__':
    unittest.main()
