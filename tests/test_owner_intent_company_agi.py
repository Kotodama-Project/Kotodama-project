from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "docs" / "OWNER-INTENT-COMPANY-AGI.md"
README = ROOT / "README.md"
STATUS = ROOT / "STATUS.md"
ROADMAP = ROOT / "ROADMAP.md"
CANONICAL_LINK = "docs/OWNER-INTENT-COMPANY-AGI.md"


class OwnerIntentCompanyAgiTests(unittest.TestCase):
    def test_owner_direction_has_one_canonical_source_and_near_top_projection(self) -> None:
        canonical = CANONICAL.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")

        for marker in (
            "Owner-confirmed",
            "Company AGI",
            "## Target",
            "## Current reality",
            "## Open design decisions",
            "## Authority and non-effects",
            "BecomeOne",
            "Kotodama",
            "bounded autonomous operation",
            "Voice Requirements Agent",
            "Execution Agent",
            "every other guild or channel remains",
            "candidate never promotes itself",
            "Agent Definition / Card",
            "ambient authority",
            "causal ledger",
            "metered LLM API",
            "Codex App Server",
            "ChatGPT OAuth / subscription",
            "identity-bound subscription access",
            "General local LLM",
            "deferred",
            "ASR / VAD",
            "tiny specialist classifiers / rankers",
            "personal seat",
            "multi-tenant capacity",
            "rate-limit state",
            "Anthropic",
            "GPT-5.6 Luna",
            "GPT-5.6 Sol",
            "Terra",
            "runtime model / effort / provenance",
            "Luna Skills",
            "GPT-5.6 Luna ONLY",
            "Sol is outside the swarm",
            "swarm stops",
            "no automatic fallback",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="canonical", marker=marker):
                self.assertIn(marker, canonical)

        start = readme.index("## Company AGI / Owner-confirmed direction")
        system_map = readme.index("## Company OS system map")
        self.assertLess(start, system_map)
        projection = readme[start:system_map]
        for marker in (
            f"]({CANONICAL_LINK})",
            "README は Projection",
            "### Target",
            "### Current reality",
            "### Open design decisions",
            "Voice Requirements Agent",
            "Execution Agent",
            "それ以外のguild / channelのcapture",
            "Agent Definition / Card",
            "Capability Grant",
            "Knowledge Scope",
            "Evidence Sink",
            "Codex App Server",
            "identity-bound subscription",
            "General local LLM",
            "ASR / VAD",
            "seat / model / rate-limit",
            "GPT-5.6 Luna",
            "GPT-5.6 Sol",
            "runtime model / effort / provenance",
            "Luna-only Swarm",
            "Sol is outside the Swarm",
            "stop without fallback",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="readme", marker=marker):
                self.assertIn(marker, projection)

        self.assertIn(
            "Human DecisionやCurrent Truthへ自己昇格せず",
            " ".join(projection.split()),
        )

        target = projection.split("### Target", 1)[1].split("### Current reality", 1)[0]
        target_bullets = [line for line in target.splitlines() if line.startswith("- ")]
        self.assertGreaterEqual(len(target_bullets), 5)
        self.assertLessEqual(len(target_bullets), 8)

        flow = " ".join(projection.split())
        expected_order = (
            "Conversation / Voice",
            "Source Evidence",
            "Requirement State",
            "Plan Candidate",
            "Agent Swarm",
            "Verification Receipt",
            "Promotion",
            "reply / learning",
        )
        positions = [flow.index(marker) for marker in expected_order]
        self.assertEqual(positions, sorted(positions))

    def test_voice_requirements_agent_is_human_gated_and_current_runtime_is_not_overclaimed(self) -> None:
        readme = README.read_text(encoding="utf-8")
        experience = readme[
            readme.index("## 理想のユーザー体験") : readme.index("## Voice —", readme.index("## 理想のユーザー体験"))
        ]
        for marker in (
            "Voice Requirements Agent",
            "一度に一問",
            "回答",
            "訂正",
            "保留",
            "unknown",
            "Requirement State",
            "Plan Candidate",
            "Execution Agent",
            "自己承認",
            "自己実行",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, experience)

        projection = readme[
            readme.index("## Company AGI / Owner-confirmed direction") : readme.index("## Company OS system map")
        ]
        for marker in (
            "CT200",
            "未結線",
            "desktop Voice bridge",
            "recording / rotation / transcription / Intent",
            "provider E2E",
            "Public Beta",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, projection)

    def test_status_and_roadmap_point_to_the_same_direction_without_promoting_runtime(self) -> None:
        self.assertIn("Updated: 2026-08-26", STATUS.read_text(encoding="utf-8"))
        for name, path in (("status", STATUS), ("roadmap", ROADMAP)):
            text = path.read_text(encoding="utf-8")
            for marker in (
                CANONICAL_LINK,
                "Company AGI",
                "Owner-confirmed",
                "Voice Requirements Agent",
                "runtime remains unimplemented",
                "NO_GO_UNPUBLISHED",
            ):
                with self.subTest(surface=name, marker=marker):
                    self.assertIn(marker, text)

    def test_public_direction_surfaces_reject_private_or_authority_overclaims(self) -> None:
        private_patterns = (
            re.compile(r"[A-Za-z]:\\"),
            re.compile(r"/home/"),
            re.compile(r"\b\d{17,20}\b"),
            re.compile(r"(?i)source_thread_id"),
            re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]"),
        )
        for path in (CANONICAL, README, STATUS, ROADMAP):
            text = path.read_text(encoding="utf-8")
            for pattern in private_patterns:
                with self.subTest(path=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

        canonical = CANONICAL.read_text(encoding="utf-8")
        for marker in (
            "does not authorize runtime execution",
            "does not create a Capability Grant",
            "does not change Current Truth",
            "does not grant Final Human GO",
            "Credentials are never pooled or shared",
            "personal seat is not unlimited multi-tenant capacity",
        ):
            self.assertIn(marker, canonical)


if __name__ == "__main__":
    unittest.main()
