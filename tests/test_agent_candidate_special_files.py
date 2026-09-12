"""Both public candidate readers must refuse special files before a blocking read."""
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
READERS = [ROOT / 'tools' / ('validate_company_pack_agent_' + name + '_candidate.py')
           for name in ['swarm_execution', 'orchestration_route_binding']]


class SpecialFileTests(unittest.TestCase):
    def test_nonregular_file_is_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_bytes(b'{}')
            special = os.stat_result((stat.S_IFIFO | 0o600, 0, 0, 1, 0, 0, 0, 0, 0, 0))
            for reader in READERS:
                with self.subTest(reader=reader.name):
                    read = runpy.run_path(str(reader))['read_bounded']
                    with patch.object(Path, 'lstat', return_value=special), patch.object(Path, 'open', side_effect=AssertionError('blocking open reached')):
                        with self.assertRaises(OSError):
                            read(path)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX named-pipe integration')
    def test_real_fifo_returns_structured_refusal_without_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.fifo'
            os.mkfifo(path)
            for reader in READERS:
                with self.subTest(reader=reader.name):
                    result = subprocess.run([sys.executable, '-B', str(reader), str(path)], capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stderr, '')
                    self.assertIn('INPUT_INVALID', result.stdout)


if __name__ == '__main__':
    unittest.main()
