import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATE_TRANSITION = (
    ROOT
    / "tools"
    / "create_attestation_nonce_store_checkpoint_segment_transition.py"
)
CREATION_SCHEMA = (
    ROOT
    / "schemas"
    / "attestation-nonce-store-checkpoint-segment-transition-creation.schema.json"
)
TRANSITION_NAMESPACE = "kotodama-nonce-store-checkpoint-segment-transition"
sys.path.insert(0, str(ROOT / "tests"))
import test_attestation_nonce_store_checkpoint_segment_transition as r22_helpers  # noqa: E402,E501


class CreateAttestationNonceStoreCheckpointSegmentTransitionCliTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ssh_keygen = shutil.which("ssh-keygen")

    def digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_creation_schema_is_closed_and_keeps_authority_claims_false(self) -> None:
        schema = json.loads(CREATION_SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            ["SEGMENT_TRANSITION_CANDIDATE_CREATED", "INVALID"],
        )
        claims = schema["properties"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertIs(
            claims["properties"]["transition_signature_verified"]["const"], False
        )
        self.assertIs(
            claims["properties"]["successor_checkpoint_signature_verified"][
                "const"
            ],
            False,
        )
        for name in (
            "actual_key_rotation_executed",
            "old_key_revocation_verified",
            "protected_runner_execution_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
        ):
            self.assertIs(claims["properties"][name]["const"], False)
        self.assertEqual(
            schema["properties"]["public_beta"]["const"],
            "NO_GO_UNPUBLISHED",
        )

    def make_unsigned_case(
        self,
        temporary: Path,
        *,
        mode: str = "KEY_ROTATION_SEGMENT",
        reuse_prior_key_with_reformatted_policy: bool = False,
    ) -> tuple[
        r22_helpers.AttestationNonceStoreCheckpointSegmentTransitionCliTests,
        dict[str, object],
    ]:
        helper = (
            r22_helpers.AttestationNonceStoreCheckpointSegmentTransitionCliTests(
                methodName="test_key_rotation_segment_binds_old_chain_new_successor_and_store"
            )
        )
        helper.ssh_keygen = self.ssh_keygen
        material = helper.make_case(
            temporary,
            mode=mode,
            reuse_prior_key_with_reformatted_policy=(
                reuse_prior_key_with_reformatted_policy
            ),
        )
        Path(material["transition_signature"]).unlink()
        Path(material["transition"]).unlink()
        return helper, material

    def create_transition(
        self,
        material: dict[str, object],
        output: Path,
        *,
        mode: str = "KEY_ROTATION_SEGMENT",
        transition_id_sha256: str | None = None,
        issued_at: str = "2026-08-03T01:00:00Z",
        expires_at: str = "2026-08-03T01:10:00Z",
        expected_bundle_sha256: str | None = None,
        expected_successor_sha256: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        case = material["case"]
        reviewer = material["transition_reviewer"]
        assert isinstance(case, dict) and isinstance(reviewer, dict)
        inputs = case["inputs"]
        assert isinstance(inputs, dict)
        bundle = Path(material["bundle"])
        successor = Path(material["successor"])
        return subprocess.run(
            [
                sys.executable,
                str(CREATE_TRANSITION),
                str(bundle),
                expected_bundle_sha256 or self.digest(bundle),
                str(successor),
                str(material["successor_signature"]),
                expected_successor_sha256 or self.digest(successor),
                str(inputs["allowed_signers"]),
                str(inputs["identity_file"]),
                str(material["successor_allowed"]),
                str(material["successor_identity"]),
                str(reviewer["allowed"]),
                str(reviewer["identity"]),
                mode,
                transition_id_sha256
                or hashlib.sha256(b"r23-transition-id").hexdigest(),
                issued_at,
                expires_at,
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_key_rotation_candidate_round_trips_through_r22_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            helper, material = self.make_unsigned_case(temporary)
            output = temporary / "builder-created-transition.json"

            created = self.create_transition(material, output)

            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            self.assertEqual(created.stderr, "")
            report = json.loads(created.stdout)
            self.assertEqual(report["status"], "SEGMENT_TRANSITION_CANDIDATE_CREATED")
            self.assertTrue(report["claims"]["private_transition_candidate_created"])
            self.assertFalse(report["claims"]["transition_signature_verified"])
            self.assertFalse(report["claims"]["public_beta_go"])
            self.assertEqual(report["transition_file_sha256"], self.digest(output))

            candidate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(candidate["transition_mode"], "KEY_ROTATION_SEGMENT")
            self.assertTrue(all(value is False for value in candidate["claims"].values()))
            self.assertEqual(candidate["public_beta"], "NO_GO_UNPUBLISHED")

            reviewer = material["transition_reviewer"]
            assert isinstance(reviewer, dict)
            material["transition"] = output
            material["transition_signature"] = helper.sign(
                output, reviewer["key"], TRANSITION_NAMESPACE
            )
            verified = helper.verify_transition(material)

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(
            json.loads(verified.stdout)["status"],
            "SIGNED_KEY_ROTATION_SEGMENT_TRANSITION",
        )

    def test_same_policy_candidate_round_trips_without_rotation_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            helper, material = self.make_unsigned_case(
                temporary, mode="SAME_POLICY_SEGMENT"
            )
            output = temporary / "same-policy-transition.json"

            created = self.create_transition(
                material, output, mode="SAME_POLICY_SEGMENT"
            )

            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            candidate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(candidate["transition_mode"], "SAME_POLICY_SEGMENT")
            self.assertFalse(
                json.loads(created.stdout)["claims"]["actual_key_rotation_executed"]
            )
            reviewer = material["transition_reviewer"]
            assert isinstance(reviewer, dict)
            material["transition"] = output
            material["transition_signature"] = helper.sign(
                output, reviewer["key"], TRANSITION_NAMESPACE
            )
            verified = helper.verify_transition(material)

        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(
            json.loads(verified.stdout)["status"],
            "SIGNED_SAME_POLICY_SEGMENT_TRANSITION",
        )

    def test_output_is_deterministic_and_existing_file_is_never_overwritten(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _, material = self.make_unsigned_case(temporary)
            first = temporary / "first-transition.json"
            second = temporary / "second-transition.json"

            first_result = self.create_transition(material, first)
            second_result = self.create_transition(material, second)
            before = first.read_bytes()
            refused = self.create_transition(material, first)

            self.assertEqual(first_result.returncode, 0)
            self.assertEqual(second_result.returncode, 0)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(refused.returncode, 1)
            self.assertEqual(refused.stderr, "")
            refused_report = json.loads(refused.stdout)
            self.assertEqual(refused_report["status"], "INVALID")
            self.assertIsNone(refused_report["transition_file_sha256"])
            self.assertTrue(
                all(value is False for value in refused_report["claims"].values())
            )
            self.assertEqual(first.read_bytes(), before)

    def test_invalid_pins_mode_id_and_windows_fail_without_output_or_reflection(
        self,
    ) -> None:
        private_marker = "private-r23-marker-must-not-leak"
        cases = (
            {"expected_bundle_sha256": "0" * 64},
            {"expected_successor_sha256": "0" * 64},
            {"mode": private_marker},
            {"transition_id_sha256": private_marker},
            {
                "issued_at": "2026-08-03T01:10:00Z",
                "expires_at": "2026-08-03T01:00:00Z",
            },
            {"expires_at": "2026-08-03T01:20:00Z"},
            {"issued_at": "2026-08-03T01:00:00." + ("0" * 50) + "Z"},
        )
        results: list[tuple[Path, subprocess.CompletedProcess[str]]] = []
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _, material = self.make_unsigned_case(temporary)
            for index, overrides in enumerate(cases):
                output = temporary / f"invalid-{index}.json"
                result = self.create_transition(material, output, **overrides)
                results.append((output, result))

            for output, result in results:
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                self.assertFalse(output.exists())
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "INVALID")
                self.assertTrue(all(value is False for value in report["claims"].values()))
                self.assertNotIn(private_marker, result.stdout + result.stderr)

    def test_usage_error_is_not_a_creation_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CREATE_TRANSITION)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_fake_rotation_reviewer_collision_and_wrong_parent_are_refused(
        self,
    ) -> None:
        results: list[tuple[str, Path, subprocess.CompletedProcess[str]]] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            fake_root = root / "fake-rotation"
            fake_root.mkdir()
            _, fake_material = self.make_unsigned_case(
                fake_root, reuse_prior_key_with_reformatted_policy=True
            )
            fake_output = fake_root / "transition.json"
            results.append(
                ("fake-rotation", fake_output, self.create_transition(fake_material, fake_output))
            )

            collision_root = root / "reviewer-collision"
            collision_root.mkdir()
            _, collision_material = self.make_unsigned_case(collision_root)
            reviewer = collision_material["transition_reviewer"]
            assert isinstance(reviewer, dict)
            reviewer["allowed"] = collision_material["successor_allowed"]
            reviewer["identity"] = collision_material["successor_identity"]
            collision_output = collision_root / "transition.json"
            results.append(
                (
                    "reviewer-collision",
                    collision_output,
                    self.create_transition(collision_material, collision_output),
                )
            )

            parent_root = root / "wrong-parent"
            parent_root.mkdir()
            helper, parent_material = self.make_unsigned_case(parent_root)
            successor = Path(parent_material["successor"])
            successor_value = json.loads(successor.read_text(encoding="utf-8"))
            successor_value["parent_binding"][
                "parent_checkpoint_file_sha256"
            ] = "0" * 64
            successor_value["checkpoint_chain_sha256"] = (
                r22_helpers.r20_helpers.r19_helpers.checkpoint_tool.checkpoint_chain_sha256(
                    successor_value
                )
            )
            successor.write_text(
                json.dumps(successor_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            Path(parent_material["successor_signature"]).unlink()
            parent_material["successor_signature"] = helper.sign(
                successor,
                Path(parent_material["successor_key"]),
                "kotodama-nonce-store-checkpoint",
            )
            parent_output = parent_root / "transition.json"
            results.append(
                (
                    "wrong-parent",
                    parent_output,
                    self.create_transition(parent_material, parent_output),
                )
            )

            for name, output, result in results:
                with self.subTest(name=name):
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertFalse(output.exists())
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "INVALID")
                    self.assertTrue(
                        all(value is False for value in report["claims"].values())
                    )

    def test_duplicate_nonfinite_and_deep_json_are_safe_refusals(self) -> None:
        private_marker = "private-r23-json-marker-must-not-leak"
        payloads = {
            "duplicate": (
                '{"kind":"' + private_marker + '","kind":"duplicate"}'
            ).encode("utf-8"),
            "nonfinite": ('{"kind":NaN,"marker":"' + private_marker + '"}').encode(
                "utf-8"
            ),
            "deep": (b'{"nested":' * 5000)
            + json.dumps(private_marker).encode("utf-8")
            + (b"}" * 5000),
        }
        results: list[tuple[str, Path, subprocess.CompletedProcess[str]]] = []
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _, material = self.make_unsigned_case(temporary)
            bundle = Path(material["bundle"])
            original = bundle.read_bytes()
            for name, payload in payloads.items():
                bundle.write_bytes(payload)
                output = temporary / f"{name}-transition.json"
                results.append((name, output, self.create_transition(material, output)))
                bundle.write_bytes(original)

            for name, output, result in results:
                with self.subTest(name=name):
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertFalse(output.exists())
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "INVALID")
                    self.assertEqual(report["errors"], ["transition creation failed"])
                    self.assertNotIn(private_marker, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
