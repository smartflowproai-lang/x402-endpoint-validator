import base64
import json
import unittest
from pathlib import Path
from unittest import mock

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
        self.text = text if text is not None else (json.dumps(json_data) if json_data is not None else "")

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

BODY_PAYMENT_REQUIRED_V1 = {
    "x402Version": 1,
    "accepts": [
        {
            "scheme": "exact",
            "network": "base",
            "maxAmountRequired": "10000",
            "asset": "USDC",
            "payTo": "0x1111111111111111111111111111111111111111",
        }
    ],
    "error": "payment required",
}


class Check402BodyTask4ContractTests(unittest.TestCase):
    """RED integration contracts for Task 4 validator wiring."""

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_header_only_get_402_reports_header_channel_fields(self, mock_get, mock_post):
        mock_get.return_value = MockResponse(
            402,
            headers={"payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
            text="",
        )
        mock_post.return_value = MockResponse(
            402,
            headers={"payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
            text="",
        )

        result = check_402_body("https://example.test/paywalled")

        self.assertTrue(result["passed"])
        self.assertEqual(result["channel"], "header")
        self.assertFalse(result["legacy_placement"])
        self.assertIsNone(result["failure_class"])
        self.assertEqual(result["probe_method"], "GET")
        self.assertFalse(result["channel_mismatch"])
        mock_get.assert_called_once()
        mock_post.assert_not_called()

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_body_only_post_402_reports_legacy_placement(self, mock_get, mock_post):
        mock_get.return_value = MockResponse(200, json_data={"ok": True})
        mock_post.return_value = MockResponse(402, json_data=BODY_PAYMENT_REQUIRED_V1)

        result = check_402_body("https://example.test/paywalled")

        self.assertTrue(result["passed"])
        self.assertEqual(result["channel"], "body")
        self.assertTrue(result["legacy_placement"])
        self.assertIsNone(result["failure_class"])
        self.assertEqual(result["probe_method"], "POST")
        self.assertFalse(result["channel_mismatch"])
        mock_get.assert_called_once()
        mock_post.assert_called_once()

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_invalid_header_with_valid_body_is_v2_header_invalid(self, mock_get, mock_post):
        mock_get.return_value = MockResponse(
            402,
            headers={"payment-required": "%%%not-base64%%%"},
            json_data=BODY_PAYMENT_REQUIRED_V1,
        )
        mock_post.return_value = MockResponse(404)

        result = check_402_body("https://example.test/paywalled")

        self.assertFalse(result["passed"])
        self.assertEqual(result["failure_class"], "v2_header_invalid")
        self.assertFalse(result["legacy_placement"])
        self.assertEqual(result["channel"], "none")

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_l402_www_authenticate_only_reports_failure_class(self, mock_get, mock_post):
        mock_get.return_value = MockResponse(
            402,
            headers={"www-authenticate": 'L402 macaroon="abc", invoice="lnbc..."'},
            json_data={"error": "payment required"},
        )
        mock_post.return_value = MockResponse(
            402,
            headers={"www-authenticate": 'L402 macaroon="abc", invoice="lnbc..."'},
            json_data={"error": "payment required"},
        )

        result = check_402_body("https://example.test/paywalled")

        self.assertFalse(result["passed"])
        self.assertEqual(result["channel"], "none")
        self.assertFalse(result["legacy_placement"])
        self.assertEqual(result["failure_class"], "l402_www_authenticate")
        self.assertEqual(result["probe_method"], "GET")
        self.assertFalse(result["channel_mismatch"])
        mock_get.assert_called_once()
        mock_post.assert_not_called()


class Check402BodyBazaarWiringTests(unittest.TestCase):
    """The bazaar extension check must run through the real entry point, not
    only when tests call the helper by hand. A merchant with a malformed
    extensions.bazaar block previously got the same green report as a
    merchant without one; now the report carries bazaar_ok /
    bazaar_failure_class. The core 402 verdict is unchanged — the extension
    is optional marketplace-discovery metadata, not part of the
    PaymentRequired contract.
    """

    def _run_fixture(self, name):
        case = _load_fixture(name)
        response = MockResponse(case["status"], headers=case["headers"], text=case["body"])
        with mock.patch("validator.requests.get", return_value=response), mock.patch(
            "validator.requests.post", return_value=MockResponse(404, text="")
        ):
            return check_402_body("https://example.test/paywalled"), case

    def test_malformed_bazaar_missing_method_surfaces_in_report(self):
        result, case = self._run_fixture("bazaar_malformed_missing_method")

        self.assertTrue(result["passed"])
        self.assertIsNone(result["failure_class"])
        self.assertTrue(result["bazaar_present"])
        self.assertEqual(result["bazaar_ok"], case["expect"]["bazaar_ok"])
        self.assertEqual(result["bazaar_failure_class"], case["expect"]["bazaar_failure_class"])
        self.assertTrue(
            any("bazaar" in finding for finding in result["findings"]),
            result["findings"],
        )

    def test_malformed_bazaar_missing_output_surfaces_in_report(self):
        result, case = self._run_fixture("bazaar_malformed_missing_output")

        self.assertTrue(result["passed"])
        self.assertIsNone(result["failure_class"])
        self.assertTrue(result["bazaar_present"])
        self.assertEqual(result["bazaar_ok"], case["expect"]["bazaar_ok"])
        self.assertEqual(result["bazaar_failure_class"], case["expect"]["bazaar_failure_class"])
        self.assertTrue(
            any("bazaar" in finding for finding in result["findings"]),
            result["findings"],
        )

    def test_conformant_bazaar_block_reports_ok(self):
        result, _ = self._run_fixture("viridis_regulatory_radar")

        self.assertTrue(result["passed"])
        self.assertTrue(result["bazaar_present"])
        self.assertTrue(result["bazaar_ok"])
        self.assertIsNone(result["bazaar_failure_class"])

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_absent_bazaar_block_stays_silent(self, mock_get, mock_post):
        mock_get.return_value = MockResponse(
            402,
            headers={"payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
            json_data={"error": "payment required"},
        )
        mock_post.return_value = MockResponse(404)

        result = check_402_body("https://example.test/paywalled")

        self.assertTrue(result["passed"])
        self.assertFalse(result["bazaar_present"])
        self.assertIsNone(result["bazaar_ok"])
        self.assertIsNone(result["bazaar_failure_class"])
        self.assertFalse(any("bazaar" in finding for finding in result["findings"]))


if __name__ == "__main__":
    unittest.main()
