"""Conformance checks for the optional ``extensions.bazaar`` marketplace
discovery block (v2 header-canonical PaymentRequired).

Shape verified against every production capture currently in
``tests/fixtures/`` that carries the block: ``viridis_regulatory_radar``,
``viridis_ghg_ledger``, ``asterpay_crypto_prices``, and
``asterpay_sentiment``. All four agree byte-for-byte on the top-level keys::

    extensions.bazaar.info.input.type    == "http"
    extensions.bazaar.info.input.method  (e.g. "GET" / "POST")
    extensions.bazaar.info.output.type   (e.g. "json")
    extensions.bazaar.schema             (JSON Schema object)

Failure-first: this suite is written against the shape observed in real
captures, not a shape assumed ahead of evidence. An earlier draft check
required ``extensions.bazaar.method == "POST"`` plus ``serviceName`` and
``tags`` fields — none of which exist in any of the four captures above,
so that check would have FAILed 4/4 conformant Bazaar merchants. The tests
below pin the real shape down so that regression is caught immediately.
"""

import base64
import json
import unittest
from pathlib import Path

try:
    from payment_required import check_bazaar_extension, extract_payment_required
except ImportError as exc:  # Expected RED until check_bazaar_extension lands.
    _IMPORT_ERROR = exc

    def _missing_api(*_args, **_kwargs):
        raise AssertionError(
            f"payment_required public API is not importable: {_IMPORT_ERROR}"
        ) from _IMPORT_ERROR

    check_bazaar_extension = _missing_api
    extract_payment_required = _missing_api
else:
    _IMPORT_ERROR = None


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _decode_header_obj(fixture_name: str) -> dict:
    """Load a fixture, decode its PAYMENT-REQUIRED header, return the object."""
    case = json.loads((FIXTURE_DIR / f"{fixture_name}.json").read_text(encoding="utf-8"))
    raw = case["headers"]["payment-required"]
    padded = raw + "=" * (-len(raw) % 4)
    decoded = base64.b64decode(padded)
    obj = json.loads(decoded.decode("utf-8"))
    assert isinstance(obj, dict)
    return obj


class BazaarExtensionAbsentTests(unittest.TestCase):
    """The block is optional (marketplace discovery, not core PaymentRequired).

    Its absence must never fail conformance.
    """

    def test_ok_when_extensions_key_missing_entirely(self):
        obj = {"x402Version": 2, "accepts": [{"scheme": "exact", "network": "eip155:8453"}]}
        result = check_bazaar_extension(obj)

        self.assertTrue(result.ok)
        self.assertFalse(result.present)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.findings, [])

    def test_ok_when_extensions_present_but_no_bazaar_key(self):
        obj = {"x402Version": 2, "accepts": [], "extensions": {"other-thing": {}}}
        result = check_bazaar_extension(obj)

        self.assertTrue(result.ok)
        self.assertFalse(result.present)

    def test_ok_when_obj_is_none(self):
        result = check_bazaar_extension(None)

        self.assertTrue(result.ok)
        self.assertFalse(result.present)


class BazaarExtensionRealCaptureTests(unittest.TestCase):
    """The block must PASS exactly as shipped by every merchant we have
    captured it from — this is the regression guard for the shape.
    """

    def test_viridis_regulatory_radar_capture_passes(self):
        obj = _decode_header_obj("viridis_regulatory_radar")
        result = check_bazaar_extension(obj)

        self.assertTrue(result.ok)
        self.assertTrue(result.present)
        self.assertIsNone(result.failure_class)
        self.assertEqual(result.findings, [])

    def test_viridis_ghg_ledger_capture_passes(self):
        obj = _decode_header_obj("viridis_ghg_ledger")
        result = check_bazaar_extension(obj)

        self.assertTrue(result.ok)
        self.assertTrue(result.present)
        self.assertEqual(result.findings, [])

    def test_asterpay_crypto_prices_capture_passes(self):
        case = json.loads(
            (FIXTURE_DIR / "asterpay_crypto_prices.json").read_text(encoding="utf-8")
        )
        body_obj = json.loads(case["body"])
        result = check_bazaar_extension(body_obj)

        self.assertTrue(result.ok)
        self.assertTrue(result.present)
        self.assertEqual(result.findings, [])

    def test_asterpay_sentiment_capture_passes(self):
        case = json.loads(
            (FIXTURE_DIR / "asterpay_sentiment.json").read_text(encoding="utf-8")
        )
        body_obj = json.loads(case["body"])
        result = check_bazaar_extension(body_obj)

        self.assertTrue(result.ok)
        self.assertTrue(result.present)
        self.assertEqual(result.findings, [])


class BazaarExtensionMalformedTests(unittest.TestCase):
    """Negative fixtures: present but broken in ways a real marketplace
    client parsing this block would choke on.
    """

    def test_fail_when_bazaar_is_not_an_object(self):
        obj = {"extensions": {"bazaar": "not-an-object"}}
        result = check_bazaar_extension(obj)

        self.assertFalse(result.ok)
        self.assertTrue(result.present)
        self.assertEqual(result.failure_class, "bazaar_malformed")
        self.assertIn("not an object", " ".join(result.findings))

    def test_fail_when_info_missing(self):
        obj = {"extensions": {"bazaar": {"schema": {"type": "object"}}}}
        result = check_bazaar_extension(obj)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "bazaar_malformed")
        self.assertIn("info", " ".join(result.findings))

    def test_fail_when_input_missing_method(self):
        obj = {
            "extensions": {
                "bazaar": {
                    "info": {
                        "input": {"type": "http"},  # method missing
                        "output": {"type": "json", "example": {}},
                    }
                }
            }
        }
        result = check_bazaar_extension(obj)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "bazaar_malformed")
        self.assertIn("info.input.method", " ".join(result.findings))

    def test_fail_when_output_missing(self):
        obj = {
            "extensions": {
                "bazaar": {
                    "info": {
                        "input": {"type": "http", "method": "GET"},
                        # output missing entirely
                    }
                }
            }
        }
        result = check_bazaar_extension(obj)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "bazaar_malformed")
        self.assertIn("info.output", " ".join(result.findings))

    def test_fail_when_schema_present_but_not_an_object(self):
        obj = {
            "extensions": {
                "bazaar": {
                    "info": {
                        "input": {"type": "http", "method": "GET"},
                        "output": {"type": "json", "example": {}},
                    },
                    "schema": "not-an-object",
                }
            }
        }
        result = check_bazaar_extension(obj)

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "bazaar_malformed")
        self.assertIn("schema", " ".join(result.findings))


class BazaarExtensionNegativeFixtureIntegrationTests(unittest.TestCase):
    """End-to-end through extract_payment_required, using the two negative
    fixtures. Both fixtures are explicitly marked ``"constructed": true`` —
    they are synthetic edge cases exercising the error path, not merchant
    captures, per the provenance standard the rest of this fixture corpus
    follows.
    """

    def _load_and_extract(self, fixture_name):
        case = json.loads(
            (FIXTURE_DIR / f"{fixture_name}.json").read_text(encoding="utf-8")
        )
        self.assertTrue(
            case.get("constructed") is True,
            f"{fixture_name} must be marked constructed=true (synthetic, not captured)",
        )
        extracted = extract_payment_required(
            case["status"], case["headers"], case["body"]
        )
        return case, extracted

    def test_bazaar_malformed_missing_method_fixture(self):
        case, extracted = self._load_and_extract("bazaar_malformed_missing_method")

        self.assertIsNotNone(extracted.header_obj)
        result = check_bazaar_extension(extracted.header_obj)

        self.assertEqual(result.ok, case["expect"]["bazaar_ok"])
        self.assertEqual(result.failure_class, case["expect"]["bazaar_failure_class"])
        self.assertTrue(result.present)

    def test_bazaar_malformed_missing_output_fixture(self):
        case, extracted = self._load_and_extract("bazaar_malformed_missing_output")

        self.assertIsNotNone(extracted.header_obj)
        result = check_bazaar_extension(extracted.header_obj)

        self.assertEqual(result.ok, case["expect"]["bazaar_ok"])
        self.assertEqual(result.failure_class, case["expect"]["bazaar_failure_class"])
        self.assertTrue(result.present)


if __name__ == "__main__":
    unittest.main()
