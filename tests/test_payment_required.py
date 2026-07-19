import base64
import json
import unittest
from pathlib import Path

try:
    from payment_required import (
        compare_channels,
        decode_payment_required_header,
        extract_payment_required,
        validate_accepts,
    )
except ImportError as exc:  # Expected RED until Task 3 creates payment_required.py.
    _IMPORT_ERROR = exc

    def _missing_api(*_args, **_kwargs):
        raise AssertionError(f"payment_required public API is not importable: {_IMPORT_ERROR}") from _IMPORT_ERROR

    compare_channels = _missing_api
    decode_payment_required_header = _missing_api
    extract_payment_required = _missing_api
    validate_accepts = _missing_api
else:
    _IMPORT_ERROR = None

try:
    from payment_required import classify_failure
except ImportError as exc:  # Preferred helper for L402 classification.
    _CLASSIFY_IMPORT_ERROR = exc

    def classify_failure(*_args, **_kwargs):
        raise AssertionError(f"classify_failure is not importable: {_CLASSIFY_IMPORT_ERROR}") from _CLASSIFY_IMPORT_ERROR
else:
    _CLASSIFY_IMPORT_ERROR = None


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _b64_json(obj):
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _case(name, inline):
    fixture = FIXTURE_DIR / f"{name}.json"
    if fixture.exists():
        return json.loads(fixture.read_text(encoding="utf-8"))
    return inline


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

HEADER_PAYMENT_REQUIRED_ALT = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "solana:mainnet",
            "amount": "2500",
            "asset": "USDC",
            "payTo": "So11111111111111111111111111111111111111112",
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

HEADER_ONLY_CASE = _case(
    "header_only_v2",
    {
        "status": 402,
        "headers": {"PAYMENT-REQUIRED": _b64_json(HEADER_PAYMENT_REQUIRED)},
        "body": "",
    },
)

BODY_ONLY_CASE = _case(
    "body_only_v1_legacy",
    {
        "status": 402,
        "headers": {},
        "body": json.dumps(BODY_PAYMENT_REQUIRED_V1),
    },
)

MISMATCH_CASE = _case(
    "header_body_mismatch",
    {
        "status": 402,
        "headers": {"payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
        "body": json.dumps(
            {
                "x402Version": 1,
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "base",
                        "maxAmountRequired": "99999",
                        "amount": "99999",
                        "asset": "USDC",
                        "payTo": "0x2222222222222222222222222222222222222222",
                    }
                ],
                "error": "payment required",
            }
        ),
    },
)


class PaymentRequiredDecodeTests(unittest.TestCase):
    def test_decode_payment_required_header_accepts_case_insensitive_header_name(self):
        decoded = decode_payment_required_header({"PAYMENT-REQUIRED": _b64_json(HEADER_PAYMENT_REQUIRED)})

        self.assertEqual(decoded, HEADER_PAYMENT_REQUIRED)

    def test_decode_payment_required_header_returns_none_when_absent(self):
        self.assertIsNone(decode_payment_required_header({"content-type": "application/json"}))

    def test_decode_payment_required_header_returns_none_for_invalid_base64_or_json(self):
        self.assertIsNone(decode_payment_required_header({"payment-required": "not base64 json"}))


class PaymentRequiredExtractionTests(unittest.TestCase):
    def test_extract_header_only_marks_header_channel_and_uses_header_as_canonical(self):
        result = extract_payment_required(
            HEADER_ONLY_CASE["status"],
            HEADER_ONLY_CASE["headers"],
            HEADER_ONLY_CASE["body"],
        )

        self.assertEqual(result.channel, "header")
        self.assertEqual(result.canonical, HEADER_PAYMENT_REQUIRED)
        self.assertEqual(result.header_obj, HEADER_PAYMENT_REQUIRED)
        self.assertIsNone(result.body_obj)
        self.assertFalse(result.legacy_placement)

    def test_extract_body_only_is_legacy_but_still_canonical_for_validation(self):
        result = extract_payment_required(
            BODY_ONLY_CASE["status"],
            BODY_ONLY_CASE["headers"],
            BODY_ONLY_CASE["body"],
        )

        self.assertEqual(result.channel, "body")
        self.assertEqual(result.canonical, BODY_PAYMENT_REQUIRED_V1)
        self.assertIsNone(result.header_obj)
        self.assertEqual(result.body_obj, BODY_PAYMENT_REQUIRED_V1)
        self.assertTrue(result.legacy_placement)

    def test_extract_both_prefers_header_as_canonical_and_keeps_body_for_comparison(self):
        result = extract_payment_required(
            MISMATCH_CASE["status"],
            MISMATCH_CASE["headers"],
            MISMATCH_CASE["body"],
        )

        self.assertEqual(result.channel, "both")
        self.assertEqual(result.canonical, HEADER_PAYMENT_REQUIRED)
        self.assertEqual(result.header_obj, HEADER_PAYMENT_REQUIRED)
        self.assertIsInstance(result.body_obj, dict)
        self.assertFalse(result.legacy_placement)

    def test_extract_none_for_l402_www_authenticate_without_payment_required_or_body_accepts(self):
        result = extract_payment_required(
            402,
            {"www-authenticate": 'L402 macaroon="abc", invoice="lnbc..."'},
            json.dumps({"error": "payment required"}),
        )

        self.assertEqual(result.channel, "none")
        self.assertIsNone(result.canonical)
        self.assertIsNone(result.header_obj)
        self.assertIsNone(result.body_obj)
        self.assertFalse(result.legacy_placement)


class PaymentRequiredComparisonTests(unittest.TestCase):
    def test_compare_channels_returns_empty_list_when_first_accept_entries_match(self):
        body_equivalent = {
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "10000",
                    "maxAmountRequired": "10000",
                    "asset": "USDC",
                    "payTo": "0x1111111111111111111111111111111111111111",
                }
            ],
            "error": "payment required",
        }

        self.assertEqual(compare_channels(HEADER_PAYMENT_REQUIRED, body_equivalent), [])

    def test_compare_channels_reports_amount_network_and_pay_to_mismatches(self):
        body_obj = json.loads(MISMATCH_CASE["body"])

        mismatches = compare_channels(HEADER_PAYMENT_REQUIRED, body_obj)

        self.assertEqual(set(mismatches), {"amount", "network", "payTo"})


class PaymentRequiredValidationTests(unittest.TestCase):
    def test_validate_accepts_header_v2_requires_amount_and_caip2_network(self):
        result = validate_accepts(HEADER_PAYMENT_REQUIRED, source="header")

        self.assertTrue(result.ok)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.schemes, ["exact"])
        self.assertEqual(result.networks, ["eip155:8453"])
        self.assertEqual(result.findings, [])

    def test_validate_accepts_header_v2_allows_solana_caip2_network(self):
        result = validate_accepts(HEADER_PAYMENT_REQUIRED_ALT, source="header")

        self.assertTrue(result.ok)
        self.assertEqual(result.networks, ["solana:mainnet"])

    def test_validate_accepts_header_v2_rejects_max_amount_without_amount(self):
        header_obj = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "maxAmountRequired": "10000",
                    "payTo": "0x1111111111111111111111111111111111111111",
                }
            ],
            "error": "payment required",
        }

        result = validate_accepts(header_obj, source="header")

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.failure_class)
        self.assertIn("amount", " ".join(result.findings))

    def test_validate_accepts_header_v2_rejects_plain_network_name(self):
        header_obj = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "base",
                    "amount": "10000",
                    "payTo": "0x1111111111111111111111111111111111111111",
                }
            ],
            "error": "payment required",
        }

        result = validate_accepts(header_obj, source="header")

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.failure_class)
        self.assertIn("CAIP-2", " ".join(result.findings))

    def test_validate_accepts_body_v1_accepts_max_amount_required_and_plain_base_network(self):
        result = validate_accepts(BODY_PAYMENT_REQUIRED_V1, source="body")

        self.assertTrue(result.ok)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.schemes, ["exact"])
        self.assertEqual(result.networks, ["base"])
        self.assertEqual(result.findings, [])

    def test_validate_accepts_body_v1_accepts_amount_as_price_field(self):
        body_obj = {
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "base",
                    "amount": "10000",
                    "payTo": "0x1111111111111111111111111111111111111111",
                }
            ],
            "error": "payment required",
        }

        result = validate_accepts(body_obj, source="body")

        self.assertTrue(result.ok)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.networks, ["base"])

    def test_validate_accepts_rejects_empty_accepts_list(self):
        result = validate_accepts({"x402Version": 2, "accepts": [], "error": "payment required"}, source="header")

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.failure_class)
        self.assertIn("accepts", " ".join(result.findings))


class PaymentRequiredFailureClassificationTests(unittest.TestCase):
    def test_classify_failure_identifies_l402_www_authenticate_without_x402_accepts(self):
        failure_class = classify_failure(
            402,
            {"www-authenticate": 'L402 macaroon="abc", invoice="lnbc..."'},
            json.dumps({"error": "payment required"}),
        )

        self.assertEqual(failure_class, "l402_www_authenticate")

    def test_classify_failure_returns_none_when_payment_required_header_is_present(self):
        failure_class = classify_failure(
            402,
            {"www-authenticate": 'L402 macaroon="abc"', "payment-required": _b64_json(HEADER_PAYMENT_REQUIRED)},
            "",
        )

        self.assertIsNone(failure_class)


if __name__ == "__main__":
    unittest.main()
