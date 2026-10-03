import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tools.build_release_sbom import LOCKS, build_bom, npm_components, python_components

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSbomTests(unittest.TestCase):
    def test_all_real_locks_are_complete_and_deterministic(self):
        for name, relative in LOCKS.items():
            with self.subTest(lock=name):
                raw = (ROOT / relative).read_bytes()
                bom = build_bom(raw, name, relative, 'v0.2.0-preview')
                self.assertEqual(bom, build_bom(raw, name, relative, 'v0.2.0-preview'))
                expected = len(yaml.safe_load(raw)['packages']) if name == 'discord' else sum(
                    '==' in line and not line.lstrip().startswith('#') for line in raw.decode().splitlines())
                self.assertEqual(len(bom['components']), expected)
                self.assertIn({'name': 'kotodama:lock:sha256', 'value': hashlib.sha256(raw).hexdigest()}, bom['metadata']['properties'])
                self.assertNotIn('dependencies', bom)
                self.assertTrue(all(c['hashes'] and c['purl'] == c['bom-ref'] for c in bom['components']))

    def test_python_extras_markers_and_hashes(self):
        h = 'a' * 64
        text = f'Name_One[feature]==1.2.3 ; sys_platform == "win32" \\\n    --hash=sha256:{h}\n'
        c = python_components(text)[0]
        self.assertEqual(c['purl'], 'pkg:pypi/name-one@1.2.3')
        self.assertEqual(c['hashes'], [{'alg': 'SHA-256', 'content': h}])

    def test_refuse_unpinned_unhashed_and_unknown_inputs(self):
        for text in ['name>=1.0', 'name==1.0', '-r private.txt', 'name @ https://example.com/a.whl', 'name==1 --hash=sha256:nope']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                python_components(text)
        with self.assertRaises(ValueError):
            build_bom(b'', 'python-ci', LOCKS['python-ci'], 'v1')
        text = f'name==1 --hash=sha256:{"a" * 64}\n'
        with self.assertRaises(ValueError):
            build_bom((text + text).encode(), 'python-ci', LOCKS['python-ci'], 'v1')

    def test_scoped_npm_hash_and_rejections(self):
        digest = b'a' * 64
        integrity = 'sha512-' + base64.b64encode(digest).decode()
        lock = {'lockfileVersion': '9.0', 'packages': {'@scope/package@1.2.3': {'resolution': {'integrity': integrity}}}}
        c = npm_components(yaml.safe_dump(lock))[0]
        self.assertEqual(c['purl'], 'pkg:npm/%40scope/package@1.2.3')
        self.assertEqual(c['hashes'][0]['content'], digest.hex())
        for bad in ['sha512-YQ==', 'sha512-!', '', 'sha1-YQ==']:
            lock['packages']['@scope/package@1.2.3']['resolution']['integrity'] = bad
            with self.subTest(integrity=bad), self.assertRaises(ValueError):
                npm_components(yaml.safe_dump(lock))
        lock['lockfileVersion'] = '10.0'
        with self.assertRaises(ValueError):
            npm_components(yaml.safe_dump(lock))

    def test_duplicate_yaml_and_malformed_marker_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_YAML_KEY'):
            npm_components("lockfileVersion: '9.0'\npackages:\n  name@1.2.3: {}\n  name@1.2.3: {}\n")
        for marker in ['not_a_marker', 'sys_platform == "win32" +', 'sys_platform == "win32" --hash=sha256:bad', '(sys_platform == "win32"', 'sys_platform == "win32" and']:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                python_components(f'name==1 ; {marker} --hash=sha256:{"a" * 64}')

    def test_cli_refuses_overwrite_and_invalid_release(self):
        with tempfile.TemporaryDirectory() as temp:
            cmd = [sys.executable, '-B', str(ROOT / 'tools/build_release_sbom.py'), '--release', 'v1.2.3-preview', '--output-dir', temp]
            first = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            files = list(Path(temp).glob('*.cdx.json'))
            self.assertEqual(len(files), 3)
            before = {p.name: p.read_bytes() for p in files}
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in files})
            cmd[4] = '../escape'
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)

    def test_workflow_generates_hashes_attests_and_attaches_every_sbom(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['release']['steps']
        scripts = '\n'.join(s.get('run', '') for s in steps)
        self.assertIn('--require-hashes -r requirements-ci.txt', scripts)
        self.assertIn('tools/build_release_sbom.py', scripts)
        build = next(s['run'] for s in steps if 'tools/build_release_sbom.py' in s.get('run', ''))
        self.assertNotIn('${{', build)
        self.assertIn('"$GITHUB_REF_NAME"', build)
        attestation = next(s for s in steps if s.get('uses', '').startswith('actions/attest-build-provenance@'))
        self.assertRegex(attestation['uses'], r'@[a-f0-9]{40}$')
        hashes = next(s['run'] for s in steps if 'sha256sum' in s.get('run', ''))
        upload = next(s['run'] for s in steps if 'gh release create' in s.get('run', ''))
        for name in LOCKS:
            artifact = f'sbom-{name}-'
            self.assertIn(artifact, hashes)
            self.assertIn(artifact, attestation['with']['subject-path'])
            self.assertIn(artifact, upload)
        self.assertIn('--draft --prerelease', upload)


if __name__ == '__main__':
    unittest.main()
