"""Golden-fixture conformance against issue #3 corpus captures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from payment_required import (
    classify_failure,
    compare_channels,
    extract_payment_required,
    validate_accepts,
)
from validator import check_402_body
from unittest import mock


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class MockResponse:
    def __init__(self, status_code, *, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return json.loads(self.text) if self.text else {}


class FixtureCorpusTests(unittest.TestCase):
    def _load(self, name: str) -> dict:
        path = FIXTURE_DIR / f"{name}.json"
        self.assertTrue(path.exists(), f"missing fixture {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _assert_expect(self, name: str) -> None:
        case = self._load(name)
        expect = case["expect"]
        extracted = extract_payment_required(case["status"], case["headers"], case["body"])
        self.assertEqual(extracted.channel, expect["channel"], name)
        self.assertEqual(extracted.legacy_placement, expect["legacy_placement"], name)

        if extracted.canonical is not None:
            source = "header" if extracted.header_obj is not None else "body"
            validated = validate_accepts(extracted.canonical, source=source)
            passed = case["status"] == 402 and validated.ok
        else:
            validated = None
            passed = False

        failure_class = None
        if not passed:
            failure_class = classify_failure(case["status"], case["headers"], case["body"])
            if failure_class is None and validated is not None:
                failure_class = validated.failure_class
            if failure_class is None:
                failure_class = "header_only_accepts"

        self.assertEqual(passed, expect["passed"], f"{name} passed mismatch; fc={failure_class}")
        if expect.get("failure_class") is not None:
            self.assertEqual(failure_class, expect["failure_class"], name)
        else:
            self.assertIsNone(expect["failure_class"])
            self.assertTrue(passed, name)

        if expect.get("channel_mismatch"):
            mismatches = compare_channels(extracted.header_obj, extracted.body_obj)
            self.assertTrue(mismatches, name)

        # End-to-end through check_402_body with mocked transport
        method = (case.get("method") or "GET").upper()

        def fake_get(url, **kwargs):
            if method == "GET" or case["status"] == 402:
                return MockResponse(case["status"], headers=case["headers"], text=case["body"])
            return MockResponse(404, text="")

        def fake_post(url, **kwargs):
            if method == "POST":
                return MockResponse(case["status"], headers=case["headers"], text=case["body"])
            # For GET fixtures, POST should not be required when GET already 402s
            return MockResponse(404, text="")

        with mock.patch("validator.requests.get", side_effect=fake_get), mock.patch(
            "validator.requests.post", side_effect=fake_post
        ):
            result = check_402_body(case.get("url") or "https://example.test/x", probe_method="auto")
        self.assertEqual(result["passed"], expect["passed"], f"{name} e2e {result}")
        self.assertEqual(result["channel"], expect["channel"], name)
        self.assertEqual(result["legacy_placement"], expect["legacy_placement"], name)
        if expect.get("channel_mismatch"):
            self.assertTrue(result["channel_mismatch"], name)

    def test_apinow_buzzwords(self):
        self._assert_expect("apinow_buzzwords")

    def test_web3identity_blockcount(self):
        self._assert_expect("web3identity_blockcount")

    def test_weatherxm_current(self):
        self._assert_expect("weatherxm_current")

    def test_hugen_address(self):
        self._assert_expect("hugen_address")

    def test_stabletravel_airports(self):
        self._assert_expect("stabletravel_airports")

    def test_body_only_v1_legacy(self):
        self._assert_expect("body_only_v1_legacy")

    def test_header_body_mismatch(self):
        self._assert_expect("header_body_mismatch")

    def test_l402_www_authenticate_only(self):
        self._assert_expect("l402_www_authenticate_only")


if __name__ == "__main__":
    unittest.main()
