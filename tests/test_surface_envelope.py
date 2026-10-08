import copy
import json
from pathlib import Path
import unittest

from tools import validate_surface_envelope as validator
from tests.test_session_conversation_ledger import _event, ledger

ROOT = Path(__file__).resolve().parents[1]


class SurfaceEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "examples/surface-envelope/slack.json").read_text(encoding="utf-8"))

    def test_each_surface_is_a_contract_without_authentication_or_execution_claims(self):
        for surface in ("slack", "teams"):
            report = validator.validate({**self.fixture, "surface": surface})
            self.assertEqual(report["status"], "SYNTHETIC_CONTRACT_VALID")
            for key in ("signature_verified", "membership_verified", "provider_verified", "task_created"):
                self.assertFalse(report[key])

    def test_unknown_fields_acl_tombstone_and_media_are_refused(self):
        changes = [dict(approved=True), dict(operation="delete"), dict(synthetic=False),
                   dict(acl={"tenant":"tenant-b", "readers":["actor-a"]}),
                   dict(capabilities={**self.fixture["capabilities"], "receiveAudio":True})]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validator.validate({**self.fixture, **changed})
        validator.validate({**self.fixture, "operation":"delete", "text":""})
        with self.assertRaises(ValueError):
            json.loads('{"actor":"a","actor":"b"}', object_pairs_hook=validator.unique)

    def test_ledger_accepts_text_metadata_but_does_not_infer_voice_or_consent(self):
        for source in ("slack_text", "teams_text"):
            event = _event("surface-text", source_type=source)
            self.assertEqual(ledger.validate_ledger([event])["result"], "LEDGER_VALID")
            missing = copy.deepcopy(event)
            missing["source"]["consent_ref"] = None
            missing = ledger.seal_event(missing, sequence=1, previous_hash=None)
            self.assertNotEqual(ledger.validate_ledger([missing])["result"], "LEDGER_VALID")


if __name__ == "__main__":
    unittest.main()
