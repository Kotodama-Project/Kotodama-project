"""The existing required status must include the complete Discord matrix."""
import os
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class DiscordRequiredGateTests(unittest.TestCase):
    def test_required_context_depends_on_the_named_inline_matrix(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/repository-validation.yml').read_text(encoding='utf-8'))
        jobs = workflow['jobs']
        discord = jobs['discord']
        self.assertEqual(discord['name'], 'test (${{ matrix.os }})')
        self.assertEqual(discord['runs-on'], '${{ matrix.os }}')
        self.assertEqual(discord['defaults']['run']['working-directory'],
                         'runtime/discord-template')
        self.assertNotIn('if', discord, 'both required contexts must always run')
        self.assertNotIn('uses', discord, 'a reusable job changes required context names')
        self.assertEqual(discord['timeout-minutes'], 10)
        required = jobs['validate']
        self.assertEqual(required['name'], 'Trusted repository validation')
        self.assertIn('discord', required['needs'])
        self.assertEqual(required['if'], '${{ always() }}')
        gate = next(step for step in required['steps']
                    if step.get('name') == 'Require the complete Discord test matrix')
        self.assertEqual(gate['env']['DISCORD_RESULT'], '${{ needs.discord.result }}')
        self.assertEqual(gate['run'], 'test "$DISCORD_RESULT" = success')
        # PyYAML's YAML 1.1 resolver reads the Actions key `on` as True.
        triggers = workflow.get('on', workflow.get(True))
        self.assertIn('pull_request', triggers)
        self.assertEqual(triggers['push']['branches'], ['main'])
        self.assertNotIn('paths', triggers.get('pull_request') or {})
        self.assertNotIn('paths-ignore', triggers.get('pull_request') or {})
        self.assertEqual(set(discord['strategy']['matrix']['os']),
                         {'ubuntu-latest', 'windows-latest'})
        self.assertEqual(
            {discord['name'].replace('${{ matrix.os }}', os_name)
             for os_name in discord['strategy']['matrix']['os']},
            {'test (ubuntu-latest)', 'test (windows-latest)'},
        )
        commands = [step.get('run') for step in discord['steps']]
        self.assertIn('pnpm test', commands)
        self.assertIn('pnpm check', commands)
        self.assertIn('pnpm install --frozen-lockfile --ignore-scripts', commands)
        self.assertIn('npm install --global pnpm@11.19.0', commands)
        fixture = next(step for step in discord['steps']
                       if step.get('name') == 'Prepare isolated Linux verification fixture')
        self.assertEqual(fixture['if'], "runner.os == 'Linux'")
        self.assertIn('KOTODAMA_TEST_VERIFIER_IMAGE=', fixture['run'])
        self.assertRegex(fixture['run'], r"node:24-bookworm-slim@sha256:[0-9a-f]{64}")
        self.assertIn('docker pull "$fixture"', fixture['run'])
        for os_name in ['Linux', 'Windows']:
            encoder = next(step for step in discord['steps']
                           if step.get('name') == f'Install audio encoder ({os_name})')
            self.assertEqual(encoder['if'], f"runner.os == '{os_name}'")
            self.assertIn('ffmpeg', encoder['run'])

    def test_one_automatic_discord_matrix_per_event_including_reusable_calls(self):
        workflows = {}
        for path in (ROOT / '.github/workflows').glob('*.y*ml'):
            workflows[path.relative_to(ROOT).as_posix()] = yaml.safe_load(
                path.read_text(encoding='utf-8'))

        def discord_matrices(path, visited=()):
            self.assertNotIn(path, visited, 'reusable workflow cycle')
            jobs = workflows[path]['jobs']
            count = 0
            for job in jobs.values():
                reference = job.get('uses', '')
                if reference.startswith('./.github/workflows/'):
                    count += discord_matrices(reference[2:], (*visited, path))
                commands = [step.get('run', '') for step in job.get('steps', [])]
                directory = job.get('defaults', {}).get('run', {}).get('working-directory')
                if directory == 'runtime/discord-template' and 'pnpm test' in commands:
                    self.assertEqual(set(job['strategy']['matrix']['os']),
                                     {'ubuntu-latest', 'windows-latest'})
                    count += 1
            return count

        for event in ['pull_request', 'push']:
            with self.subTest(event=event):
                count = 0
                for path, workflow in workflows.items():
                    triggers = workflow.get('on', workflow.get(True))
                    if event in triggers:
                        count += discord_matrices(path)
                self.assertEqual(count, 1, 'the full Discord suite must run once per OS')

    def test_dependency_review_keeps_its_required_context(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/dependency-review.yml').read_text(encoding='utf-8'))
        self.assertEqual(workflow['jobs']['dependency-review']['name'], 'Dependency review')

    # The gate step runs on the Linux runner; on Windows `bash` may resolve to
    # WSL, which does not inherit this process's environment.
    @unittest.skipUnless(os.name == 'posix', 'the gate step runs under bash on Linux')
    def test_failure_skip_cancellation_and_missing_results_do_not_pass(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/repository-validation.yml').read_text(encoding='utf-8'))
        gate = next(step for step in workflow['jobs']['validate']['steps']
                    if step.get('name') == 'Require the complete Discord test matrix')
        for result in ['success', 'failure', 'skipped', 'cancelled', '']:
            with self.subTest(result=result):
                status = subprocess.run(['bash', '-c', gate['run']],
                                        env={**os.environ, 'DISCORD_RESULT': result}, check=False)
                self.assertEqual(status.returncode == 0, result == 'success')


if __name__ == '__main__':
    unittest.main()
