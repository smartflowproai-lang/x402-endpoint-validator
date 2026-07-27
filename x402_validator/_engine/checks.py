"""Single-responsibility x402 conformance checks.

Every check function takes a httpx client + URL and returns one of the typed
result models from ``_engine.models``. Each function:

    - Performs exactly ONE conceptual check.
    - Never raises (network/HTTP errors become ``status=ERROR``).
    - Builds human messages via ``_engine.messages``.

The ``X402Auditor`` (see ``_engine.auditor``) is the public orchestrator.
This module is the lower layer: stateless, framework-agnostic.

Adding a new check:
    1. Define a CheckResult subclass in ``_engine.models``.
    2. Add a check function here that returns it.
    3. Wire it into ``X402Auditor.run_full_audit``.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Mapping

import httpx

from x402_validator._engine import messages as msg
from x402_validator._engine.constants import (
    CAIP2_PATTERN,
    MANIFEST_PATH_SUFFIX,
    PAYMENT_HEADERS,
)
from x402_validator._engine.models import (
    BazaarResult,
    Caip2Result,
    CheckResult,
    JsonResilienceResult,
    ManifestResult,
    MarketplaceResult,
    ProductResult,
)


# ---------------------------------------------------------------------------
# Network helpers (private)
# ---------------------------------------------------------------------------


async def _safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """GET ``url`` and return the Response, or None if any network/HTTP error.

    Avoids raising so callers can return ``status=ERROR`` results instead.
    """
    try:
        return await client.get(url)
    except httpx.TimeoutException:
        return None
    except httpx.ConnectError:
        return None
    except httpx.HTTPError:
        return None
    except Exception:
        return None


def _b64_to_obj(token: str) -> dict[str, Any] | None:
    """Decode base64(JSON) into a dict; return None on any failure.

    Tolerates missing padding, urlsafe encoding, and JSON parse errors so the
    caller can simply skip malformed headers.
    """
    try:
        padded = token + ("=" * (-len(token) % 4))
        try:
            decoded = base64.b64decode(padded, validate=False)
        except Exception:
            decoded = base64.urlsafe_b64decode(padded)
        obj = json.loads(decoded.decode("utf-8"))
        if not isinstance(obj, dict):
            return None
        return obj
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Manifest discovery
# ---------------------------------------------------------------------------


async def check_manifest(
    client: httpx.AsyncClient, base_url: str
) -> ManifestResult:
    """GET ``{base_url}/.well-known/x402``; require ``accepts`` or ``products``.

    PASS — JSON object with ``accepts`` OR non-empty ``products`` array.
    FAIL — non-200, non-JSON, missing both keys, etc.
    ERROR — network/transport failure.
    """
    url = base_url.rstrip("/") + MANIFEST_PATH_SUFFIX

    try:
        response = await client.get(url)
    except httpx.TimeoutException:
        return ManifestResult(
            status="ERROR",
            message=msg.manifest_error(url, "timeout"),
            details={"url": url, "status_code": None, "error": "timeout"},
        )
    except httpx.ConnectError as e:
        return ManifestResult(
            status="ERROR",
            message=msg.manifest_error(url, f"connection: {e}"),
            details={"url": url, "status_code": None, "error": str(e)},
        )
    except Exception as e:
        return ManifestResult(
            status="ERROR",
            message=msg.manifest_error(url, str(e)),
            details={"url": url, "status_code": None, "error": str(e)},
        )

    status_code = response.status_code

    if status_code != 200:
        return ManifestResult(
            status="FAIL",
            message=msg.manifest_missing(url),
            details={
                "url": url,
                "status_code": status_code,
                "has_accepts": False,
                "has_products": False,
                "headers": dict(response.headers),
            },
        )

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return ManifestResult(
            status="FAIL",
            message=msg.manifest_non_json(url, status_code),
            details={
                "url": url,
                "status_code": status_code,
                "has_accepts": False,
                "has_products": False,
                "headers": dict(response.headers),
            },
        )

    if not isinstance(payload, dict):
        return ManifestResult(
            status="FAIL",
            message=msg.manifest_non_json(url, status_code),
            details={
                "url": url,
                "status_code": status_code,
                "has_accepts": False,
                "has_products": False,
                "payload_type": type(payload).__name__,
            },
        )

    has_accepts = "accepts" in payload and isinstance(payload["accepts"], list)
    products = payload.get("products") if isinstance(payload.get("products"), list) else []
    has_products = len(products) > 0

    if has_accepts or has_products:
        return ManifestResult(
            status="PASS",
            message=msg.manifest_ok(has_accepts, len(products), url),
            details={
                "url": url,
                "status_code": status_code,
                "has_accepts": has_accepts,
                "has_products": has_products,
                "product_count": len(products) if has_products else 0,
                "headers": dict(response.headers),
            },
        )

    return ManifestResult(
        status="FAIL",
        message=msg.manifest_missing_accepts(url, payload),
        details={
            "url": url,
            "status_code": status_code,
            "has_accepts": False,
            "has_products": False,
            "headers": dict(response.headers),
            "received_keys": sorted(list(payload.keys())),
        },
    )


# ---------------------------------------------------------------------------
# CAIP-2 compliance
# ---------------------------------------------------------------------------


def _header_display_name(name: str) -> str:
    if name == "www-authenticate":
        return "WWW-Authenticate"
    if name == "x-payment-required":
        return "X-Payment-Required"
    return name  # already-canonical like "payment-required"


async def check_caip2(
    client: httpx.AsyncClient, target_url: str
) -> Caip2Result:
    """Probe payment headers on the target URL; verify a valid CAIP-2 network.

    Priority order: ``payment-required``, ``x-payment-required``,
    ``x-402-accepts``, ``www-authenticate``. Each is expected to be
    base64(JSON) containing a ``network`` field in CAIP-2 form.

    PASS — at least one header carries a valid CAIP-2 network.
    FAIL — none found or all malformed.
    """
    response = await _safe_get(client, target_url)
    headers: Mapping[str, str] = response.headers if response is not None else {}

    headers_lower = {k.lower(): v for k, v in headers.items()}

    for header_name in PAYMENT_HEADERS:
        raw = headers_lower.get(header_name)
        if not raw:
            continue

        encoded = raw
        if header_name == "www-authenticate":
            prefix = "x402 "
            lower_raw = raw.lower()
            if not lower_raw.startswith(prefix):
                continue
            encoded = raw[len(prefix):].strip()

        obj = _b64_to_obj(encoded)
        if obj is None:
            continue

        network = obj.get("network") or obj.get("chainId")
        if not network:
            continue

        network_str = str(network)
        if CAIP2_PATTERN.match(network_str):
            display = _header_display_name(header_name)
            return Caip2Result(
                status="PASS",
                message=msg.caip2_ok(display, network_str),
                details={
                    "header_present": True,
                    "header_name": display,
                    "caip2_value": network_str,
                    "valid": True,
                },
            )
        else:
            display = _header_display_name(header_name)
            return Caip2Result(
                status="FAIL",
                message=msg.caip2_invalid(display, network_str),
                details={
                    "header_present": True,
                    "header_name": display,
                    "caip2_value": network_str,
                    "valid": False,
                },
            )

    return Caip2Result(
        status="FAIL",
        message=msg.caip2_missing(),
        details={
            "header_present": False,
            "header_name": None,
            "caip2_value": None,
            "valid": False,
        },
    )


# ---------------------------------------------------------------------------
# JSON resilience
# ---------------------------------------------------------------------------


async def check_json_resilience(
    client: httpx.AsyncClient, endpoint_url: str
) -> JsonResilienceResult:
    """Verify that any HTTP 402 response has a JSON object body.

    PASS — endpoint not 402 OR 402 body is a JSON object.
    CRITICAL_FAIL — 402 body is a JSON primitive (string/number/array/null)
                    or non-JSON. This crashes the reference verifier.
    ERROR — network failure.
    """
    try:
        response = await client.get(endpoint_url)
    except httpx.TimeoutException:
        return JsonResilienceResult(
            status="ERROR",
            message=msg.network_timeout(),
            details={"status_code": None, "payload_type": None, "is_dict": None},
        )
    except httpx.ConnectError as e:
        return JsonResilienceResult(
            status="ERROR",
            message=msg.network_connect(str(e)),
            details={"status_code": None, "payload_type": None, "is_dict": None},
        )
    except Exception as e:
        return JsonResilienceResult(
            status="ERROR",
            message=msg.network_unexpected(str(e)),
            details={"status_code": None, "payload_type": None, "is_dict": None},
        )

    status_code = response.status_code

    if status_code != 402:
        return JsonResilienceResult(
            status="PASS",
            message=msg.json_not_applicable(status_code),
            details={
                "status_code": status_code,
                "payload_type": None,
                "is_dict": None,
            },
        )

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return JsonResilienceResult(
            status="CRITICAL_FAIL",
            message=msg.json_invalid_body(),
            details={
                "status_code": 402,
                "payload_type": "invalid_json",
                "is_dict": False,
            },
        )

    payload_type = type(payload).__name__
    is_dict = type(payload) is dict

    if is_dict:
        return JsonResilienceResult(
            status="PASS",
            message=msg.json_ok(),
            details={
                "status_code": 402,
                "payload_type": payload_type,
                "is_dict": True,
            },
        )

    sample = str(payload)[:100] if payload is not None else "null"
    return JsonResilienceResult(
        status="CRITICAL_FAIL",
        message=msg.json_primitive_error(payload_type, sample),
        details={
            "status_code": 402,
            "payload_type": payload_type,
            "is_dict": False,
            "sample": sample,
        },
    )


# ---------------------------------------------------------------------------
# Bazaar compliance
# ---------------------------------------------------------------------------


def check_bazaar(response_body: dict[str, Any] | None) -> BazaarResult:
    """Validate ``extensions.bazaar`` block shape on a 402 body.

    PASS — required fields present and valid.
    FAIL — block missing or any required field missing/invalid.
    SKIP — body is None (returns PASS with skipped message).

    Required fields:
        extensions.bazaar.method      — must equal ``"POST"``
        extensions.bazaar.serviceName — non-empty string
        extensions.bazaar.tags        — non-empty list of strings
    """
    if response_body is None:
        return BazaarResult(
            status="PASS",
            message=msg.bazaar_skipped(),
            details={
                "bazaar_present": False,
                "bazaar_method": None,
                "bazaar_service_name": None,
                "bazaar_tags": None,
                "missing_fields": [],
            },
        )

    if not isinstance(response_body, dict):
        return BazaarResult(
            status="FAIL",
            message=msg.bazaar_missing_block(),
            details={
                "bazaar_present": False,
                "bazaar_method": None,
                "bazaar_service_name": None,
                "bazaar_tags": None,
                "missing_fields": ["extensions.bazaar"],
            },
        )

    extensions = response_body.get("extensions", {})
    bazaar = extensions.get("bazaar") if isinstance(extensions, dict) else None

    if bazaar is None:
        return BazaarResult(
            status="FAIL",
            message=msg.bazaar_missing_block(),
            details={
                "bazaar_present": False,
                "bazaar_method": None,
                "bazaar_service_name": None,
                "bazaar_tags": None,
                "missing_fields": ["extensions.bazaar"],
            },
        )

    bazaar_method = bazaar.get("method")
    bazaar_service_name = bazaar.get("serviceName")
    bazaar_tags = bazaar.get("tags")
    missing: list[str] = []

    if bazaar_method is None:
        missing.append("extensions.bazaar.method")
    elif bazaar_method != "POST":
        return BazaarResult(
            status="FAIL",
            message=msg.bazaar_wrong_method(str(bazaar_method)),
            details={
                "bazaar_present": True,
                "bazaar_method": bazaar_method,
                "bazaar_service_name": bazaar_service_name,
                "bazaar_tags": bazaar_tags,
                "missing_fields": [],
            },
        )

    if not isinstance(bazaar_service_name, str) or bazaar_service_name.strip() == "":
        missing.append("extensions.bazaar.serviceName")

    if not isinstance(bazaar_tags, list) or len(bazaar_tags) == 0:
        missing.append("extensions.bazaar.tags")

    if missing:
        return BazaarResult(
            status="FAIL",
            message=msg.bazaar_missing_fields(missing),
            details={
                "bazaar_present": True,
                "bazaar_method": bazaar_method,
                "bazaar_service_name": bazaar_service_name,
                "bazaar_tags": bazaar_tags,
                "missing_fields": missing,
            },
        )

    return BazaarResult(
        status="PASS",
        message=msg.bazaar_ok(),
        details={
            "bazaar_present": True,
            "bazaar_method": bazaar_method,
            "bazaar_service_name": bazaar_service_name,
            "bazaar_tags": bazaar_tags,
            "missing_fields": [],
        },
    )


async def check_bazaar_for_url(
    client: httpx.AsyncClient, target_url: str
) -> BazaarResult:
    """Convenience wrapper: GET the target URL, extract 402 body, run ``check_bazaar``."""
    body = await _get_402_body(client, target_url)
    return check_bazaar(body)


async def _get_402_body(
    client: httpx.AsyncClient, target_url: str
) -> dict[str, Any] | None:
    """GET the target; return its 402 body if a dict, else None."""
    try:
        full_url = target_url.rstrip("/") + "/"
        response = await client.get(full_url)
        if response.status_code != 402:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Marketplace catalog
# ---------------------------------------------------------------------------


async def check_marketplace(
    client: httpx.AsyncClient, base_url: str, manifest_payload: dict[str, Any]
) -> MarketplaceResult:
    """Validate each product in ``manifest['products']`` conforms to x402.

    Per product requirement (each x402 block):
        - scheme == "exact"
        - network matches CAIP-2 pattern
        - pay_to (or payTo) is set
        - facilitator_url is set
        - method == "GET" if specified
    """
    products = manifest_payload.get("products", [])
    if not isinstance(products, list) or not products:
        return MarketplaceResult(
            status="FAIL",
            message=msg.marketplace_summary(0, 0),
            total_products=0,
            conformant_count=0,
            details={"product_count": 0, "conformant": 0, "product_details": []},
        )

    product_details: list[dict[str, Any]] = []
    conformant = 0

    for i, product in enumerate(products):
        if not isinstance(product, dict):
            product_details.append(
                {
                    "product_id": f"index_{i}",
                    "name": f"index_{i}",
                    "endpoint": "",
                    "status": "non_conformant",
                    "errors": ["product entry is not an object"],
                    "x402": None,
                }
            )
            continue

        pid = str(product.get("id", f"product_{i}"))
        name = str(product.get("name", pid))
        x402_block = product.get("x402")
        errors: list[str] = []

        if x402_block is None:
            errors.append("missing x402 block")
        elif isinstance(x402_block, dict):
            scheme = x402_block.get("scheme")
            network = x402_block.get("network")
            pay_to = x402_block.get("pay_to") or x402_block.get("payTo")
            facilitator = x402_block.get("facilitator_url")

            if scheme != "exact":
                errors.append(f"scheme should be 'exact', got '{scheme}'")
            if not network or not CAIP2_PATTERN.match(str(network)):
                errors.append(f"invalid CAIP-2 network: {network!r}")
            if not pay_to:
                errors.append("missing pay_to address")
            if not facilitator:
                errors.append("missing facilitator_url")
        else:
            errors.append("x402 block is not an object")

        if product.get("method") and product["method"] != "GET":
            errors.append(f"method should be GET, got {product['method']!r}")

        if not errors:
            conformant += 1

        product_details.append(
            {
                "product_id": pid,
                "name": name,
                "endpoint": str(product.get("endpoint", "")),
                "status": "conformant" if not errors else "non_conformant",
                "errors": errors,
                "x402": x402_block,
            }
        )

    total = len(products)
    return MarketplaceResult(
        status="PASS" if conformant == total else "FAIL",
        message=msg.marketplace_summary(conformant, total),
        total_products=total,
        conformant_count=conformant,
        details={
            "product_count": total,
            "conformant": conformant,
            "product_details": product_details,
        },
    )


# ---------------------------------------------------------------------------
# Per-product endpoint walk
# ---------------------------------------------------------------------------


async def check_product_endpoint(
    client: httpx.AsyncClient,
    base_url: str,
    product: dict[str, Any],
) -> ProductResult:
    """GET ``{base_url}{product['endpoint']}`` and validate the response.

    Free products (no x402 block) should return HTTP 200.
    Paid products (with x402 block) should return HTTP 402 with a
    Payment-Required header.
    """
    pid = str(product.get("id", "unknown"))
    name = str(product.get("name", pid))
    endpoint = str(product.get("endpoint", "") or "")
    x402_block = product.get("x402")
    is_free = x402_block is None

    if not endpoint:
        return ProductResult(
            status="ERROR",
            message=msg.product_endpoint_no_endpoint(pid),
            product_id=pid,
            endpoint_url="",
            details={"error": "no endpoint defined"},
        )

    full_url = base_url.rstrip("/") + endpoint

    try:
        resp = await client.get(full_url)
    except httpx.TimeoutException:
        return ProductResult(
            status="ERROR",
            message=msg.product_timeout(name),
            product_id=pid,
            endpoint_url=full_url,
            details={"endpoint": endpoint, "error": "timeout"},
        )
    except httpx.ConnectError as e:
        return ProductResult(
            status="ERROR",
            message=msg.product_connect_error(name, str(e)),
            product_id=pid,
            endpoint_url=full_url,
            details={"endpoint": endpoint, "error": str(e)},
        )
    except Exception as e:
        return ProductResult(
            status="ERROR",
            message=msg.product_unexpected(name, -1),
            product_id=pid,
            endpoint_url=full_url,
            details={"endpoint": endpoint, "error": str(e)},
        )

    status = resp.status_code

    if is_free:
        if status == 200:
            return ProductResult(
                status="PASS",
                message=msg.product_free_pass(name),
                product_id=pid,
                endpoint_url=full_url,
                details={"endpoint": endpoint, "status_code": status, "is_free": True},
            )
        return ProductResult(
            status="FAIL",
            message=msg.product_free_fail(name, status),
            product_id=pid,
            endpoint_url=full_url,
            details={"endpoint": endpoint, "status_code": status, "is_free": True},
        )

    if status == 402:
        headers_lower = {k.lower() for k in resp.headers.keys()}
        has_pr = "payment-required" in headers_lower or "x-payment-required" in headers_lower
        if has_pr:
            return ProductResult(
                status="PASS",
                message=msg.product_paid_ok_with_header(name),
                product_id=pid,
                endpoint_url=full_url,
                details={
                    "endpoint": endpoint,
                    "status_code": status,
                    "is_free": False,
                    "has_payment_header": True,
                    "headers": dict(resp.headers),
                },
            )
        return ProductResult(
            status="FAIL",
            message=msg.product_paid_ok_no_header(name),
            product_id=pid,
            endpoint_url=full_url,
            details={
                "endpoint": endpoint,
                "status_code": status,
                "is_free": False,
                "has_payment_header": False,
                "headers": dict(resp.headers),
            },
        )

    if status == 200:
        return ProductResult(
            status="FAIL",
            message=msg.product_paid_wrong(name, status),
            product_id=pid,
            endpoint_url=full_url,
            details={"endpoint": endpoint, "status_code": status, "is_free": False},
        )

    return ProductResult(
        status="ERROR",
        message=msg.product_unexpected(name, status),
        product_id=pid,
        endpoint_url=full_url,
        details={"endpoint": endpoint, "status_code": status, "is_free": False},
    )
