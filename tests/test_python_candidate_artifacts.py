"""Archive boundary and repeatability, independent of installed build tooling."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import build_python_candidate as builder


class PythonCandidateArtifactsTests(unittest.TestCase):
    def test_metadata_normalization_is_reproducible_and_preserves_contents(self):
        contents = {"candidate/z.txt": b"Japanese: \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\n", "candidate/a.txt": b"a\n"}
        for wheel in (False, True):
            first = builder.normalize_archive(Path("unused"), contents, 1788307200, wheel=wheel)
            second = builder.normalize_archive(Path("unused"), dict(reversed(list(contents.items()))), 1788307200, wheel=wheel)
            self.assertEqual(first, second)
            self.assertNotEqual(first, builder.normalize_archive(Path("unused"), contents, 1788307210, wheel=wheel))

    def test_unlisted_and_duplicate_wheel_files_are_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("runtime/private.py", b"not allowed")
            with self.assertRaisesRegex(ValueError, "WHEEL_FILE_ALLOWLIST"):
                builder.archive_contents(path, "0.2.0.dev0")

    def test_changed_source_content_is_refused(self):
        source = {"runtime/task_swarm/protocol.py": b"original\n"}
        with self.assertRaisesRegex(ValueError, "ARCHIVE_SOURCE_MISMATCH"):
            builder.verify_source_contents({"kotodama_core/task_swarm/protocol.py": b"different\n"}, source, "0.2.0.dev0", wheel=True)


if __name__ == "__main__":
    unittest.main()
