"""Build actionable, human-readable messages for each check result.

The goal of these helpers is for every FAIL/ERROR message to tell the
endpoint operator exactly what is wrong AND what they should do about it.

Examples:
    FAIL:  "Manifest endpoint returned HTTP 404. Expected /.well-known/x402 to
           return a JSON object with an 'accepts' key. See
           https://github.com/MSSATANASS/x402-validator-tools for a fixture."
    ERROR: "Connection refused. The endpoint is unreachable. Verify the URL
           is live and accepts unauthenticated GET on the manifest path."

These are deterministic text builders (no I/O). Each returns a string; some
also bundle suggested remediation notes in a list (used in JSON output).
"""

from __future__ import annotations

from typing import Any, Iterable


# === Manifest ============================================================


# Standard x402 discovery path — override-able in ``_engine.constants`` if the
# spec ever changes. Kept here too so messages can reference it without
# importing from constants (circular-import safe).
MANIFEST_PATH: str = "/.well-known/x402"


def manifest_missing(url: str) -> str:
    return (
        f"Manifest endpoint not found at {url}. The x402 spec requires a JSON "
        f"manifest at {MANIFEST_PATH} with either an 'accepts' key (resource "
        f"pricing) or a 'products' array (marketplace catalog). "
        f"Add the file to your origin."
    )


def manifest_non_json(url: str, status: int) -> str:
    return (
        f"Manifest at {url} returned HTTP {status} but the body is not valid "
        f"JSON. The manifest must parse as JSON. "
        f"Fix: serve application/json with a valid object body."
    )


def manifest_missing_accepts(url: str, hints: dict[str, Any]) -> str:
    return (
        f"Manifest at {url} is valid JSON but lacks the required 'accepts' "
        f"key (per-resource pricing) and the optional 'products' array "
        f"(marketplace catalog). "
        f"Fix: include either 'accepts' (with scheme/network/amount) or "
        f"'products' (each with id/endpoint/x402). "
        f"Got keys: {sorted(list(hints.keys()))[:6]}."
    )


def manifest_ok(accepts: bool, products: int, url: str) -> str:
    if accepts:
        return f"Manifest at {url} is valid and contains 'accepts'."
    return f"Manifest at {url} is a marketplace catalog with {products} product(s)."


def manifest_error(url: str, why: str) -> str:
    return f"Could not reach manifest at {url}: {why}. Verify the URL is live."


# === CAIP-2 ==============================================================


def caip2_missing() -> str:
    return (
        "No CAIP-2 network identifier found in any payment header. "
        "Headers probed: payment-required, x-402-accepts, www-authenticate. "
        "Fix: encode base64(json) of the PaymentRequired payload into one of "
        "these headers with a 'network' field in CAIP-2 form (e.g., "
        "'eip155:8453' for Base mainnet)."
    )


def caip2_invalid(header: str, value: str) -> str:
    return (
        f"Header {header} carries network '{value}' which is not a valid "
        f"CAIP-2 identifier. CAIP-2 syntax is '<namespace>:<reference>' with "
        f"lowercase namespace (e.g., 'eip155:8453' or 'solana:mainnet'). "
        f"Found an invalid value: '{value}'."
    )


def caip2_ok(header: str, value: str) -> str:
    return f"CAIP-2 network '{value}' validated in header '{header}'."


# === JSON resilience =====================================================


def json_primitive_error(payload_type: str, sample: str) -> str:
    return (
        f"HTTP 402 returned a JSON primitive ({payload_type}) instead of a "
        f"JSON object. The reference verifier requires an object body. "
        f"Sample: '{sample}'. "
        f"Fix: wrap your payment terms in an object (e.g., "
        f"'{{\"accepts\": [...]}}' or '{{\"x402Version\": 2, "
        f"\"accepts\": [...]}}')."
    )


def json_invalid_body() -> str:
    return (
        "HTTP 402 response body is not valid JSON. The x402 spec requires a "
        "JSON object body. Fix: ensure Content-Type is application/json and "
        "the body parses as JSON."
    )


def json_ok() -> str:
    return "HTTP 402 response body is a valid JSON object."


def json_not_applicable(status: int) -> str:
    return (
        f"Endpoint returned HTTP {status} (not 402). JSON resilience check "
        f"is not applicable; skipped. PASS."
    )


# === Bazaar ==============================================================


def bazaar_missing_block() -> str:
    return (
        "extensions.bazaar block is required but missing from the HTTP 402 "
        "response body. Fix: include 'extensions.bazaar' at the top level "
        "of the body with three fields: 'method' (must be 'POST'), "
        "'serviceName' (string), 'tags' (non-empty array of strings)."
    )


def bazaar_missing_fields(missing: Iterable[str]) -> str:
    items = ", ".join(missing)
    return (
        f"extensions.bazaar is present but missing required field(s): "
        f"{items}. Fix: add the listed fields; 'method' must equal 'POST', "
        f"'serviceName' must be a non-empty string, 'tags' must be a "
        f"non-empty array of strings."
    )


def bazaar_wrong_method(actual: str) -> str:
    return (
        f"extensions.bazaar.method is '{actual}' but the x402 spec requires "
        f"'POST'. Fix: set method: 'POST'."
    )


def bazaar_ok() -> str:
    return "extensions.bazaar is present and validates (method=POST, serviceName set, tags non-empty)."


def bazaar_skipped() -> str:
    return (
        "No HTTP 402 body available; bazaar compliance check skipped. "
        "PASS (not applicable)."
    )


# === Marketplace / product ==============================================


def marketplace_summary(conformant: int, total: int) -> str:
    if total == 0:
        return "Manifest contains no 'products' array; marketplace mode cannot evaluate."
    if conformant == total:
        return f"All {total} products conformant."
    return (
        f"{conformant}/{total} products conformant. "
        f"See product details for required fixes (scheme/network/pay_to/facilitator_url)."
    )


def product_free_pass(name: str) -> str:
    return f"Free product '{name}' resolved to HTTP 200 as expected."


def product_free_fail(name: str, status: int) -> str:
    return (
        f"Free product '{name}' returned HTTP {status} but should return 200. "
        f"Free products bypass x402 — verify the route is reachable."
    )


def product_paid_ok_no_header(name: str) -> str:
    return (
        f"Paid product '{name}' returned HTTP 402 but the Payment-Required "
        f"header is absent. Add base64(json) PaymentRequired to header "
        f"'X-Payment-Required' (or 'Payment-Required') for v2 compliance."
    )


def product_paid_ok_with_header(name: str) -> str:
    return (
        f"Paid product '{name}' returned HTTP 402 with Payment-Required "
        f"header. v2 channel detected."
    )


def product_paid_wrong(name: str, status: int) -> str:
    return (
        f"Paid product '{name}' returned HTTP {status} but should return "
        f"402 (Payment Required). Check that x402 middleware intercepts "
        f"unauthenticated requests before they reach the handler."
    )


def product_endpoint_no_endpoint(pid: str) -> str:
    return f"Product '{pid}' has no 'endpoint' field; cannot probe."


def product_timeout(name: str) -> str:
    return f"Product '{name}' timed out before HTTP response."


def product_connect_error(name: str, error: str) -> str:
    return f"Product '{name}' connection error: {error}"


def product_unexpected(name: str, status: int) -> str:
    return (
        f"Product '{name}' returned unexpected HTTP {status}. Expected 200 "
        f"(free) or 402 (paid)."
    )


# === Network errors ======================================================


def network_timeout() -> str:
    return "Request timed out. Default timeout is 10s; pass --timeout to raise."


def network_connect(error: str) -> str:
    return f"Connection error: {error}. Verify the endpoint is reachable."


def network_unexpected(error: str) -> str:
    return f"Unexpected error: {error}."
