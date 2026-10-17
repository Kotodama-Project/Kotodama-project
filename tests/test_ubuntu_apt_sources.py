from pathlib import Path
import tempfile
import unittest

from tools.prepare_ubuntu_apt_sources import normalize, prepare


class UbuntuAptSourcesTests(unittest.TestCase):
    def test_deb822_mirror_indirection_is_resolved_without_changing_signature_policy(self):
        before = "Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\nSuites: noble noble-updates\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
        after = normalize(before)
        self.assertIn("URIs: https://archive.ubuntu.com/ubuntu\n", after)
        self.assertEqual(after.replace("https://archive.ubuntu.com/ubuntu", "mirror+file:/etc/apt/apt-mirrors.txt"), before)
        self.assertEqual(normalize(after), after)

    def test_direct_mirror_and_security_reference_are_exact_tokens(self):
        self.assertEqual(normalize("deb http://azure.archive.ubuntu.com/ubuntu/ noble main\n"), "deb https://archive.ubuntu.com/ubuntu noble main\n")
        self.assertEqual(normalize("URIs: mirror+file:/etc/apt/apt-mirrors-security.txt\n"), "URIs: https://security.ubuntu.com/ubuntu\n")
        for uri in ("http://azure.archive.ubuntu.com/ubuntu-extra", "mirror+file:/etc/apt/apt-mirrors.txt.other", "https://packages.microsoft.com/ubuntu/24.04/prod"):
            self.assertEqual(normalize("URIs: " + uri + "\n"), "URIs: " + uri + "\n")

    def test_apply_reads_back_changed_files_and_retains_unrelated_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory = root / "sources.list.d"; directory.mkdir()
            target = directory / "ubuntu.sources"
            target.write_text("URIs: mirror+file:/etc/apt/apt-mirrors.txt\nSigned-By: /key.gpg\n", encoding="utf-8")
            unrelated = directory / "vendor.list"; unrelated.write_text("deb https://vendor.example.test stable main\n", encoding="utf-8")
            original = target.read_bytes()
            self.assertEqual(prepare(root)["changed_files"], 1)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(prepare(root, apply=True)["changed_files"], 1)
            self.assertIn("https://archive.ubuntu.com/ubuntu", target.read_text(encoding="utf-8"))
            self.assertIn("Signed-By: /key.gpg", target.read_text(encoding="utf-8"))
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "deb https://vendor.example.test stable main\n")
            self.assertEqual(prepare(root, apply=True)["changed_files"], 0)

    def test_invalid_input_is_refused_before_any_planned_file_is_changed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory = root / "sources.list.d"; directory.mkdir()
            valid = directory / "a.sources"; valid.write_text("URIs: mirror+file:/etc/apt/apt-mirrors.txt\n", encoding="utf-8")
            original = valid.read_bytes()
            (directory / "z.sources").write_bytes(b"\xff")
            with self.assertRaises(UnicodeError):
                prepare(root, apply=True)
            self.assertEqual(valid.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
