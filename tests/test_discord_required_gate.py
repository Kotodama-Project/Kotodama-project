"""The existing required status must include the complete Discord matrix."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class DiscordRequiredGateTests(unittest.TestCase):
    def test_required_context_depends_on_local_reusable_matrix(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/repository-validation.yml').read_text())
        jobs = workflow['jobs']
        self.assertEqual(jobs['discord']['uses'], './.github/workflows/discord-runtime.yml')
        required = jobs['validate']
        self.assertEqual(required['name'], 'Trusted repository validation')
        self.assertEqual(required['needs'], 'discord')
        self.assertEqual(required['if'], '${{ always() }}')
        gate = required['steps'][0]
        self.assertEqual(gate['env']['DISCORD_RESULT'], '${{ needs.discord.result }}')
        self.assertEqual(gate['run'], 'test "$DISCORD_RESULT" = success')
        discord = yaml.safe_load((ROOT / '.github/workflows/discord-runtime.yml').read_text())
        # PyYAML's YAML 1.1 resolver reads the Actions key `on` as True.
        triggers = discord.get('on', discord.get(True))
        self.assertIn('workflow_call', triggers)
        self.assertEqual(set(discord['jobs']['test']['strategy']['matrix']['os']),
                         {'ubuntu-latest', 'windows-latest'})
        commands = [step.get('run') for step in discord['jobs']['test']['steps']]
        self.assertIn('pnpm test', commands)
        self.assertIn('pnpm check', commands)
        fixture = next(step for step in discord['jobs']['test']['steps']
                       if step.get('name') == 'Prepare isolated Linux verification fixture')
        self.assertEqual(fixture['if'], "runner.os == 'Linux'")
        self.assertIn('KOTODAMA_TEST_VERIFIER_IMAGE=', fixture['run'])

    def test_failure_skip_cancellation_and_missing_results_do_not_pass(self):
        import os
        for result in ['success', 'failure', 'skipped', 'cancelled', '']:
            with self.subTest(result=result):
                status = subprocess.run(['bash', '-c', 'test "$DISCORD_RESULT" = success'],
                                        env={**os.environ, 'DISCORD_RESULT': result}, check=False)
                self.assertEqual(status.returncode == 0, result == 'success')


if __name__ == '__main__':
    unittest.main()
