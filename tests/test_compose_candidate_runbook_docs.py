from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESOLVED = ROOT / "docs" / "RESOLVED-COMPOSE-CANDIDATE.md"
IMAGE_PREFLIGHT = ROOT / "docs" / "IMAGE-AVAILABILITY-PREFLIGHT.md"


def assert_ordered(test_case: unittest.TestCase, document: str, *markers: str) -> None:
    positions = []
    for marker in markers:
        positions.append(document.index(marker))
    test_case.assertEqual(positions, sorted(positions), markers)


class ComposeCandidateRunbookDocumentationTests(unittest.TestCase):
    def test_resolved_candidate_has_posix_environment_and_command_parity(self) -> None:
        document = RESOLVED.read_text(encoding="utf-8")

        for marker in (
            "```powershell",
            "$env:KOTODAMA_POSTGRES_IMAGE = '<registry>/<repository>@sha256:<64-hex-digest>'",
            "$env:KOTODAMA_COMPANY_DB_PASSWORD = '<private-distinct-value>'",
            "$env:KOTODAMA_EVIDENCE_DB_PASSWORD = '<private-distinct-value>'",
            "```sh",
            "export KOTODAMA_POSTGRES_IMAGE='<registry>/<repository>@sha256:<64-hex-digest>'",
            "export KOTODAMA_COMPANY_DB_PASSWORD='<private-distinct-value>'",
            "export KOTODAMA_EVIDENCE_DB_PASSWORD='<private-distinct-value>'",
            "New-Item -ItemType Directory -Force work | Out-Null",
            "mkdir -p work",
            "python tools\\resolve_compose_candidate.py kotodama-local-r1 --output work\\resolved-compose-candidate.json",
            "python3 tools/resolve_compose_candidate.py kotodama-local-r1 --output work/resolved-compose-candidate.json",
            "python tools\\validate_resolved_compose_candidate.py work\\resolved-compose-candidate.json",
            "python3 tools/validate_resolved_compose_candidate.py work/resolved-compose-candidate.json",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, document)

        assert_ordered(
            self,
            document,
            "New-Item -ItemType Directory -Force work | Out-Null",
            "python tools\\resolve_compose_candidate.py kotodama-local-r1 --output work\\resolved-compose-candidate.json",
            "mkdir -p work",
            "python3 tools/resolve_compose_candidate.py kotodama-local-r1 --output work/resolved-compose-candidate.json",
            "python tools\\validate_resolved_compose_candidate.py work\\resolved-compose-candidate.json",
            "python3 tools/validate_resolved_compose_candidate.py work/resolved-compose-candidate.json",
        )
        for marker in ("local", "read-only", "credential", "NO_GO_UNPUBLISHED"):
            with self.subTest(boundary=marker):
                self.assertIn(marker, document)

    def test_image_preflight_has_posix_command_parity_in_order(self) -> None:
        document = IMAGE_PREFLIGHT.read_text(encoding="utf-8")

        command_pairs = (
            (
                "python tools\\resolve_compose_candidate.py kotodama-local-r1 --output work\\resolved-compose-candidate.json",
                "python3 tools/resolve_compose_candidate.py kotodama-local-r1 --output work/resolved-compose-candidate.json",
            ),
            (
                "python tools\\preflight_compose_image_availability.py work\\resolved-compose-candidate.json --output work\\compose-image-availability.json",
                "python3 tools/preflight_compose_image_availability.py work/resolved-compose-candidate.json --output work/compose-image-availability.json",
            ),
            (
                "python tools\\verify_compose_image_availability_preflight.py work\\compose-image-availability.json work\\resolved-compose-candidate.json",
                "python3 tools/verify_compose_image_availability_preflight.py work/compose-image-availability.json work/resolved-compose-candidate.json",
            ),
        )
        for powershell_command, posix_command in command_pairs:
            with self.subTest(powershell_command=powershell_command):
                self.assertIn(powershell_command, document)
                self.assertIn(posix_command, document)

        assert_ordered(
            self,
            document,
            "python tools\\resolve_compose_candidate.py kotodama-local-r1 --output work\\resolved-compose-candidate.json",
            "python3 tools/resolve_compose_candidate.py kotodama-local-r1 --output work/resolved-compose-candidate.json",
            "python tools\\preflight_compose_image_availability.py work\\resolved-compose-candidate.json --output work\\compose-image-availability.json",
            "python3 tools/preflight_compose_image_availability.py work/resolved-compose-candidate.json --output work/compose-image-availability.json",
            "python tools\\verify_compose_image_availability_preflight.py work\\compose-image-availability.json work\\resolved-compose-candidate.json",
            "python3 tools/verify_compose_image_availability_preflight.py work/compose-image-availability.json work/resolved-compose-candidate.json",
        )
        for marker in ("read-only", "pull", "start", "NO_GO_UNPUBLISHED", "POSIX shell"):
            with self.subTest(boundary=marker):
                self.assertIn(marker, document)

    def test_runbooks_do_not_publish_real_private_values(self) -> None:
        resolved = RESOLVED.read_text(encoding="utf-8")
        self.assertIn("<private-distinct-value>", resolved)
        for path in (RESOLVED, IMAGE_PREFLIGHT):
            document = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("synthetic-company-r13-secret", document)
                self.assertNotIn("synthetic-evidence-r13-secret", document)


if __name__ == "__main__":
    unittest.main()
