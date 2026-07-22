"""Unit tests for check_manifest schema recognition variants."""
import json
import unittest
from unittest.mock import patch, MagicMock

import validator


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


class TestManifestSchemaKinds(unittest.TestCase):
    def _run(self, payload):
        with patch.object(validator.requests, "get", return_value=_mock_response(payload)):
            return validator.check_manifest("https://example.com/api/data")

    def test_v1_accepts(self):
        out = self._run({"x402Version": 1, "accepts": [{"scheme": "exact"}]})
        self.assertTrue(out["passed"])
        self.assertEqual(out["schema_kind"], "v1-accepts")

    def test_v2_provider_payment(self):
        out = self._run({"x402Version": 2, "payment": {"payTo": "0xabc"}, "resources": ["https://example.com/a"]})
        self.assertTrue(out["passed"])
        self.assertEqual(out["schema_kind"], "v2-provider-payment")

    def test_v2_resource_accepts_passes(self):
        # Per-resource accepts, no top-level payment block (seen in the wild).
        payload = {
            "x402Version": 2,
            "service": "example",
            "resources": [
                {"resource": "https://example.com/a", "accepts": [{"scheme": "exact", "network": "eip155:8453"}]},
                {"resource": "https://example.com/b", "accepts": [{"scheme": "exact", "network": "eip155:8453"}]},
            ],
        }
        out = self._run(payload)
        self.assertTrue(out["passed"])
        self.assertEqual(out["schema_kind"], "v2-resource-accepts")

    def test_resource_list_bare_fails_with_specific_note(self):
        payload = {"version": 1, "resources": ["https://example.com/a", "https://example.com/b"]}
        out = self._run(payload)
        self.assertFalse(out["passed"])
        self.assertEqual(out["schema_kind"], "resource-list-bare")
        self.assertIn("without payment terms", out["note"])

    def test_unknown_schema_still_unknown(self):
        out = self._run({"hello": "world"})
        self.assertFalse(out["passed"])
        self.assertEqual(out["schema_kind"], "unknown")

    def test_resource_dicts_without_accepts_not_recognised(self):
        payload = {"resources": [{"resource": "https://example.com/a"}, {"resource": "https://example.com/b"}]}
        out = self._run(payload)
        self.assertFalse(out["passed"])
        self.assertEqual(out["schema_kind"], "unknown")


if __name__ == "__main__":
    unittest.main()
