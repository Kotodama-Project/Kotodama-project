"""Offline filesystem/Git regressions for the native template seal boundary."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'native_template_seal', ROOT / 'templates/native-proxmox/cloudflare-os/seal-check.py')
seal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seal)


class NativeTemplateSeal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.install = self.base / 'install'
        self.home = self.base / 'home'
        self.config = self.base / 'config'
        self.skel = self.base / 'skel'
        for path in (self.install, self.home, self.config, self.skel):
            path.mkdir()
        for name in seal.INSTALL_ENTRIES:
            (self.install / name).mkdir()
        self.core = self.install / 'core'
        for name in seal.HOME_DEFAULTS:
            for directory in (self.home, self.skel):
                (directory / name).write_text('# default shell file\n', encoding='utf-8')
        self.git('init', '-q')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'user.name', 'Template Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write(self.core / '.gitignore', '*.json\nnode_modules/\n.wrangler/\n.env\n.dev.vars\n')
        self.write(self.core / 'pnpm-lock.yaml', 'lockfileVersion: 9\n')
        self.write(self.core / 'source.txt', 'official fixture source\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic official source fixture')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        self.write(self.core / 'node_modules/package/index.js', '// dependency\n')
        self.write(self.home / '.cache/pnpm/metadata.json', '{}\n')
        self.baseline = self.record()

    def write(self, path, value='synthetic fixture\n'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.core), *args], text=True, stderr=subprocess.PIPE)

    def remove_added_file(self, path, scope):
        path.unlink()
        parent = path.parent
        while parent != scope and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def record(self, state='inactive'):
        return seal.record_install(self.install, self.home, self.config, self.skel, state, self.revision)

    def verify(self, state='inactive'):
        return seal.verify_install(self.baseline, self.install, self.home, self.config, state, self.revision)

    def test_pristine_fixture_has_bounded_proof(self):
        result = self.verify()
        self.assertTrue(result['templateSourceClean'])
        self.assertTrue(result['installInventoryMatches'])
        self.assertEqual(result['coreRevision'], self.revision)
        self.assertEqual(result['proof_scope'], list(map(str, [self.install, self.home, self.config])))
        for unsupported in ('accountsBaked', 'conversationDataBaked', 'providerConfigurationBaked'):
            self.assertNotIn(unsupported, result)
        self.assertIn('outside this proof', ' '.join(result['limits']))

    def test_unknown_and_ignored_core_data_cannot_seed_or_verify(self):
        for name in ('unknown-account.json', 'saved-document.txt', 'packages/app/accounts.json'):
            with self.subTest(name=name):
                path = self.core / name
                self.write(path, '{}')
                for operation in (self.record, self.verify):
                    with self.assertRaises(seal.SealError):
                        operation()
                self.remove_added_file(path, self.core)
                self.assertTrue(self.verify()['installInventoryMatches'])

    def test_unknown_home_data_cannot_seed_or_verify(self):
        for name in ('accounts.json', 'documents/note.txt', '.config/provider/session.json', '.cache/accounts.json'):
            with self.subTest(name=name):
                path = self.home / name
                self.write(path, '{}')
                for operation in (self.record, self.verify):
                    with self.assertRaises(seal.SealError):
                        operation()
                self.remove_added_file(path, self.home)
                self.assertTrue(self.verify()['installInventoryMatches'])

    def test_home_shell_file_modified_before_record_is_rejected(self):
        self.write(self.home / '.profile', 'export PRIVATE_ACCOUNT=synthetic\n')
        with self.assertRaises(seal.SealError):
            self.record()

    def test_tracked_modified_and_staged_source_rejected(self):
        self.write(self.core / 'source.txt', 'changed\n')
        for staged in (False, True):
            if staged:
                self.git('add', 'source.txt')
            with self.subTest(staged=staged):
                with self.assertRaises(seal.SealError):
                    self.record()
                with self.assertRaises(seal.SealError):
                    self.verify()

    def test_assume_unchanged_cannot_hide_tracked_changes(self):
        self.git('update-index', '--assume-unchanged', 'source.txt')
        self.write(self.core / 'source.txt', 'changed\n')
        with self.assertRaises(seal.SealError):
            self.record()

    def test_wrong_head_rejected(self):
        with self.assertRaises(seal.SealError):
            seal.verify_install(self.baseline, self.install, self.home, self.config, 'inactive', '0' * 40)

    def test_modified_install_baseline_bytes_rejected(self):
        self.write(self.core / 'node_modules/package/index.js', '// changed\n')
        with self.assertRaisesRegex(seal.SealError, 'INVENTORY_MISMATCH'):
            self.verify()

    def test_added_cache_data_after_record_is_rejected(self):
        self.write(self.home / '.cache/pnpm/saved-account.json', '{}')
        with self.assertRaisesRegex(seal.SealError, 'INVENTORY_MISMATCH'):
            self.verify()

    def test_deleted_install_baseline_entry_rejected(self):
        (self.core / 'node_modules/package/index.js').unlink()
        with self.assertRaisesRegex(seal.SealError, 'INVENTORY_MISMATCH'):
            self.verify()

    def test_unexpected_install_root_entry_rejected(self):
        self.write(self.install / 'saved-account.json', '{}')
        with self.assertRaises(seal.SealError):
            self.record()

    def test_instance_or_known_provider_state_rejected(self):
        self.write(self.config / 'os-instance.json', '{}')
        with self.assertRaises(seal.SealError):
            self.record()
        (self.config / 'os-instance.json').unlink()
        self.write(self.core / '.env', 'SYNTHETIC=fixture\n')
        with self.assertRaises(seal.SealError):
            self.record()

    def test_active_transitioning_failed_and_unknown_runtime_rejected(self):
        for state in ('active', 'activating', 'deactivating', 'failed', 'unknown', ''):
            with self.subTest(state=state):
                for operation in (self.record, self.verify):
                    with self.assertRaises(seal.SealError):
                        operation(state)

    def test_symlink_escape_rejected(self):
        target = self.base / 'outside.txt'
        self.write(target)
        link = self.core / 'node_modules/package/escape'
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f'Host cannot create symlinks: {error.winerror}')
        with self.assertRaisesRegex(seal.SealError, 'SYMLINK_ESCAPE'):
            self.record()
        with self.assertRaisesRegex(seal.SealError, 'SYMLINK_ESCAPE'):
            self.verify()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction escape fixture')
    def test_windows_directory_junction_escape_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.write(outside / 'account.json', '{}')
        junction = self.core / 'node_modules' / 'escaped-directory'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                       capture_output=True, check=True)
        with self.assertRaisesRegex(seal.SealError, 'SYMLINK_ESCAPE'):
            self.record()

    def test_symlink_branch_rejects_escape_without_host_symlink_privilege(self):
        link = self.core / 'node_modules' / 'link'
        self.write(link)
        actual_lstat, actual_resolve = Path.lstat, Path.resolve

        def lstat(path):
            if path == link:
                return types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)
            return actual_lstat(path)

        def resolve(path, *args, **kwargs):
            return self.base if path == link else actual_resolve(path, *args, **kwargs)

        with patch.object(Path, 'lstat', lstat), patch.object(Path, 'resolve', resolve):
            with self.assertRaisesRegex(seal.SealError, 'SYMLINK_ESCAPE'):
                seal.inventory(self.install)

    def test_inventory_cannot_be_overwritten(self):
        path = self.base / 'protected' / 'inventory.json'
        # Filesystem exclusivity is portable; Unix ownership is tested below.
        with patch.object(seal, 'require_root_owned'):
            seal.save_inventory(path, self.baseline)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                seal.save_inventory(path, {'replacement': True})
            self.assertEqual(path.read_bytes(), original)

    def test_non_root_or_writable_inventory_rejected(self):
        path = self.base / 'inventory.json'
        for uid, mode in ((1000, stat.S_IFREG | 0o600), (0, stat.S_IFREG | 0o666),
                          (0, stat.S_IFLNK | 0o600)):
            with self.subTest(uid=uid, mode=mode):
                with patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_uid=uid, st_mode=mode)):
                    with self.assertRaises(seal.SealError):
                        seal.require_root_owned(path)

    def test_scoped_dependency_symlink_is_supported_and_bound(self):
        link = self.core / 'node_modules/package/link.js'
        try:
            link.symlink_to('index.js')
        except OSError as error:
            self.skipTest(f'Host cannot create symlinks: {error.winerror}')
        self.baseline = self.record()
        self.assertTrue(self.verify()['installInventoryMatches'])
        link.unlink()
        with self.assertRaises(seal.SealError):
            self.verify()

    def test_cli_does_not_offer_path_or_revision_overrides(self):
        output = subprocess.check_output([os.sys.executable, '-B', str(SPEC.origin), '--help'], text=True)
        self.assertIn('--record-install', output)
        self.assertNotIn('--root', output)
        self.assertNotIn('--revision', output)


if __name__ == '__main__':
    unittest.main()
