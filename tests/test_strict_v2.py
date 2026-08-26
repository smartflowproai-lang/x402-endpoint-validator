import base64
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import validator
from payment_required import decode_payment_required_header, validate_accepts
from validator import (
    RAW_RESPONSE_BODY_MAX_BYTES,
    REDACTED_HEADER_PLACEHOLDER,
    build_raw_response,
    check_402_body,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _b64_json(obj):
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _load_fixture(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _strict_payment_required(**accept_overrides):
    accept = {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "10000",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "payTo": "0x1111111111111111111111111111111111111111",
        "maxTimeoutSeconds": 60,
    }
    accept.update(accept_overrides)
    return {
        "x402Version": 2,
        "accepts": [accept],
        "error": "payment required",
    }


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


class StrictV2ValidationTests(unittest.TestCase):
    def test_strict_rejects_header_accept_with_only_max_amount_required(self):
        obj = _strict_payment_required(maxAmountRequired="10000")
        del obj["accepts"][0]["amount"]

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "amount_key")
        self.assertIn("amount", " ".join(result.findings))

    def test_strict_rejects_plain_network_base_on_header(self):
        obj = _strict_payment_required(network="base")

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "network_format")
        self.assertIn("CAIP-2", " ".join(result.findings))

    def test_strict_rejects_missing_max_timeout_seconds(self):
        obj = _strict_payment_required()
        del obj["accepts"][0]["maxTimeoutSeconds"]

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertFalse(result.ok)
        self.assertIn("maxTimeoutSeconds", " ".join(result.findings))

    def test_strict_rejects_unknown_scheme(self):
        obj = _strict_payment_required(scheme="wildcard")

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "scheme_unsupported")
        self.assertIn("scheme", " ".join(result.findings))

    def test_strict_requires_integer_x402_version_2(self):
        obj = _strict_payment_required()
        obj["x402Version"] = "2"

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertFalse(result.ok)
        self.assertIn("x402Version", " ".join(result.findings))

    @unittest.skipUnless((FIXTURE_DIR / "asterpay_sentiment.json").exists(), "asterpay fixture not present")
    def test_strict_accepts_asterpay_fixture_if_present(self):
        case = _load_fixture("asterpay_sentiment")
        obj = decode_payment_required_header(case["headers"])

        result = validate_accepts(obj, source="header", strict_v2=True)

        self.assertTrue(result.ok, result.findings)
        self.assertIsNone(result.failure_class)
        self.assertIn("eip155:8453", result.networks)


class StrictV2Check402BodyTests(unittest.TestCase):
    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_strict_rejects_body_only_v1_fixture(self, mock_get, mock_post):
        case = _load_fixture("body_only_v1_legacy")
        mock_get.return_value = MockResponse(case["status"], headers=case["headers"], text=case["body"])
        mock_post.return_value = MockResponse(404)

        result = check_402_body(case["url"], strict_v2=True)

        self.assertFalse(result["passed"])
        self.assertEqual(result["channel"], "body")
        self.assertTrue(result["legacy_placement"])
        self.assertIn(result["failure_class"], {"legacy_placement", "legacy_placement_forbidden"})
        self.assertTrue(result["strict_v2"])
        mock_get.assert_called_once()
        mock_post.assert_not_called()

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_check_402_body_strict_includes_raw_response_keys(self, mock_get, mock_post):
        obj = _strict_payment_required()
        pr = _b64_json(obj)
        mock_get.return_value = MockResponse(
            402,
            headers={
                "payment-required": pr,
                "content-type": "application/json",
                "Set-Cookie": "session=secret",
                "Authorization": "Bearer leaked-token",
            },
            text="{}",
        )
        mock_post.return_value = MockResponse(404)
        url = "https://example.test/paywalled"

        result = check_402_body(url, strict_v2=True)

        self.assertTrue(result["passed"], result)
        self.assertTrue(result["strict_v2"])
        self.assertIn("raw_response", result)
        self.assertEqual(
            set(result["raw_response"]),
            {
                "method",
                "url",
                "status_code",
                "headers",
                "body",
                "body_truncated",
                "body_sha256",
            },
        )
        raw = result["raw_response"]
        self.assertEqual(raw["method"], "GET")
        self.assertEqual(raw["url"], url)
        self.assertEqual(raw["status_code"], 402)
        self.assertEqual(raw["headers"]["payment-required"], pr)
        self.assertEqual(raw["headers"]["set-cookie"], REDACTED_HEADER_PLACEHOLDER)
        self.assertEqual(raw["headers"]["authorization"], REDACTED_HEADER_PLACEHOLDER)
        self.assertEqual(raw["body"], "{}")
        self.assertFalse(raw["body_truncated"])
        self.assertEqual(
            raw["body_sha256"],
            hashlib.sha256(b"{}").hexdigest(),
        )
        self.assertRegex(result["probed_at_utc"], ISO_Z_RE)
        mock_get.assert_called_once()
        mock_post.assert_not_called()

    @mock.patch("validator.requests.post")
    @mock.patch("validator.requests.get")
    def test_default_strict_v2_false_still_allows_body_only_legacy(self, mock_get, mock_post):
        case = _load_fixture("body_only_v1_legacy")
        mock_get.return_value = MockResponse(case["status"], headers=case["headers"], text=case["body"])
        mock_post.return_value = MockResponse(404)

        result = check_402_body(case["url"])

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["channel"], "body")
        self.assertTrue(result["legacy_placement"])
        self.assertIsNone(result["failure_class"])

    def test_build_raw_response_truncates_large_body_and_hashes_full_original(self):
        full_body = "x" * (RAW_RESPONSE_BODY_MAX_BYTES + 50)
        full_sha = hashlib.sha256(full_body.encode("utf-8")).hexdigest()

        raw = build_raw_response(
            method="POST",
            url="https://example.test/huge",
            status_code=402,
            headers={"Content-Type": "text/plain", "SET-COOKIE": "a=b"},
            body_text=full_body,
        )

        self.assertEqual(raw["method"], "POST")
        self.assertEqual(raw["url"], "https://example.test/huge")
        self.assertTrue(raw["body_truncated"])
        self.assertEqual(len(raw["body"].encode("utf-8")), RAW_RESPONSE_BODY_MAX_BYTES)
        self.assertEqual(raw["body_sha256"], full_sha)
        self.assertNotEqual(raw["body"], full_body)
        self.assertEqual(raw["headers"]["set-cookie"], REDACTED_HEADER_PLACEHOLDER)
        self.assertEqual(raw["headers"]["content-type"], "text/plain")

    def test_build_raw_response_null_body_sha_when_no_body(self):
        raw = build_raw_response(
            method="GET",
            url="https://example.test/empty",
            status_code=402,
            headers={},
            body_text=None,
        )
        self.assertEqual(raw["body"], "")
        self.assertFalse(raw["body_truncated"])
        self.assertIsNone(raw["body_sha256"])


class StrictV2ReportMainTests(unittest.TestCase):
    def test_main_env_strict_v2_wires_summary_and_endpoint_probe_time(self):
        strict_values = []

        def fake_check_402_body(url, probe_method="auto", strict_v2=False, **kwargs):
            strict_values.append(strict_v2)
            return {
                "passed": True,
                "payment_required_passed": True,
                "status_code": 402,
                "body_conformant": True,
                "channel": "header",
                "probe_method": probe_method,
                "schemes": ["exact"],
                "networks": ["eip155:8453"],
                "failure_class": None,
                "legacy_placement": False,
                "channel_mismatch": False,
                "channel_mismatch_fields": [],
                "caip2_in_header": True,
                "missing_keys": [],
                "x402_version": 2,
                "findings": [],
                "strict_v2": strict_v2,
                "probed_at_utc": "2001-02-03T04:05:06Z",
                "raw_response": {
                    "method": "GET",
                    "url": "https://example.test/paywalled",
                    "status_code": 402,
                    "headers": {},
                    "body": "",
                    "body_truncated": False,
                    "body_sha256": hashlib.sha256(b"").hexdigest(),
                },
                "note": "ok",
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            env = {
                "X402V_ENDPOINTS": "https://example.test/paywalled",
                "X402V_REPORT_PATH": report_path,
                "X402V_STRICT_V2": "true",
                "X402V_PROBE_METHOD": "GET",
            }
            with mock.patch.dict(os.environ, env, clear=True), mock.patch(
                "validator.check_reachability",
                return_value={"passed": True, "status_code": 402, "response_time_ms": 1, "note": "ok"},
            ), mock.patch(
                "validator.check_manifest",
                return_value={
                    "passed": True,
                    "manifest_url": "https://example.test/.well-known/x402",
                    "status_code": 200,
                    "schema_kind": "v2-provider-payment",
                    "x402_version": 2,
                    "note": "ok",
                },
            ), mock.patch(
                "validator.check_402_body",
                side_effect=fake_check_402_body,
            ), mock.patch(
                "validator.check_p95",
                return_value={
                    "passed": True,
                    "samples_ms": [1],
                    "p95_ms": 1,
                    "threshold_ms": 1000,
                    "errors": 0,
                    "note": "ok",
                },
            ), mock.patch("validator.print_upsell"):
                exit_code = validator.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(strict_values, [True])
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))

        self.assertTrue(report["summary"]["strict_v2"])
        self.assertEqual(report["summary"]["probe_method"], "GET")
        self.assertEqual(report["endpoints"][0]["probed_at_utc"], "2001-02-03T04:05:06Z")
        self.assertTrue(report["endpoints"][0]["checks"]["body_conformance"]["strict_v2"])


if __name__ == "__main__":
    unittest.main()
