"""Regression suite for the false-positive classes introduced by ff4be8a.

Commit ff4be8a ("remove three false-positive classes found by 2026-07-25
hostile audit") shipped with zero tests: the existing suite returned 51
passed / 51 passed on the commit before and after, i.e. it was blind to the
entire change (audit 2026-07-25, RS-8). The commit killed 6 false positives
and created at least two new classes; 11 of the 11 remaining failures in the
three partner reports were false positives.

Every test here pins one of the seven behaviours the audit required to
change. The suite is designed to FAIL on ff4be8a and PASS on 1.3.0 — that is
the property that makes it a regression suite rather than decoration.

Mapping test -> audit finding:
  RS-2   reachability is decided by the method that produced the verdict
  RS-3   documented-free routes are `free_route` (info), not failures
  RS-4   the price rule keys off a namespace REGISTRY, not a merchant string
  RS-5   `auth_gated` needs accepts == [] AND a recognised auth extension
  RS-6   manifest defects are visible in the summary
  RS-7   decide_exit_code agrees with endpoint.passed
  RS-9   validator_version is bumped to 1.3.0
  RS-10  probe_attempts actually reaches the report
  RS-11  full 44-char Solana genesis hashes are valid CAIP-2
  RS-12  prose from documentation is not parsed into endpoints
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import validator
from payment_required import (
    NAMESPACE_REGISTRY,
    SEVERITY_FAIL,
    SEVERITY_INFO,
    SEVERITY_PASS,
    validate_accepts,
)
from validator import (
    check_402_body,
    check_reachability,
    decide_exit_code,
    parse_endpoints,
    validate_endpoint_url,
)

# Real Solana mainnet-beta genesis hash: 44 base58 chars, i.e. longer than the
# 32-char CAIP-2 reference cap ff4be8a introduced.
SOLANA_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"


def _b64_json(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


class MockResponse:
    def __init__(self, status_code, *, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return json.loads(self.text) if self.text else {}


# ---------------------------------------------------------------- RS-2 -----
class ReachabilityUsesDecidingMethodTests(unittest.TestCase):
    """A POST-only route must not be convicted as dead by a GET.

    ff4be8a: `kelam-report.json` recorded, for the same endpoint,
    `reachability: {passed: false, status_code: 404, note: "Dead route"}` and
    `body_conformance: {passed: true, status_code: 402, probe_method: "POST"}`.
    """

    def test_post_402_beats_get_404(self):
        reach = check_reachability(
            "https://call.example.test/api/place_call",
            [
                {"method": "GET", "status_code": 404},
                {"method": "POST", "status_code": 402},
            ],
        )
        self.assertTrue(reach["passed"])
        self.assertEqual(reach["status_code"], 402)
        self.assertEqual(reach["method"], "POST")

    def test_all_methods_404_is_still_dead(self):
        reach = check_reachability(
            "https://example.test/gone",
            [
                {"method": "GET", "status_code": 404},
                {"method": "POST", "status_code": 404},
            ],
        )
        self.assertFalse(reach["passed"])
        self.assertIn("Dead route", reach["note"])

    def test_no_probe_evidence_is_not_reachable(self):
        reach = check_reachability("https://example.test/x", [])
        self.assertFalse(reach["passed"])
        self.assertIsNone(reach["status_code"])

    def test_endpoint_record_is_self_consistent(self):
        """The whole-endpoint record must not contradict itself."""
        payment_required = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "10000",
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    "payTo": "0x1111111111111111111111111111111111111111",
                    "maxTimeoutSeconds": 60,
                }
            ],
            "error": "payment required",
        }
        with mock.patch(
            "validator.requests.get", return_value=MockResponse(404)
        ), mock.patch(
            "validator.requests.post",
            return_value=MockResponse(
                402,
                headers={"PAYMENT-REQUIRED": _b64_json(payment_required)},
                text=json.dumps(payment_required),
            ),
        ), mock.patch(
            "validator._check_manifest_cached",
            return_value={"passed": True, "manifest_url": "m", "note": "ok"},
        ), mock.patch(
            "validator.check_p95",
            return_value={"passed": True, "p95_ms": 1, "samples_ms": [1], "note": "ok"},
        ):
            result = validator.validate_endpoint("https://call.example.test/api/place_call", 1000)

        reach = result["checks"]["reachability"]
        body = result["checks"]["body_conformance"]
        self.assertTrue(body["passed"], "POST probe should see the 402")
        self.assertTrue(reach["passed"], "route answered 402 via POST; it is not dead")
        self.assertTrue(result["passed"])


# ---------------------------------------------------------------- RS-3 -----
class DocumentedFreeRouteTests(unittest.TestCase):
    """Routes the provider's own OpenAPI declares `200`-only are not defects.

    ff4be8a reported 5 hyperextend routes as failures; the provider's OpenAPI
    declares all five as `responses: ["200"]`. Sending that accuses them of
    breaking a contract they never made.
    """

    def test_free_route_200_is_info_not_failure(self):
        with mock.patch("validator.requests.get", return_value=MockResponse(200, text="{}")):
            body = check_402_body("https://api.example.test/v1/dexes", probe_method="GET", expect="free")
        self.assertEqual(body["severity"], SEVERITY_INFO)
        self.assertEqual(body["failure_class"], "free_route")
        self.assertFalse(body["passed"])

    def test_free_route_does_not_fail_the_endpoint(self):
        with mock.patch(
            "validator.requests.get", return_value=MockResponse(200, text="{}")
        ), mock.patch(
            "validator._check_manifest_cached",
            return_value={"passed": True, "manifest_url": "m", "note": "ok"},
        ), mock.patch(
            "validator.check_p95",
            return_value={"passed": True, "p95_ms": 1, "samples_ms": [1], "note": "ok"},
        ):
            result = validator.validate_endpoint(
                "https://api.example.test/v1/dexes", 1000, probe_method="GET", expect="free"
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["severity"], SEVERITY_INFO)
        self.assertEqual(result["failure_class"], "free_route")

    def test_undeclared_route_without_402_still_fails(self):
        """The free_route escape hatch must require a declaration."""
        with mock.patch("validator.requests.get", return_value=MockResponse(200, text="{}")):
            body = check_402_body("https://api.example.test/v1/dexes", probe_method="GET")
        self.assertEqual(body["severity"], SEVERITY_FAIL)
        self.assertEqual(body["failure_class"], "undecided")


# ---------------------------------------------------------------- RS-4 -----
class AmountRuleUsesNamespaceRegistryTests(unittest.TestCase):
    """The price rule must not be switchable by a string the merchant controls.

    ff4be8a gated the amount check on `network.startswith(("eip155:", "solana:"))`.
    Reproduced on that commit: `network: "foo:bar"`, `amount: "not-a-number"`
    returned ok=True, failure_class=None.
    """

    def _pr(self, network: str, amount) -> dict:
        return {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": network,
                    "amount": amount,
                    "asset": "USDC",
                    "payTo": "0x1111111111111111111111111111111111111111",
                }
            ],
            "error": "payment required",
        }

    def test_unknown_namespace_is_not_a_pass(self):
        result = validate_accepts(self._pr("foo:bar", "not-a-number"), source="header")
        self.assertFalse(result.ok, "unknown namespace must not launder a bad amount into a pass")
        self.assertEqual(result.severity, SEVERITY_INFO)
        self.assertEqual(result.failure_class, "unknown_network")

    def test_registered_namespace_still_convicts_bad_amount(self):
        result = validate_accepts(self._pr("eip155:8453", "not-a-number"), source="header")
        self.assertFalse(result.ok)
        self.assertEqual(result.severity, SEVERITY_FAIL)
        self.assertEqual(result.failure_class, "amount_key")

    def test_unknown_namespace_with_valid_amount_passes(self):
        """Unverifiable != guilty: a well-formed atomic amount is still fine."""
        result = validate_accepts(self._pr("foo:bar", "2500"), source="header")
        self.assertTrue(result.ok)
        self.assertEqual(result.severity, SEVERITY_PASS)

    def test_registry_contents_are_explicit(self):
        self.assertIn("eip155", NAMESPACE_REGISTRY)
        self.assertIn("solana", NAMESPACE_REGISTRY)


# ---------------------------------------------------------------- RS-5 -----
class AuthGatedRequiresRecognisedExtensionTests(unittest.TestCase):
    """`auth_gated` was a substring sniff that returned ok=True.

    Reproduced on ff4be8a: error "payment authorization failed" -> ok=True,
    "author unknown" -> ok=True, "LOGIN" -> ok=True.
    """

    def _empty_accepts(self, **extra) -> dict:
        return {"x402Version": 2, "accepts": [], **extra}

    def test_payment_authorization_failed_is_not_an_auth_wall(self):
        result = validate_accepts(
            self._empty_accepts(error="payment authorization failed"), source="header"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.severity, SEVERITY_FAIL)
        self.assertNotEqual(result.failure_class, "auth_gated")

    def test_author_unknown_is_not_an_auth_wall(self):
        result = validate_accepts(self._empty_accepts(error="author unknown"), source="header")
        self.assertFalse(result.ok)
        self.assertEqual(result.severity, SEVERITY_FAIL)

    def test_bare_login_word_is_not_an_auth_wall(self):
        result = validate_accepts(self._empty_accepts(error="LOGIN"), source="header")
        self.assertFalse(result.ok)
        self.assertEqual(result.severity, SEVERITY_FAIL)

    def test_recognised_extension_is_an_auth_wall_and_is_info_not_pass(self):
        result = validate_accepts(
            self._empty_accepts(
                error="SIWX authentication required",
                extensions={"sign-in-with-x": {"info": {"domain": "example.test"}}},
            ),
            source="header",
        )
        self.assertEqual(result.failure_class, "auth_gated")
        self.assertEqual(result.severity, SEVERITY_INFO)
        self.assertFalse(result.ok, "an auth wall is out of scope, not a conformance pass")

    def test_auth_extension_requires_empty_accepts(self):
        """A real payment offer is judged on its merits, extension or not."""
        result = validate_accepts(
            {
                "x402Version": 2,
                "accepts": [{"scheme": "exact", "network": "eip155:8453"}],
                "extensions": {"sign-in-with-x": {}},
            },
            source="header",
        )
        self.assertNotEqual(result.failure_class, "auth_gated")


# ------------------------------------------------------------ RS-6/RS-7 ----
class ManifestDefectVisibilityTests(unittest.TestCase):
    """A manifest defect was removed from `passed` and from the summary, yet
    still flipped the exit code under `fail-on: critical` — two contradictory
    definitions of failure in one binary."""

    def _report(self, *, manifest_ok: bool, body_severity: str, passed: bool) -> dict:
        return {
            "summary": {
                "all_passed": passed,
                "manifest_defect_hosts": [] if manifest_ok else ["https://h.test/.well-known/x402"],
                "manifest_defects": 0 if manifest_ok else 1,
            },
            "endpoints": [
                {
                    "url": "https://h.test/a",
                    "passed": passed,
                    "manifest_defect": not manifest_ok,
                    "checks": {
                        "manifest": {"passed": manifest_ok, "manifest_url": "https://h.test/.well-known/x402"},
                        "body_conformance": {"passed": passed, "severity": body_severity},
                    },
                }
            ],
        }

    def test_critical_ignores_manifest_when_endpoint_passed(self):
        report = self._report(manifest_ok=False, body_severity=SEVERITY_PASS, passed=True)
        self.assertEqual(decide_exit_code(report, "critical"), 0)

    def test_critical_fails_on_real_conformance_defect(self):
        report = self._report(manifest_ok=True, body_severity=SEVERITY_FAIL, passed=False)
        self.assertEqual(decide_exit_code(report, "critical"), 1)

    def test_manifest_mode_is_opt_in_and_works(self):
        report = self._report(manifest_ok=False, body_severity=SEVERITY_PASS, passed=True)
        self.assertEqual(decide_exit_code(report, "manifest"), 1)

    def test_summary_carries_manifest_defect_hosts(self):
        payment_required = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "10000",
                    "asset": "USDC",
                    "payTo": "0x1111111111111111111111111111111111111111",
                    "maxTimeoutSeconds": 60,
                }
            ],
            "error": "payment required",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            env = {
                "X402V_ENDPOINTS": "https://h.test/a",
                "X402V_REPORT_PATH": report_path,
                "X402V_PROBE_METHOD": "GET",
            }
            with mock.patch.dict(os.environ, env, clear=True), mock.patch(
                "validator.requests.get",
                return_value=MockResponse(
                    402,
                    headers={"PAYMENT-REQUIRED": _b64_json(payment_required)},
                    text=json.dumps(payment_required),
                ),
            ), mock.patch(
                "validator.check_manifest",
                return_value={
                    "passed": False,
                    "manifest_url": "https://h.test/.well-known/x402",
                    "status_code": 404,
                    "note": "manifest not reachable (expected 200)",
                },
            ), mock.patch(
                "validator.check_p95",
                return_value={"passed": True, "p95_ms": 1, "samples_ms": [1], "errors": 0, "note": "ok"},
            ):
                validator._MANIFEST_CACHE.clear()
                exit_code = validator.main()
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0, "a host-level manifest defect is not an endpoint failure")
        self.assertEqual(report["summary"]["manifest_defects"], 1)
        self.assertEqual(
            report["summary"]["manifest_defect_hosts"],
            ["https://h.test/.well-known/x402"],
        )


# ---------------------------------------------------------- RS-9/RS-10 -----
class VersionAndEvidenceTests(unittest.TestCase):
    def test_validator_version_is_bumped(self):
        """1.2.0 shipped two engines with opposite verdicts on the same URLs.

        The guarantee is "past 1.2.0", not a pin on one release: pinning the
        exact string turned this into a tripwire that every bump has to edit,
        which is how a version assert stops testing anything.
        """
        parts = tuple(int(p) for p in validator.VALIDATOR_VERSION.split("."))
        self.assertGreater(parts, (1, 2, 0), validator.VALIDATOR_VERSION)

    def test_probe_attempts_reaches_the_report(self):
        """0 of 81 endpoint records carried this advertised evidence field."""
        with mock.patch(
            "validator.requests.get", return_value=MockResponse(404)
        ), mock.patch("validator.requests.post", return_value=MockResponse(404)):
            body = check_402_body("https://example.test/x")
        self.assertEqual(
            body["probe_attempts"],
            [{"method": "GET", "status_code": 404}, {"method": "POST", "status_code": 404}],
        )


# --------------------------------------------------------------- RS-11 -----
class Caip2SolanaGenesisHashTests(unittest.TestCase):
    """The new CAIP-2 grammar silently rejected 44-char Solana genesis hashes."""

    def _pr(self, network: str) -> dict:
        return {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": network,
                    "amount": "2500",
                    "asset": "USDC",
                    "payTo": "So11111111111111111111111111111111111111112",
                }
            ],
            "error": "payment required",
        }

    def test_full_44_char_genesis_hash_is_valid(self):
        self.assertEqual(len(SOLANA_GENESIS), 44)
        result = validate_accepts(self._pr(f"solana:{SOLANA_GENESIS}"), source="header")
        self.assertTrue(result.ok)
        self.assertEqual(result.severity, SEVERITY_PASS)

    def test_truncated_32_char_reference_still_valid(self):
        result = validate_accepts(self._pr(f"solana:{SOLANA_GENESIS[:32]}"), source="header")
        self.assertTrue(result.ok)

    def test_cluster_alias_still_valid(self):
        result = validate_accepts(self._pr("solana:mainnet"), source="header")
        self.assertTrue(result.ok)

    def test_eip155_still_requires_decimal_reference(self):
        result = validate_accepts(self._pr("eip155:mainnet"), source="header")
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_class, "network_format")


# --------------------------------------------------------------- RS-12 -----
class EndpointParserRejectsProseTests(unittest.TestCase):
    """The only finding against lauhal was a sentence from its own docs.

    `https://api.x-402.online/v1/llm {"prompt":"..."} - $0.002, or GET
    /v1/weather?city=Paris - $0.003` was scanned as an endpoint URL.
    """

    PROSE = (
        'https://api.x-402.online/v1/llm {"prompt":"..."} — $0.002, '
        "or GET /v1/weather?city=Paris — $0.003"
    )

    def test_prose_entry_is_rejected_not_scanned(self):
        specs, rejected = parse_endpoints(
            json.dumps(["https://api.x-402.online/v1/llm", self.PROSE]), "/tmp"
        )
        self.assertEqual([s["url"] for s in specs], ["https://api.x-402.online/v1/llm"])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["entry"], self.PROSE)

    def test_bare_string_input_splits_on_lines_not_whitespace(self):
        specs, rejected = parse_endpoints(self.PROSE, "/tmp")
        self.assertEqual(specs, [], "a docs sentence must not become endpoints")
        self.assertEqual(len(rejected), 1)

    def test_validate_endpoint_url_accepts_real_urls(self):
        for url in (
            "https://api.x-402.online/v1/llm",
            "http://localhost:8080/paywalled",
            "https://api.hyperextend.xyz/v1/trades/coverage?coin=ETH",
        ):
            self.assertIsNone(validate_endpoint_url(url), url)

    def test_per_endpoint_probe_method_and_expect_survive_parsing(self):
        specs, rejected = parse_endpoints(
            json.dumps(
                [
                    {"url": "https://call.example.test/api/place_call", "probe_method": "POST"},
                    {"url": "https://api.example.test/v1/dexes", "expect": "free"},
                ]
            ),
            "/tmp",
        )
        self.assertEqual(rejected, [])
        self.assertEqual(specs[0]["probe_method"], "POST")
        self.assertEqual(specs[1]["expect"], "free")


if __name__ == "__main__":
    unittest.main()
