import pytest
from typing import Any

from x402_conformance_engine import BazaarResult, X402Auditor


VALID_BAZAAR = {
    "method": "POST",
    "serviceName": "test-service",
    "tags": ["x402", "payment"],
}


def make_body(bazaar: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"status": "payment_required"}
    if bazaar is not None:
        body["extensions"] = {"bazaar": bazaar}
    return body


class TestBazaarCheck:
    def test_missing_entire_bazaar_block(self):
        body = make_body(bazaar=None)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "extensions.bazaar" in result.message
        assert result.details["bazaar_present"] is False

    def test_missing_method_field(self):
        bazaar = dict(VALID_BAZAAR)
        del bazaar["method"]
        body = make_body(bazaar)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "method" in result.message
        assert "extensions.bazaar.method" in result.details["missing_fields"]

    def test_method_is_get_instead_of_post(self):
        bazaar = dict(VALID_BAZAAR)
        bazaar["method"] = "GET"
        body = make_body(bazaar)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "GET" in result.message
        assert "POST" in result.message
        assert result.details["bazaar_method"] == "GET"

    def test_missing_service_name(self):
        bazaar = dict(VALID_BAZAAR)
        del bazaar["serviceName"]
        body = make_body(bazaar)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "serviceName" in result.message
        assert "extensions.bazaar.serviceName" in result.details["missing_fields"]

    def test_missing_tags(self):
        bazaar = dict(VALID_BAZAAR)
        del bazaar["tags"]
        body = make_body(bazaar)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "tags" in result.message
        assert "extensions.bazaar.tags" in result.details["missing_fields"]

    def test_tags_is_not_a_list(self):
        bazaar = dict(VALID_BAZAAR)
        bazaar["tags"] = "not-a-list"
        body = make_body(bazaar)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "FAIL"
        assert "tags" in result.message

    def test_all_fields_valid_passes(self):
        body = make_body(VALID_BAZAAR)
        auditor = X402Auditor()
        result = auditor.check_bazaar_compliance(body)
        assert result.status == "PASS"
        assert result.details["bazaar_method"] == "POST"
        assert result.details["bazaar_service_name"] == "test-service"
        assert result.details["bazaar_tags"] == ["x402", "payment"]
        assert result.details["missing_fields"] == []
