"""Three-state severity mapping for the optional extensions.bazaar check.

Contract fixed when the 1.3.0 three-state line (a9fb1aa) merged with the
PR #16 bazaar conformance check: the two features are orthogonal and must
stay orthogonal.

  absent            -> bazaar_severity == "info"  (nothing verified)
  present + ok      -> bazaar_severity == "pass"
  present + broken  -> bazaar_severity == "fail"  (scoped to the extension)

A malformed extension never enters the endpoint-level severity: it is
marketplace-discovery metadata, not part of the PaymentRequired contract.
"""

import base64
import json
import unittest
from pathlib import Path
from unittest import mock

import requests

from payment_required import SEVERITY_FAIL, SEVERITY_INFO, SEVERITY_PASS
from validator import check_402_body

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name):
    with open(FIXTURES / f"{name}.json") as fh:
        return json.load(fh)


def _b64_json(obj):
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


class MockResponse:
    def __init__(self, status_code, *, headers=None, json_data=None, text=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data
        self.text = text if text is not None else (
            json.dumps(json_data) if json_data is not None else ""
        )

    def json(self):
        if self._json_data is None:
            raise ValueError("response body is not JSON")
        return self._json_data


HEADER_PAYMENT_REQUIRED = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": "10000",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "payTo": "0x1111111111111111111111111111111111111111",
        }
    ],
    "error": "payment required",
}


class BazaarSeverityMappingTests(unittest.TestCase):
    def _run_fixture(self, name):
        case = _load_fixture(name)
        response = MockResponse(case["status"], headers=case["headers"], text=case["body"])
        with mock.patch("validator.requests.get", return_value=response), mock.patch(
            "validator.requests.post", return_value=MockResponse(404, text="")
        ):
            return check_402_body("https://example.test/paywalled")

    def test_absent_block_is_info_not_pass(self):
        """Absence is never laundered into a pass — nothing was verified."""
        with mock.patch(
            "validator.requests.get",
            return_value=MockResponse(
                402,
                headers={"payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
                json_data={"error": "payment required"},
            ),
        ), mock.patch("validator.requests.post", return_value=MockResponse(404)):
            result = check_402_body("https://example.test/paywalled")

        self.assertFalse(result["bazaar_present"])
        self.assertEqual(result["bazaar_severity"], SEVERITY_INFO)
        self.assertEqual(result["severity"], SEVERITY_PASS)

    def test_present_and_conformant_is_pass(self):
        result = self._run_fixture("viridis_regulatory_radar")

        self.assertTrue(result["bazaar_present"])
        self.assertEqual(result["bazaar_severity"], SEVERITY_PASS)

    def test_malformed_block_is_fail_but_does_not_convict_the_endpoint(self):
        for name in ("bazaar_malformed_missing_method", "bazaar_malformed_missing_output"):
            with self.subTest(fixture=name):
                result = self._run_fixture(name)

                self.assertEqual(result["bazaar_severity"], SEVERITY_FAIL)
                self.assertEqual(result["bazaar_failure_class"], "bazaar_malformed")
                # The payment-conformance verdict is a separate contract.
                self.assertTrue(result["passed"])
                self.assertEqual(result["severity"], SEVERITY_PASS)
                self.assertIsNone(result["failure_class"])

    def test_network_error_record_carries_the_bazaar_fields(self):
        """Report schema stays uniform: no KeyError on unreachable endpoints."""
        with mock.patch(
            "validator.requests.get", side_effect=requests.RequestException("boom")
        ), mock.patch(
            "validator.requests.post", side_effect=requests.RequestException("boom")
        ):
            result = check_402_body("https://example.test/dead")

        self.assertFalse(result["bazaar_present"])
        self.assertIsNone(result["bazaar_ok"])
        self.assertIsNone(result["bazaar_failure_class"])
        self.assertEqual(result["bazaar_severity"], SEVERITY_INFO)


if __name__ == "__main__":
    unittest.main()
