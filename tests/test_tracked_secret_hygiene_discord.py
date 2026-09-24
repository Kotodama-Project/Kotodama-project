"""The tracked credential gate covers the Discord template's own credential shapes."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "tools/check_tracked_secret_hygiene.py"
SPEC = importlib.util.spec_from_file_location("tracked_secret_hygiene_discord", SCANNER_PATH)
assert SPEC is not None and SPEC.loader is not None
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)

# Synthetic value with the three dot-separated Discord bot token segments. It is
# not a real credential; the middle and last segments are filler.
SYNTHETIC_DISCORD_TOKEN = "M" + "Tk2MjA0MTMxNDgyMDAwMDAw" + "." + "GaBcDe" + "." + "z" * 30
TEMPLATE_NAMES = ("DISCORD_BOT_TOKEN", "KOTODAMA_BRIDGE_TOKEN", "KOTODAMA_LOCAL_ASR_KEY")


class DiscordTemplateCredentialShapesTests(unittest.TestCase):
    def test_discord_bot_token_shape_is_detected_without_an_assignment(self) -> None:
        text = "paste " + SYNTHETIC_DISCORD_TOKEN + " here\n"
        findings = SCANNER.scan_text(Path("setup-notes.md"), text)
        self.assertTrue(findings)
        self.assertIn("Discord bot token", " ".join(str(item) for item in findings))

    def test_template_environment_names_are_treated_as_credentials(self) -> None:
        # DISCORD_BOT_TOKEN values are always the three-segment shape caught by the
        # token pattern; the two bridge names carry arbitrary values, so their
        # assignments are checked by name.
        for name in TEMPLATE_NAMES[1:]:
            with self.subTest(name=name):
                text = name + "=" + "a1b2c3d4e5f6" * 4 + "\n"
                self.assertTrue(SCANNER.scan_text(Path("setup-notes.md"), text))

    def test_placeholders_and_example_file_stay_clean(self) -> None:
        for name in TEMPLATE_NAMES:
            with self.subTest(name=name):
                self.assertEqual([], SCANNER.scan_text(Path(".env.example"), name + "=${" + name + "}\n"))
                self.assertEqual([], SCANNER.scan_text(Path(".env.example"), name + "=\n"))


if __name__ == "__main__":
    unittest.main()
