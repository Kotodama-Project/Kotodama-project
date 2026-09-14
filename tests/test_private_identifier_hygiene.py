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
PRIVATE_PATTERNS = (
    ("container or VM identifier", re.compile(r"\b(?:CT|VM)\d{3}\b")),
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
    "tests/test_repository_publication_hygiene.py",
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
        samples = {
            "container or VM identifier": "deployed on CT200 and VM214",
            "private pool name": "pool local-zfs-raid01 mounted",
            "private Windows profile path": "C:\\Users\\someone\\repo",
            "tailnet host": "https://host.tail0abc.ts.net:10000/",
        }
        for label, pattern in PRIVATE_PATTERNS:
            with self.subTest(label=label):
                self.assertIsNotNone(pattern.search(samples[label]))


if __name__ == "__main__":
    unittest.main()
