from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTopologyNavigationTests(unittest.TestCase):
    def test_readme_links_the_repository_topology(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "[Repository Topology](docs/REPOSITORY-TOPOLOGY.md)",
            readme,
        )

    def test_topology_separates_three_layers_and_authority(self) -> None:
        topology = (ROOT / "docs" / "REPOSITORY-TOPOLOGY.md").read_text(
            encoding="utf-8"
        )
        for marker in (
            "Public Core",
            "Private Control Plane",
            "Local Operational Workspace",
            "requires the private control plane to consume an admitted public core",
            "does not claim that this cutover is complete",
            "public core never imports private implementation or data",
            "Governed Review",
            "PUBLIC_EXTRACT / clean history",
            "PRIVATE_RETAIN",
            "REGENERATE",
            "DROP",
            "separate from the repository lifecycle classifications",
            "NO_GO_UNPUBLISHED",
            "Promotion",
            "Current Truth",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, topology)

    def test_topology_does_not_publish_machine_local_paths(self) -> None:
        topology = (ROOT / "docs" / "REPOSITORY-TOPOLOGY.md").read_text(
            encoding="utf-8"
        )
        for prohibited in ("C:\\Users\\", "RamboPC", "DevHub\\10_active"):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, topology)


if __name__ == "__main__":
    unittest.main()
