"""Reject overstated coverage and inventory drift in the public review packet."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import validate_cloudflare_upstream_review as review


class CloudflareUpstreamReviewTests(unittest.TestCase):
    def setUp(self):
        self.packet = review.load_packet()

    def test_current_packet_retains_partial_reads_and_no_adoption(self):
        result = review.validate_packet(self.packet)
        self.assertEqual(result, {"files": 99, "declared_complete_diff_reads": 79, "declared_partial_diff_reads": 20})
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(review.main([]), 0)
        result = json.loads(output.getvalue())
        for key in ("git_inventory_verified", "semantic_read_verified", "reviewer_identity_verified", "independent_approval_verified", "runtime_verified", "pin_changed"):
            self.assertIs(result[key], False)
        self.assertEqual(result["public_beta"], "NO_GO_UNPUBLISHED")

    def test_partial_read_cannot_silently_become_complete(self):
        row = next(row for row in self.packet["files"] if not row["read_complete"])
        row["read_complete"] = True
        with self.assertRaises(review.ReviewViolation):
            review.validate_packet(self.packet)

    def test_inventory_and_gate_mutations_are_refused(self):
        mutations = {
            "duplicate path": lambda p: p["files"][1].update(path=p["files"][0]["path"]),
            "traversal": lambda p: p["files"][0].update(path="../outside"),
            "line total": lambda p: p["files"][0].update(added_lines=p["files"][0]["added_lines"] + 1),
            "new endpoint": lambda p: p["summary"]["source"].update(commit="1" * 40),
            "invented approval": lambda p: p["summary"].update(no_independence_acceptance=False),
            "provider effects": lambda p: p["summary"]["effects"].update(provider_mutation=1),
            "invented test": lambda p: p["summary"].update(tests_executed=["passed"]),
            "removed gap": lambda p: p["summary"]["coverage_gaps"].pop(),
            "boolean count": lambda p: p["summary"].update(actual_read_count=True),
            "wrong add blob": lambda p: p["files"][0].update(old_blob="1" * 40),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(self.packet)
                mutate(candidate)
                with self.assertRaises(review.ReviewViolation):
                    review.validate_packet(candidate)

    def test_git_comparison_refuses_blob_and_per_path_count_drift(self):
        rows = self.packet["files"]
        raw = "\n".join(f':100644 100644 {r["old_blob"]} {r["new_blob"]} {r["change_type"]}\t{r["path"]}' for r in rows)
        counts = "\n".join(f'{r["added_lines"]}\t{r["deleted_lines"]}\t{r["path"]}' for r in rows)

        def observe(repo, *args):
            if args[0] == "rev-parse":
                key = "baseline" if args[1].startswith(review.BASE) else "source"
                return self.packet["summary"][key]["tree"]
            return raw if "--raw" in args else counts

        with patch.object(review, "git", side_effect=observe):
            review.verify_inventory(Path("unused"), self.packet)
            for field, value in (("new_blob", "1" * 40), ("added_lines", rows[0]["added_lines"] + 1)):
                with self.subTest(field=field):
                    candidate = copy.deepcopy(self.packet)
                    candidate["files"][0][field] = value
                    with self.assertRaises(review.ReviewViolation):
                        review.verify_inventory(Path("unused"), candidate)

    def test_parser_rejects_duplicate_keys_and_missing_input_without_path_leak(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text('{"status":1,"status":2}', encoding="utf-8")
            with self.assertRaises(review.ReviewViolation):
                review.load_packet(path)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(review.main(["--packet", str(Path(temporary) / "missing.json")]), 1)
            self.assertNotIn(temporary, output.getvalue())


if __name__ == "__main__":
    unittest.main()
