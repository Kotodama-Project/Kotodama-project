from __future__ import annotations

import copy
import importlib.util
import unittest


from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_cloudflare_os_candidate.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_os_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
ADAPTER = MODULE.load_adapter()


class CloudflareOsCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = MODULE.load_json(MODULE.MANIFEST)
        cls.schema = MODULE.load_json(MODULE.SCHEMA)

    def mutate(self) -> dict:
        return copy.deepcopy(self.manifest)

    def test_current_candidate_passes(self) -> None:
        errors, result = MODULE.validate()
        self.assertEqual([], errors)
        self.assertEqual(6, result["cases"])

    def test_unknown_manifest_field_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["unexpected"] = True
        with self.assertRaisesRegex(MODULE.CandidateViolation, "schema validation failed"):
            MODULE.validate_schema(candidate, self.schema)

    def test_public_beta_cannot_be_promoted(self) -> None:
        candidate = self.mutate()
        candidate["public_beta"] = "GO"
        with self.assertRaisesRegex(MODULE.CandidateViolation, "NO_GO_UNPUBLISHED"):
            MODULE.validate_manifest(candidate)

    def test_source_only_effect_cannot_be_added(self) -> None:
        candidate = self.mutate()
        candidate["effects"]["deployment"] = 1
        with self.assertRaisesRegex(MODULE.CandidateViolation, "effects"):
            MODULE.validate_manifest(candidate)

    def test_starter_gitlink_cannot_be_replaced_by_current_core(self) -> None:
        candidate = self.mutate()
        candidate["starter_core_gitlink"]["commit"] = MODULE.CORE_COMMIT
        with self.assertRaises(MODULE.CandidateViolation):
            MODULE.validate_manifest(candidate)

    def test_raw_source_must_be_revision_bound(self) -> None:
        candidate = self.mutate()
        candidate["official_sources"][-1] = (
            "https://raw.githubusercontent.com/cloudflare/cloudflare-os-starter/main/docs/observability.md"
        )
        with self.assertRaisesRegex(MODULE.CandidateViolation, "revision-bound"):
            MODULE.validate_manifest(candidate)

    def test_observation_is_source_candidate_only(self) -> None:
        projection = ADAPTER.project_event(
            MODULE.make_event("observation"),
            expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT,
        )
        self.assertTrue(projection["source_evidence_candidate"])
        self.assertFalse(projection["execution_authorized"])

    def test_protected_observation_requires_context_admission(self) -> None:
        event = MODULE.make_event("observation", protected=True)
        event["context_admission_sha256"] = None
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "missing_context"):
            ADAPTER.project_event(event, expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT)

    def test_private_body_is_rejected(self) -> None:
        event = MODULE.make_event("observation")
        event["private_body_included"] = True
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "private_body"):
            ADAPTER.project_event(event, expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT)

    def test_simulation_cannot_claim_an_applied_effect(self) -> None:
        event = MODULE.make_event("action_simulated")
        event["effect_state"] = "applied"
        event["effect_count"] = 1
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "invalid_simulated"):
            ADAPTER.project_event(event, expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT)

    def test_applied_action_requires_authority_and_receipt_bindings(self) -> None:
        for field in (
            "work_order_sha256",
            "capability_grant_sha256",
            "human_decision_sha256",
            "external_action_receipt_sha256",
        ):
            with self.subTest(field=field):
                event = MODULE.make_event("action_applied")
                event[field] = None
                with self.assertRaises(ADAPTER.GatekeeperAdapterViolation):
                    ADAPTER.project_event(event, expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT)

    def test_revision_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "revision_mismatch"):
            ADAPTER.project_event(
                MODULE.make_event("observation"),
                expected_gatekeeper_revision=MODULE.CORE_COMMIT,
            )

    def test_unknown_event_field_is_rejected(self) -> None:
        event = MODULE.make_event("observation")
        event["body"] = "forbidden"
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "invalid_event_shape"):
            ADAPTER.project_event(event, expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT)

    def test_projection_cannot_self_authorize_or_promote(self) -> None:
        projection = ADAPTER.project_event(
            MODULE.make_event("action_applied"),
            expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT,
        )
        for field in ("execution_authorized", "promotion_authorized", "current_truth_changed"):
            with self.subTest(field=field):
                changed = copy.deepcopy(projection)
                changed[field] = True
                with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "unsafe_projection"):
                    ADAPTER.validate_projection(changed)

    def test_direct_applied_projection_requires_authority_bindings(self) -> None:
        projection = ADAPTER.project_event(
            MODULE.make_event("action_applied"),
            expected_gatekeeper_revision=MODULE.PINNED_CORE_COMMIT,
        )
        projection["work_order_sha256"] = None
        with self.assertRaisesRegex(ADAPTER.GatekeeperAdapterViolation, "missing_work_order"):
            ADAPTER.validate_projection(projection)

    def test_projection_digest_is_deterministic(self) -> None:
        first = MODULE.validate_adapter(ADAPTER)
        second = MODULE.validate_adapter(ADAPTER)
        self.assertEqual(first["projection_set_sha256"], second["projection_set_sha256"])


if __name__ == "__main__":
    unittest.main()
