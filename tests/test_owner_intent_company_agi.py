from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "docs" / "OWNER-INTENT-COMPANY-AGI.md"
README = ROOT / "README.md"
STATUS = ROOT / "STATUS.md"
ROADMAP = ROOT / "ROADMAP.md"
CANONICAL_LINK = "docs/OWNER-INTENT-COMPANY-AGI.md"
GRILLU_ANCHOR = "grillu-adaptive-requirements"


def _markdown_section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text[start + len(heading):]
    next_heading = re.search(r"^## ", following, flags=re.MULTILINE)
    return text[start:] if next_heading is None else text[start:start + len(heading) + next_heading.start()]


class OwnerIntentCompanyAgiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonical = CANONICAL.read_text(encoding="utf-8")
        self.readme = README.read_text(encoding="utf-8")
        self.status = STATUS.read_text(encoding="utf-8")
        self.roadmap = ROADMAP.read_text(encoding="utf-8")
        start = self.readme.index("## Company AGI / Owner-confirmed direction")
        end = self.readme.index("## Company OS system map", start)
        self.projection = self.readme[start:end]

    def test_canonical_product_boundary_and_okf_profile_are_explicit(self) -> None:
        for marker in (
            "Owner-confirmed",
            "Company AGI",
            "## Target",
            "one public Kotodama product",
            "private donor and experimental kernel",
            "consumer/control plane pinned",
            "never a second product SSOT",
            "## Governed knowledge and OKF",
            "Google Cloud Open Knowledge Format (OKF)",
            "OKF v0.2",
            "GoogleCloudPlatform/open-knowledge-format",
            "central human- and agent-readable representation",
            "not the sole Company truth",
            "central authority",
            "transactional state",
            "raw archive",
            "ACL",
            "storage/serving/query",
            "audit ledger",
            "deletion semantics",
            "concurrency semantics",
            "source-of-record role",
            "Owner-reviewed OKF concepts",
            "governed curated interpretation",
            "rebuildable projections",
            "never canonical source",
            "stable logical ID",
            "immutable revision/content digest",
            "parent revision",
            "evidence locators",
            "evidence hashes",
            "authenticated authority/policy/approval receipt",
            "supersession, invalidation, and retention",
            "typed, revision-bound links",
            "compare-and-set (CAS)",
            "Context Pack and attestation binding",
            "erasure/invalidation index",
            "## Current reality",
            "## Open design decisions",
            "## Authority and non-effects",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="canonical", marker=marker):
                self.assertIn(marker, self.canonical)

        for marker in (
            f"]({CANONICAL_LINK})",
            "README は Projection",
            "### Target",
            "### Current reality",
            "### Open design decisions",
            "一つだけ",
            "BecomeOne",
            "OKF v0.2",
            "centralな人間・agent-readable representation",
            "唯一のtruthにはしません",
            "Discord text / Voice",
            "Session auto-creation",
            "adaptive",
            "Luna-first",
            "private v1 backend",
            "Goal Completion",
            "NO_GO_UNPUBLISHED",
        ):
            with self.subTest(surface="readme projection", marker=marker):
                self.assertIn(marker, self.projection)

        target = self.projection.split("### Target", 1)[1].split("### Current reality", 1)[0]
        target_bullets = [line for line in target.splitlines() if line.startswith("- ")]
        self.assertGreaterEqual(len(target_bullets), 6)
        self.assertLessEqual(len(target_bullets), 10)

        flow = " ".join(self.projection.split())
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

    def test_ingress_raw_evidence_and_session_bindings_are_separate(self) -> None:
        for marker in (
            "## Conversation ingress and evidence",
            "Discord text and Voice",
            "Codex",
            "Claude",
            "Notion",
            "GitHub",
            "Google Drive",
            "n8n",
            "exact source/session/channel",
            "speaker or individual track",
            "timestamps and",
            "spans, raw ASR text",
            "raw ASR text",
            "consent/retention revision",
            "a digest",
            "Raw evidence",
            "never overwrite raw evidence",
            "raw PCM + ingress event JSON",
            "per-speaker ASR",
            "optional timestamp/acoustic alignment",
            "immutable speaker-attributed transcript",
            "deterministic/contextual corrected transcript (separate sidecar/diff)",
            "whole-conversation minutes",
            "Source Evidence / Intent events",
            "Raw PCM and ingress event JSON",
            "source provenance",
            "individual speaker track",
            "ASR remains derived and fallible",
            "Phoneme/G2P",
            "dictionary lookup",
            "unknown words from audio",
            "Session auto-creation is allowed",
            "Task SSOT",
            "Plan/Requirement references",
            "Agent Invocation and model provenance",
            "Capability/Knowledge/MCP grants",
            "A2A delegation",
            "dependencies and parallel",
            "status, evidence, and invalidation",
            "evidence, and invalidation",
            "Unknown or ambiguous authority remains",
            "explicit rather than being inferred",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.canonical)

        stages = (
            "raw PCM + ingress event JSON",
            "per-speaker ASR",
            "optional timestamp/acoustic alignment",
            "immutable speaker-attributed transcript",
            "deterministic/contextual corrected transcript (separate sidecar/diff)",
            "whole-conversation minutes",
            "Source Evidence / Intent events",
        )
        stage_positions = [self.canonical.index(stage) for stage in stages]
        self.assertEqual(stage_positions, sorted(stage_positions))

        voice_start = self.readme.index("## Voice —")
        voice_end = self.readme.index("## GrillU —", voice_start)
        voice = self.readme[voice_start:voice_end]
        voice_stages = (
            "raw PCM + ingress event JSON",
            "per-speaker ASR",
            "optional timestamp/acoustic alignment",
            "immutable speaker-attributed transcript",
            "deterministic/contextual corrected transcript (separate sidecar/diff)",
            "whole-conversation minutes",
            "Source Evidence / Intent events",
        )
        voice_positions = [voice.index(stage) for stage in voice_stages]
        self.assertEqual(voice_positions, sorted(voice_positions))
        self.assertIn("individual speaker track は", voice)
        self.assertIn("ASR は derived / fallible", voice)
        self.assertNotIn("audio / ASR を authority", voice)

        for marker in (
            "Discord text / Voice",
            "Codex",
            "Claude",
            "Notion",
            "GitHub",
            "Google Drive",
            "n8n",
            "raw evidence",
            "Session auto-creation",
            "A2A",
        ):
            with self.subTest(surface="readme projection", marker=marker):
                self.assertIn(marker, self.projection)

    def test_grillu_is_adaptive_and_never_authorizes_execution(self) -> None:
        for marker in (
            "Voice Requirements / GrillU is an adaptive, channel-neutral facilitator",
            "Natural continuous Voice conversation can form requirements",
            "uncertainty, impact, or authority needs clarification",
            "rigid UI or a one-question ritual",
            "answers,\ncorrections, holds, and unknowns",
            "does not\nself-approve, self-promote, or gain execution authority",
        ):
            with self.subTest(surface="canonical", marker=marker):
                self.assertIn(marker, self.canonical)

        experience_start = self.readme.index("## 理想のユーザー体験")
        experience_end = self.readme.index("## Voice —", experience_start)
        experience = self.readme[experience_start:experience_end]
        for marker in (
            "continuous Voice",
            "channel-neutral",
            "不確実性・影響・authority",
            "質問数やUIを固定するritualではありません",
            "self-approve",
            "self-promote",
            "self-execute",
        ):
            with self.subTest(surface="readme experience", marker=marker):
                self.assertIn(marker, experience)

        for text in (self.canonical, self.projection, experience):
            self.assertNotIn("一度に一問", text)
            self.assertNotIn("一問だけ", text)
            self.assertNotRegex(text, re.compile(r"(?i)ask(?:s)?\s+one\s+question\s+only"))

    def test_execution_model_archive_delegation_and_improvement_boundaries(self) -> None:
        for marker in (
            "## Bounded execution and agent authority",
            "auto-execute reversible work",
            "self-owned disposable clone",
            "worktree",
            "container",
            "isolated VM",
            "exact base or image",
            "data/network/tool grants",
            "budget, TTL, kill",
            "export/evidence boundary",
            "cleanup receipt",
            "no ambient\nshared, production, public, or credential authority",
            "## Model and local-component policy",
            "Luna-first",
            "overwhelming majority",
            "GPT-5.6 Luna",
            "GPT-5.6 Sol",
            "upper-tier\narchitecture",
            "cross-swarm audit",
            "adversarial synthesis",
            "Terra",
            "routing rationale",
            "exact runtime model",
            "provenance/evidence",
            "bounded stop",
            "General-purpose local LLM operation remains deferred",
            "ASR/VAD",
            "speaker support",
            "tiny deterministic specialists",
            "metered API architecture remains\nexcluded",
            "## Conversation archive boundary",
            "Archive Target interface remains provider-neutral",
            "package manifest and\ndigests",
            "retention period\nand deletion policy remain OPEN",
            "ordinary encrypted file package on a dedicated ZFS",
            "## Standing GitHub delegation",
            "agent-executable revert path",
            "independent review and tests pass",
            "force-push or history erasure",
            "repository deletion",
            "visibility/settings/credential changes",
            "post-merge monitoring",
            "## Unattended Improvement Loop",
            "budget,\ncadence, kill conditions, provenance",
            "automatic Session / Task",
            "disposable experiment",
            "Luna-first build / review",
            "upper-tier Sol audit / integration when warranted",
            "reversible Git merge",
            "auto-revert regression",
            "promote verified learning into OKF / Company SSOT",
            "not unbounded self-modification",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.canonical)

        for marker in (
            "reversible work",
            "exact base/image",
            "Luna-first",
            "GPT-5.6 Sol",
            "Terra",
            "private v1 backend",
            "Standing GitHub delegation",
            "Goal Completion",
            "reversible merge/revert",
            "auto",
            "kill",
            "provenance",
        ):
            with self.subTest(surface="readme projection", marker=marker):
                self.assertIn(marker, self.projection)

        stale_model_words = (
            "GPT-5.6 Luna ONLY",
            "Luna-only Swarm",
            "Sol is outside the swarm",
            "Sol is outside the Swarm",
            "stop without fallback",
            "OKF v0.1",
            "frozen OKF",
        )
        for text_name, text in (
            ("canonical", self.canonical),
            ("readme projection", self.projection),
        ):
            for marker in stale_model_words:
                with self.subTest(surface=text_name, stale=marker):
                    self.assertNotIn(marker, text)

        self.assertIn("owner-selected\nprivate v1 backend is an ordinary encrypted file package on a dedicated ZFS", self.canonical)
        self.assertIn("current inspection found no safe\ndedicated existing target", self.canonical)
        for backend in ("Blob Store", "AWS", "Drive", "MinIO", "NAS"):
            adopted_pattern = re.compile(
                rf"(?i)(?:adopt(?:ed|ion)?|prefer(?:red|ence)?|select(?:ed|ion)?|chosen).{{0,60}}{re.escape(backend)}"
            )
            with self.subTest(backend=backend):
                self.assertIsNone(adopted_pattern.search(self.canonical))

    def test_status_and_roadmap_project_direction_without_promoting_runtime(self) -> None:
        self.assertIn("Updated: 2026-08-26", self.status)
        for name, text in (("status", self.status), ("roadmap", self.roadmap)):
            for marker in (
                CANONICAL_LINK,
                "Company AGI",
                "Owner-confirmed",
                "one Kotodama",
                "Correction themes",
                "OKF v0.2",
                "Luna-first",
                "private ZFS v1 target",
                "bounded Goal Completion",
                "runtime remains unimplemented",
                "NO_GO_UNPUBLISHED",
                "redacted owner-directed",
                "not signed",
                "independently verifiable",
                "rightsholder",
                "Issue #25",
            ):
                with self.subTest(surface=name, marker=marker):
                    self.assertIn(marker, text)

        for name, text, heading in (
            ("status", self.status, "## Owner-confirmed Company AGI direction"),
            ("roadmap", self.roadmap, "## Owner-confirmed Company AGI direction"),
        ):
            projection = _markdown_section(text, heading)
            nonblank_lines = [line for line in projection.splitlines() if line.strip()]
            with self.subTest(surface=name, boundary="compact projection"):
                self.assertLessEqual(len(nonblank_lines), 18)
                self.assertLess(len(projection), len(self.canonical) // 3)
                self.assertNotIn("## Governed knowledge and OKF", projection)
                self.assertNotIn("## Unattended Improvement Loop", projection)

    def test_changed_document_links_and_grillu_anchor_are_resolvable(self) -> None:
        for document in (README, CANONICAL, STATUS, ROADMAP):
            text = document.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                if target.startswith(("https://", "http://", "#")):
                    continue
                local_target = target.split("#", 1)[0]
                if not local_target:
                    continue
                with self.subTest(document=document.name, target=local_target):
                    self.assertTrue((document.parent / local_target).is_file())

        self.assertIn(f"](#{GRILLU_ANCHOR})", self.readme)
        self.assertIn(f'<a id="{GRILLU_ANCHOR}"></a>', self.readme)
        self.assertNotIn("#grillu--一度に一つだけ深掘りする", self.readme)

    def test_public_direction_surfaces_reject_private_or_authority_overclaims(self) -> None:
        private_patterns = (
            re.compile(r"[A-Za-z]:\\"),
            re.compile(r"/home/"),
            re.compile(r"\b\d{17,20}\b"),
            re.compile(r"(?i)source_thread_id"),
            re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]"),
            re.compile(r"(?i)CT\d{2,}"),
        )
        for path in (CANONICAL, README, STATUS, ROADMAP):
            text = path.read_text(encoding="utf-8")
            for pattern in private_patterns:
                with self.subTest(path=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

        for marker in (
            "does not authorize runtime execution",
            "does not create a Capability Grant",
            "does not change Current Truth",
            "does not grant Final Human GO",
            "Credentials are never pooled or shared",
            "personal seat is not unlimited multi-tenant capacity",
            "redacted public candidate",
            "not a signed or independently verifiable governance",
            "Issue #25 remains open",
            "Apache-2.0 candidate bytes",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.canonical)


if __name__ == "__main__":
    unittest.main()
