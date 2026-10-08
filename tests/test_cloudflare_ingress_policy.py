import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tools import validate_cloudflare_ingress_policy as checker

ROOT=Path(__file__).resolve().parents[1]


class IngressPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy=json.loads((ROOT/"examples/cloudflare-ingress/synthetic-policy.json").read_text(encoding="utf-8"))
        self.now=datetime(2026,10,8,0,30,tzinfo=timezone.utc)

    def test_proposed_policy_is_not_a_provider_or_origin_closure_receipt(self):
        result=checker.validate(self.policy,now=self.now)
        self.assertEqual(result["origin_count"],1)
        for field in ("configuration_verified","identity_verified","direct_origin_closure_verified","token_verified","deployment_authorized"):
            self.assertFalse(result[field])

    def test_multiple_origins_bypass_direct_access_and_raw_locators_are_refused(self):
        for mutate in (
            lambda p:p["origins"].append(dict(p["origins"][0])),
            lambda p:p["access"].update(bypass_allowed=True),
            lambda p:p["access"].update(default_deny=False),
            lambda p:p["origins"][0].update(direct_ingress="open"),
            lambda p:p.update(hostname_locator="private-host.example"),
            lambda p:p["service_token"].update(value="private-token-marker"),
            lambda p:p["service_token"].update(revoked=True),
        ):
            value=copy.deepcopy(self.policy); mutate(value)
            with self.assertRaises(ValueError):
                checker.validate(value,now=self.now)

    def test_admin_data_ports_and_cleartext_tailnet_origin_are_refused(self):
        for port in checker.FORBIDDEN_PORTS:
            value=copy.deepcopy(self.policy); value["origins"][0]["port"]=port
            with self.subTest(port=port), self.assertRaises(ValueError):
                checker.validate(value,now=self.now)
        self.policy["origins"][0]["network"]="private_tailnet"
        with self.assertRaises(ValueError):
            checker.validate(self.policy,now=self.now)
        self.policy["origins"][0]["transport"]="https"
        checker.validate(self.policy,now=self.now)

    def test_expired_future_overlong_tokens_and_reused_access_plan_are_refused(self):
        for at in (datetime(2026,10,7,tzinfo=timezone.utc),datetime(2026,10,8,1,tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):
                checker.validate(self.policy,now=at)
        overlong=copy.deepcopy(self.policy); overlong["service_token"]["expires_at"]="2026-10-10T00:00:00Z"
        with self.assertRaises(ValueError):
            checker.validate(overlong,now=self.now)
        self.policy["access"]["gateway_policy_digest"]=self.policy["access"]["frontend_policy_digest"]
        with self.assertRaises(ValueError):
            checker.validate(self.policy,now=self.now)


if __name__=="__main__":
    unittest.main()
