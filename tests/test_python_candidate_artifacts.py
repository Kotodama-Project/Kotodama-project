"""Archive boundary and repeatability, independent of installed build tooling."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import build_python_candidate as builder


class PythonCandidateArtifactsTests(unittest.TestCase):
    def test_builder_and_lock_drift_are_refused_against_the_recorded_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "builder.py"
            path.write_bytes(b"committed\n")
            with patch.object(builder, "ROOT", root), patch.object(builder, "git", return_value=b"committed\n"):
                self.assertEqual(builder.pinned_files("a" * 40, {"builder.py"}), {"builder.py": b"committed\n"})
                path.write_bytes(b"changed locally\n")
                with self.assertRaisesRegex(ValueError, "SOURCE_DIFFERS_FROM_COMMIT"):
                    builder.pinned_files("a" * 40, {"builder.py"})

    def test_generated_metadata_lf_and_crlf_produce_same_record_without_source_changes(self):
        source = b"do not rewrite source\r\n"
        linux = {"kotodama_core/a.py": source,
                 "kotodama_core-0.2.0.dev0.dist-info/METADATA": b"Name: kotodama-core\n\nDescription\n",
                 "kotodama_core-0.2.0.dev0.dist-info/RECORD": b"prior record"}
        windows = dict(linux)
        name = "kotodama_core-0.2.0.dev0.dist-info/METADATA"
        windows[name] = linux[name].replace(b"\n", b"\r\n")
        a = builder.normalize_metadata(linux, wheel=True)
        b = builder.normalize_metadata(windows, wheel=True)
        self.assertEqual(a, b)
        self.assertEqual(a["kotodama_core/a.py"], source)
        self.assertEqual(builder.normalize_metadata(a, wheel=True), a)
        tar = {"package/PKG-INFO": b"meta\r\n", "package/setup.cfg": b"cfg\r\n", "package/code.py": source}
        normalized = builder.normalize_metadata(tar, wheel=False)
        self.assertEqual(normalized["package/PKG-INFO"], b"meta\n")
        self.assertEqual(normalized["package/setup.cfg"], b"cfg\n")
        self.assertEqual(normalized["package/code.py"], source)

    def test_metadata_normalization_is_reproducible_and_preserves_contents(self):
        contents = {"candidate/z.txt": b"Japanese: \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e\n", "candidate/a.txt": b"a\n"}
        for wheel in (False, True):
            first = builder.normalize_archive(Path("unused"), contents, 1788307200, wheel=wheel)
            second = builder.normalize_archive(Path("unused"), dict(reversed(list(contents.items()))), 1788307200, wheel=wheel)
            self.assertEqual(first, second)
            self.assertNotEqual(first, builder.normalize_archive(Path("unused"), contents, 1788307210, wheel=wheel))

    def test_unlisted_wheel_files_are_rejected_before_install(self):
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
