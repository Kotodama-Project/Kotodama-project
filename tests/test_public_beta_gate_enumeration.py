import re
import unittest
from pathlib import Path


from tests.document_contract_helpers import section, assert_links, shell_commands, assert_command_order, table_rows, assert_preview_boundary, headings, link_targets

ROOT = Path(__file__).resolve().parents[1]
OVERVIEW = ROOT / "docs" / "OVERVIEW.md"
ROADMAP = ROOT / "ROADMAP.md"

GATE_SECTION = "### Public Beta 完成としてまだ証明されていないもの"
GATE_LINE = re.compile(r"^- `(PB-G\d+)` \[(unproven|completed)\] (.+)$")
GATE_TOKEN = re.compile(r"`(PB-G\d+)`")
# OVERVIEW owns this stable full registry: completed gates retain their IDs/rows.
# A registry change needs an explicit contract update, not an observed-list length.
EXPECTED_GATE_IDS = tuple(f"PB-G{number}" for number in range(1, 11))
DECLARED_COUNT = re.compile(r"未証明の gate はちょうど \*\*(\d+) 件\*\* です")
UNCHECKED_ROADMAP_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)


class PublicBetaGateEnumerationTests(unittest.TestCase):
    """Keep the public gate list countable and cross-referenced.

    The same set of unproven gates is restated in more than one place. Without a
    stable identifier per gate, a projection can quietly drop or merge one and
    the totals stop agreeing, which is exactly the failure mode this repository
    tells readers to distrust.
    """

    def setUp(self) -> None:
        self.overview = OVERVIEW.read_text(encoding="utf-8")
        self.roadmap = ROADMAP.read_text(encoding="utf-8")

    def gate_lines(self) -> list[tuple[str, str, str]]:
        surface = section(self.overview, "public-beta-完成としてまだ証明されていないもの")
        return [match.groups() for line in surface.splitlines() if (match := GATE_LINE.fullmatch(line))]

    def test_gate_identifiers_are_unique_and_sequential(self) -> None:
        gates = self.gate_lines()
        self.assertTrue(gates)
        identifiers = [identifier for identifier, _, _ in gates]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(
            tuple(identifiers), EXPECTED_GATE_IDS,
            "the stable PB-G1..PB-G10 full registry must retain every gate",
        )
        for identifier, status, description in gates:
            with self.subTest(identifier=identifier):
                self.assertIn(status, {"unproven", "completed"})
                self.assertTrue(description.strip())

    def test_declared_count_matches_the_listed_gates(self) -> None:
        surface = section(self.overview, "public-beta-完成としてまだ証明されていないもの")
        declared = DECLARED_COUNT.search(surface)
        self.assertIsNotNone(declared, "authoritative gate section must state its unproven count")
        gates = self.gate_lines()
        self.assertTrue(gates)
        unproven = sum(status == "unproven" for _, status, _ in gates)
        self.assertEqual(int(declared.group(1)), unproven)

    def test_every_unchecked_roadmap_item_cites_a_known_gate(self) -> None:
        known = {identifier for identifier, _, _ in self.gate_lines()}
        items = UNCHECKED_ROADMAP_ITEM.findall(self.roadmap)
        self.assertTrue(items, "ROADMAP must still list unchecked gates")
        for item in items:
            with self.subTest(item=item[:60]):
                cited = set(GATE_TOKEN.findall(item))
                self.assertTrue(cited, "unchecked ROADMAP item cites no gate")
                self.assertTrue(cited.issubset(known), f"unknown gate cited: {cited - known}")

    def test_every_gate_is_cited_by_at_least_one_roadmap_item(self) -> None:
        known = {
            identifier
            for identifier, status, _ in self.gate_lines()
            if status == "unproven"
        }
        cited: set[str] = set()
        for item in UNCHECKED_ROADMAP_ITEM.findall(self.roadmap):
            cited.update(GATE_TOKEN.findall(item))
        self.assertEqual(set(), known - cited, "gate with no ROADMAP path to closing it")

    def test_gate_list_keeps_the_public_boundary_explicit(self) -> None:
        section = self.overview.split(GATE_SECTION, 1)[1].split("\n## ", 1)[0]
        self.assertIn("NO_GO_UNPUBLISHED", section)
        self.assertIn("tests/test_public_beta_gate_enumeration.py", section)


if __name__ == "__main__":
    unittest.main()
