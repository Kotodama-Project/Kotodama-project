import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.protocol import SwarmError, finite, timestamp, validate_binding


class ProtocolTests(unittest.TestCase):
    def test_timezone_midnight_is_not_expiry(self):
        self.assertEqual(timestamp("2026-09-11T01:25:00+09:00"), timestamp("2026-09-10T16:25:00Z"))
        self.assertGreater(timestamp("2026-09-11T01:25:00+09:00"), timestamp("2026-09-10T16:04:07Z"))
        with self.assertRaises(SwarmError):
            timestamp("2026-09-11T01:25:00")

    def test_nonfinite_limits(self):
        for value in (float("nan"), float("inf"), -float("inf"), True):
            with self.subTest(value=value), self.assertRaises(SwarmError):
                finite(value, "wait", maximum=20)

    def test_owner_binding_is_required_and_current(self):
        binding = dict(task_id="task-demo", revision=1, context_digest="a"*64, owner_ref="owner",
                       active_home="local-demo", authority_ref="work-order", capability_ref="grant",
                       expires_at=200, status="active", actor_ref="worker", epoch=1,
                       invocation_ref="invocation", actor_status="active")
        self.assertEqual(validate_binding(binding, now=100, actor="worker")["epoch"], 1)
        for change in ({"expires_at": 99}, {"actor_ref": "other"}, {"actor_status": "closed"}, {"status": "closed"}):
            with self.subTest(change=change), self.assertRaises(SwarmError):
                validate_binding({**binding, **change}, now=100, actor="worker")
        with self.assertRaises(SwarmError):
            validate_binding({"task_id": "task-demo"}, now=100)


if __name__ == "__main__":
    unittest.main()
