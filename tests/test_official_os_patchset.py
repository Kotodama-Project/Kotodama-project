from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('patchset', ROOT / 'tools/verify_official_os_patchset.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OfficialPatchScopeTests(unittest.TestCase):
    def test_exact_patches_are_bound_without_applying(self):
        result = module.verify(ROOT / 'runtime/cloudflare-os-kotodama/patches')
        self.assertTrue(result['exact_changed_paths_verified'])
        self.assertFalse(result['applied'])

    def test_extra_hunk_is_refused_even_if_patch_digest_is_rebound(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'patches'
            shutil.copytree(ROOT / 'runtime/cloudflare-os-kotodama/patches', directory)
            manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            row = manifest['files'][0]
            patch = directory / row['patch']
            patch.write_bytes(patch.read_bytes()+b'\ndiff --git a/unlisted.txt b/unlisted.txt\n--- a/unlisted.txt\n+++ b/unlisted.txt\n@@ -1 +1 @@\n-before\n+after\n')
            row['patchSha256'] = hashlib.sha256(patch.read_bytes()).hexdigest()
            (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'changed path'):
                module.verify(directory)

    def test_tamper_and_mode_change_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'patches'
            shutil.copytree(ROOT / 'runtime/cloudflare-os-kotodama/patches', directory)
            manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            row = manifest['files'][0]
            patch = directory / row['patch']
            patch.write_bytes(patch.read_bytes()+b'\nold mode 100644\nnew mode 100755\n')
            with self.assertRaisesRegex(ValueError, 'digest'):
                module.verify(directory)
            row['patchSha256'] = hashlib.sha256(patch.read_bytes()).hexdigest()
            (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'metadata'):
                module.verify(directory)


if __name__ == '__main__':
    unittest.main()
