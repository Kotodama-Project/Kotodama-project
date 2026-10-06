from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('toolchain_verify', ROOT/'templates/native-proxmox/cloudflare-os/verify-toolchain.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeToolchainIntegrityTests(unittest.TestCase):
    def test_archive_mutation_is_refused_for_both_declared_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp)/'fixture.archive'
            before = b'bounded public artifact fixture'
            for algorithm in ['sha256', 'sha512']:
                artifact.write_bytes(before)
                expected = hashlib.new(algorithm, before).hexdigest()
                self.assertEqual(module.verify_archive(artifact, algorithm, expected), expected)
                artifact.write_bytes(before+b'tampered')
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    module.verify_archive(artifact, algorithm, expected)

    def test_installer_verifies_both_archives_before_extract_or_execution(self):
        source = (ROOT/'templates/native-proxmox/cloudflare-os/install.sh').read_text(encoding='utf-8')
        check = source.index('python3 /root/kotodama-template-assets/verify-toolchain.py')
        self.assertLess(source.index('-o pnpm.tgz'), check)
        self.assertLess(check, source.index('tar -xJf'))
        self.assertLess(check, source.index('npm install'))
        self.assertIn('--offline ./pnpm.tgz', source)
        self.assertNotIn('node-shasums.txt', source)
        for row in module.PINS.values():
            self.assertIn(row['url'], source)


if __name__ == '__main__':
    unittest.main()
