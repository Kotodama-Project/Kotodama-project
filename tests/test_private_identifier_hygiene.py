"""Public files must not carry private infrastructure identifiers.

The contributing policy forbids private host names, container or VM numbers,
private absolute paths, and private pool names in any public artifact. This
scan covers every tracked text file rather than a single status document.
"""

import re
import subprocess
import unittest
from pathlib import Path


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


def tracked_text_files():
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=60
    )
    for raw in completed.stdout.split(b"\0"):
        name = raw.decode("utf-8", errors="replace")
        if not name or name in EXCLUDED:
            continue
        path = ROOT / name
        if not path.is_file() or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield name, text


class PrivateIdentifierHygieneTests(unittest.TestCase):
    def test_tracked_text_omits_private_infrastructure_identifiers(self) -> None:
        offenders = []
        for name, text in tracked_text_files():
            for marker in TOLERATED:
                text = text.replace(marker, "")
            for label, pattern in PRIVATE_PATTERNS:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{name}:{line}: {label} {match.group(0)!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

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
