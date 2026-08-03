from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_status_and_roadmap_name_r50_navigation_surface() -> None:
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    status_flat = " ".join(status.split())
    roadmap_flat = " ".join(roadmap.split())

    assert "R50 is the current public Template/Company/Blocks/Records/MOCs/starter" in status_flat
    assert "R48 is the current public template/documentation surface" not in status_flat
    assert "R50 added the eight-entry-point navigation synchronization" in status_flat
    assert "Review Request, Review Response, and Decision Handoff" in status_flat
    assert "Public Beta access" in status_flat
    assert "Not open" in status_flat
    assert "Final Human GO" in status_flat
    assert "Not completed" in status_flat

    assert "R50 synchronizes this roadmap with the current public Company Pack surface" in roadmap_flat
    assert "R49 synchronizes this roadmap with the R48 public Company Pack surface" not in roadmap_flat
    assert "[x] Template/Company/Blocks/Records/MOCs/starter navigation synchronization" in roadmap_flat
    assert "read-only/candidate-only" in roadmap_flat
    assert "Public Beta GO" in roadmap_flat
    assert "[ ] Candidate-bound Final Human GO" in roadmap_flat
