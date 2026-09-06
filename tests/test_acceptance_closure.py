"""Prevent loss of acceptance coverage and contradictory current-state views."""
from pathlib import Path
import json
import hashlib
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceClosureTests(unittest.TestCase):
    def test_all_user_requested_ids_have_resumable_acceptance(self):
        data = json.loads((ROOT / 'docs/acceptance/requirements.json').read_text(encoding='utf-8'))
        rows = data['requirements']
        self.assertEqual([r['id'] for r in rows], [f'R{i:02}' for i in range(1, 69)])
        self.assertFalse(data['all_requirements_accepted'])
        self.assertFalse(data['automatic_resume'])
        self.assertEqual(data['work_state'], 'CLOSED_PENDING_EXPLICIT_REOPEN')
        current_readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertEqual(data['source']['closing_readme']['sha256'], hashlib.sha256(current_readme.encode('utf-8')).hexdigest())
        self.assertEqual(data['source']['closing_readme']['lines'], len(current_readme.splitlines()))
        evidence = {e['id'] for e in json.loads((ROOT / 'docs/acceptance/evidence.json').read_text(encoding='utf-8'))['observations']}
        for r in rows:
            with self.subTest(requirement=r['id']):
                for key in ['positive_acceptance', 'negative_and_recovery', 'owner_route', 'next_action', 'source_url']:
                    self.assertTrue(r[key])
                self.assertLessEqual(set(r['evidence_refs']), evidence)
                self.assertEqual(r['overall_acceptance'], 'NOT_DECLARED')
                page = (ROOT / f'docs/acceptance/{r["group"]}.md').read_text(encoding='utf-8')
                self.assertIn(f'<a id="{r["id"].lower()}"></a>', page)
                self.assertIn(r['positive_acceptance'], page)
                self.assertIn(r['negative_and_recovery'], page)
                self.assertNotRegex(r['owner_route'], r'KTP-TASK-\d+')
                if r['id'] in {'R03', 'R05', 'R37', 'R54'}:
                    self.assertIn('Telegram', r['positive_acceptance'])

    def test_current_status_and_roadmap_share_the_snapshot(self):
        snapshot = json.loads((ROOT / 'docs/acceptance/github-snapshot.json').read_text(encoding='utf-8'))
        blocks = []
        for path in ['STATUS.md', 'ROADMAP.md']:
            content = (ROOT / path).read_text(encoding='utf-8')
            block = content.split('## Current public state — 2026-09-06', 1)[1].split('## Historical observations below', 1)[0]
            self.assertIn(snapshot['default_commit'], block)
            self.assertIn('NO_GO_UNPUBLISHED', block)
            self.assertIn('manual', block)
            for p in snapshot['pulls']:
                self.assertIn(p['head'], block)
            blocks.append(block)
        self.assertEqual(blocks[0], blocks[1])

    def test_all_observed_issue_bodies_have_an_obligation_route(self):
        issues = json.loads((ROOT / 'docs/acceptance/issues.json').read_text(encoding='utf-8'))['issues']
        self.assertEqual(len(issues), 25)
        self.assertEqual(len({i['number'] for i in issues}), 25)
        for i in issues:
            self.assertRegex(i['body_sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(i['remaining_obligation'])
            self.assertTrue(i['requirement_ids'])

    def test_closing_markdown_links_resolve_locally(self):
        files = list((ROOT / 'docs/acceptance').glob('*.md')) + [ROOT / 'docs/CLOSING-2026-09-06.md']
        for file in files:
            for target in re.findall(r'\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
                if '://' in target:
                    continue
                path, _, anchor = target.partition('#')
                resolved = (file.parent / path).resolve() if path else file
                self.assertTrue(resolved.is_relative_to(ROOT), target)
                self.assertTrue(resolved.is_file(), f'{file.name}: {target}')
                if anchor and re.fullmatch(r'(?:r\d{2}|e\d{2})', anchor):
                    self.assertIn(f'id="{anchor}"', resolved.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
