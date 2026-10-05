"""Public files must not carry private infrastructure identifiers.

The contributing policy forbids private host names, container or VM numbers,
private absolute paths, and private pool names in any public artifact. This
scan covers every tracked text file rather than a single status document.
"""

import re
import subprocess
import unittest
from pathlib import Path


import os
import tempfile
from tests.test_repository_publication_hygiene import SECRET_SCANNER

ROOT = Path(__file__).resolve().parents[1]
# Python's `\b` counts Japanese characters as word characters, so an identifier
# written directly next to Japanese text has no word boundary. Explicit ASCII
# lookarounds catch it there as well as in English prose.
CONTAINER_OR_VM = re.compile(r"(?<![A-Za-z0-9])(?:CT|VM)\d{3}(?![A-Za-z0-9])")
PRIVATE_PATTERNS = (
    ("container or VM identifier", CONTAINER_OR_VM),
    ("private pool name", re.compile(r"\blocal-zfs-")),
    ("private Windows profile path", re.compile(r"[A-Za-z]:\\Users\\(?!alice\b|bob\b)")),
    ("tailnet host", re.compile(r"\b[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net\b")),
)
# Runtime marker consumed by a private retention process; renaming it needs a
# coordinated change on the consumer side, so it is tolerated here on purpose.
TOLERATED = (".ct202-local-grant-",)
EXCLUDED = {
    "tests/test_private_identifier_hygiene.py",
    "tests/test_owner_intent_company_agi.py",
}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".tgz", ".zip", ".ico"}


def tracked_text_files(root: Path = ROOT):
    """Yield decoded tracked HEAD/index/worktree snapshots with source labels."""
    index = SECRET_SCANNER.index_blobs(root)
    head = SECRET_SCANNER.head_blobs(root)
    oids = set(index.values()) | set(head.values())
    sizes = SECRET_SCANNER.blob_sizes(root, oids)
    contents = SECRET_SCANNER.read_blobs(root, {oid for oid in oids if sizes[oid] <= SECRET_SCANNER.MAX_TEXT_BYTES})
    for relative in sorted(set(index) | set(head)):
        name = relative.as_posix()
        if name in EXCLUDED:
            continue
        snapshots = {}
        for source, oid in (("HEAD", head.get(relative)), ("index", index.get(relative))):
            if oid is not None and oid in contents:
                snapshots.setdefault(contents[oid], set()).add(source)
        path = root / relative
        if path.is_symlink():
            snapshots.setdefault(path.readlink().as_posix().encode(), set()).add("working tree")
        elif path.is_file() and path.stat().st_size <= SECRET_SCANNER.MAX_TEXT_BYTES:
            snapshots.setdefault(path.read_bytes(), set()).add("working tree")
        for data, sources in snapshots.items():
            text, _decode_error = SECRET_SCANNER.decode_text_snapshot(relative, data)
            if text is not None:
                yield name, SECRET_SCANNER.source_label(sources), text


class PrivateIdentifierHygieneTests(unittest.TestCase):
    def test_tracked_text_omits_private_infrastructure_identifiers(self) -> None:
        def find_identifiers(snapshots):
            offenders = []
            for name, source, text in snapshots:
                for marker in TOLERATED:
                    text = text.replace(marker, "")
                for label, pattern in PRIVATE_PATTERNS:
                    for match in pattern.finditer(text):
                        line = text.count("\n", 0, match.start()) + 1
                        # Only path, line, detector and source; never reflect the match.
                        offenders.append(f"{name}:{line}: {label} [{source}]")
            return offenders

        self.assertEqual(find_identifiers(tracked_text_files()), [])
        # Real owned Git snapshots and BOMs exercise the same decoding boundary.
        value = "CT" + "123"
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        with tempfile.TemporaryDirectory() as temporary:
            owned = Path(temporary)
            def git(*arguments):
                subprocess.run(["git", *arguments], cwd=owned, env=environment,
                               capture_output=True, check=True, timeout=10)
            git("init", "--quiet", "--template=")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            git("config", "commit.gpgsign", "false")
            path = owned / "identifier.txt"
            path.write_text(value, encoding="utf-16")
            git("add", ".")
            git("commit", "--quiet", "-m", "owned HEAD fixture")
            path.write_text(value + " index", encoding="utf-32")
            git("add", ".")
            path.write_text(value + " working", encoding="utf-8")
            offenders = find_identifiers(tracked_text_files(owned))
        self.assertEqual(set(offenders), {f"identifier.txt:1: container or VM identifier [{source}]"
                                         for source in ("HEAD", "index", "working tree")})
        self.assertNotIn(value, "\n".join(offenders))

    def test_patterns_detect_the_identifier_shapes_they_guard(self) -> None:
        # Synthetic values only; each has the shape the pattern guards.
        samples = {
            "container or VM identifier": "deployed on CT123 and VM456",
            "private pool name": "pool local-zfs-example mounted",
            "private Windows profile path": "C:\\Users\\someone\\repo",
            "tailnet host": "https://host.tail0abc.ts.net:10000/",
        }
        for label, pattern in PRIVATE_PATTERNS:
            with self.subTest(label=label):
                self.assertIsNotNone(pattern.search(samples[label]))

    def test_identifier_next_to_japanese_text_is_detected(self) -> None:
        for sample in ("送信先はCT123に限る", "hostがVM456の設定を読む", "(CT123)"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(CONTAINER_OR_VM.search(sample))
        # Mixed-case base64 in lockfiles must not trip the scan.
        for sample in ("ACT123", "CT1234", "CT123abc", "vm456", ".ct123-local-grant-"):
            with self.subTest(sample=sample):
                self.assertIsNone(CONTAINER_OR_VM.search(sample))


if __name__ == "__main__":
    unittest.main()
