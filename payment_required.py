"""x402 PaymentRequired channel helpers (v2 header-canonical).

Pure functions for decoding the PAYMENT-REQUIRED header, extracting
requirements from header and/or body, validating accepts[], comparing
channels, and classifying L402-only failures.

Design locked in issue #3 + maintainer confirmation:
- Header is the canonical HTTP transport for PaymentRequired (v2).
- Report channel: header | body | both | none.
- Header wins when both exist; body-only passes as legacy_placement.
- Header/body mismatches on amount/network/payTo are findings.
- L402 / WWW-Authenticate alone is a separate failure_class.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


CAIP2_RE = re.compile(r"^(eip155:\d+|solana:.+)$")


@dataclass
class ExtractResult:
    channel: str  # none|header|body|both
    canonical: dict[str, Any] | None
    header_obj: dict[str, Any] | None
    body_obj: dict[str, Any] | None
    legacy_placement: bool
    header_invalid: bool = False


@dataclass
class ValidateResult:
    ok: bool
    failure_class: str | None
    schemes: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def _header_get(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def decode_payment_required_header(headers: Mapping[str, str]) -> dict[str, Any] | None:
    """Decode base64 JSON from PAYMENT-REQUIRED (case-insensitive)."""
    raw = _header_get(headers, "payment-required")
    if not raw:
        return None
    token = raw.strip().split()[-1] if raw.strip() else ""
    if not token:
        return None
    try:
        padded = token + ("=" * (-len(token) % 4))
        try:
            decoded = base64.b64decode(padded, validate=False)
        except Exception:
            decoded = base64.urlsafe_b64decode(padded)
        obj = json.loads(decoded.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _parse_body_payment(body_text: str) -> dict[str, Any] | None:
    if not body_text or not str(body_text).strip():
        return None
    try:
        data = json.loads(body_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    accepts = data.get("accepts")
    if isinstance(accepts, list) and accepts:
        return data
    return None


def extract_payment_required(
    status: int,
    headers: Mapping[str, str],
    body_text: str,
) -> ExtractResult:
    """Extract PaymentRequired from header and/or body; header is canonical."""
    del status  # status is reserved for callers / classify_failure
    raw_header = _header_get(headers, "payment-required")
    header_present = bool(raw_header and str(raw_header).strip())
    header_obj = decode_payment_required_header(headers) if header_present else None
    body_obj = _parse_body_payment(body_text)

    # Present-but-undecodable PAYMENT-REQUIRED must not silently fall back to
    # a legacy body pass — that is v2_header_invalid, not body-only.
    if header_present and header_obj is None:
        return ExtractResult(
            channel="none",
            canonical=None,
            header_obj=None,
            body_obj=body_obj,
            legacy_placement=False,
            header_invalid=True,
        )

    if header_obj is not None and body_obj is not None:
        return ExtractResult(
            channel="both",
            canonical=header_obj,
            header_obj=header_obj,
            body_obj=body_obj,
            legacy_placement=False,
        )
    if header_obj is not None:
        return ExtractResult(
            channel="header",
            canonical=header_obj,
            header_obj=header_obj,
            body_obj=None,
            legacy_placement=False,
        )
    if body_obj is not None:
        return ExtractResult(
            channel="body",
            canonical=body_obj,
            header_obj=None,
            body_obj=body_obj,
            legacy_placement=True,
        )
    return ExtractResult(
        channel="none",
        canonical=None,
        header_obj=None,
        body_obj=None,
        legacy_placement=False,
    )


def _accept_price(accept: Mapping[str, Any]) -> str | None:
    for key in ("amount", "maxAmountRequired", "price"):
        if key in accept and accept[key] is not None:
            return str(accept[key])
    return None


def compare_channels(
    header_obj: dict[str, Any] | None,
    body_obj: dict[str, Any] | None,
) -> list[str]:
    """Return mismatch field names among amount/network/payTo across accepts[]."""
    if not header_obj or not body_obj:
        return []
    h_accepts = header_obj.get("accepts")
    b_accepts = body_obj.get("accepts")
    if not isinstance(h_accepts, list) or not h_accepts:
        return []
    if not isinstance(b_accepts, list) or not b_accepts:
        return []

    mismatches: set[str] = set()
    for idx in range(max(len(h_accepts), len(b_accepts))):
        h0 = h_accepts[idx] if idx < len(h_accepts) and isinstance(h_accepts[idx], dict) else {}
        b0 = b_accepts[idx] if idx < len(b_accepts) and isinstance(b_accepts[idx], dict) else {}
        if not h0 or not b0:
            # Length mismatch implies at least one quote differs; attribute to
            # network/payTo/amount generically via payTo when one side missing.
            mismatches.update({"amount", "network", "payTo"})
            continue
        if _accept_price(h0) != _accept_price(b0):
            mismatches.add("amount")
        if str(h0.get("network", "")) != str(b0.get("network", "")):
            mismatches.add("network")
        if str(h0.get("payTo", "")) != str(b0.get("payTo", "")):
            mismatches.add("payTo")
    return sorted(mismatches)


def _is_caip2(network: str) -> bool:
    return bool(CAIP2_RE.match(network or ""))


def validate_accepts(
    obj: dict[str, Any],
    *,
    source: str,
    strict_v2: bool = False,
) -> ValidateResult:
    """Validate PaymentRequired.accepts[] for header (v2) or body (legacy) source.

    When ``strict_v2=True`` (issue #1): require integer x402Version==2, CAIP-2
    networks, digit ``amount`` (not maxAmountRequired alone), asset, payTo,
    maxTimeoutSeconds>0, and scheme in {exact, upto}. Unknown schemes hard-fail.
    """
    findings: list[str] = []
    schemes: list[str] = []
    networks: list[str] = []

    if not isinstance(obj, dict):
        return ValidateResult(
            ok=False,
            failure_class="v2_header_invalid" if source == "header" else "undecided",
            findings=["PaymentRequired is not an object"],
        )

    accepts = obj.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        return ValidateResult(
            ok=False,
            failure_class="v2_header_invalid" if source == "header" else "header_only_accepts",
            findings=["accepts[] missing or empty"],
        )

    version_raw = obj.get("x402Version")
    if strict_v2:
        if type(version_raw) is not int or version_raw != 2:
            findings.append("strict-v2 requires integer x402Version == 2")
            return ValidateResult(
                ok=False,
                failure_class="v2_header_invalid",
                findings=findings,
            )
        version = 2
    else:
        try:
            version = int(version_raw) if version_raw is not None else (2 if source == "header" else 1)
        except (TypeError, ValueError):
            version = 2 if source == "header" else 1

    header_like = source == "header" or version >= 2 or strict_v2
    failure_class: str | None = None

    for item in accepts:
        if not isinstance(item, dict):
            findings.append("accepts[] entry is not an object")
            failure_class = failure_class or "v2_header_invalid"
            continue

        scheme = item.get("scheme")
        network = item.get("network")
        if scheme is not None:
            schemes.append(str(scheme))
        if network is not None:
            networks.append(str(network))

        if scheme is None:
            findings.append("accepts[] entry missing scheme")
            failure_class = failure_class or "scheme_unsupported"
        elif str(scheme) not in ("exact", "upto"):
            if strict_v2:
                findings.append(f"unsupported scheme '{scheme}'")
                failure_class = failure_class or "scheme_unsupported"
            else:
                # exact first-class; upto warning-level; unknown schemes are
                # findings but do not hard-fail free tier (README / issue #3).
                findings.append(f"unsupported scheme '{scheme}' (info)")
        if network is None:
            findings.append("accepts[] entry missing network")
            failure_class = failure_class or "network_format"

        if header_like or strict_v2:
            amount = item.get("amount")
            if amount is None or str(amount).strip() == "":
                findings.append("header/v2 accepts[] entry missing amount")
                failure_class = failure_class or "amount_key"
            elif not str(amount).isdigit():
                findings.append("amount must be a digit string")
                failure_class = failure_class or "amount_key"

            if network is not None and not _is_caip2(str(network)):
                findings.append("network must be CAIP-2 (eip155:<n> or solana:<id>)")
                failure_class = failure_class or "network_format"

            if strict_v2:
                asset = item.get("asset")
                if asset is None or str(asset).strip() == "":
                    findings.append("strict-v2 accepts[] entry missing asset")
                    failure_class = failure_class or "v2_header_invalid"
                pay_to = item.get("payTo")
                if pay_to is None or str(pay_to).strip() == "":
                    findings.append("strict-v2 accepts[] entry missing payTo")
                    failure_class = failure_class or "v2_header_invalid"
                timeout = item.get("maxTimeoutSeconds")
                if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
                    findings.append("strict-v2 requires maxTimeoutSeconds number > 0")
                    failure_class = failure_class or "v2_header_invalid"
        else:
            if _accept_price(item) is None:
                findings.append("body accepts[] entry missing maxAmountRequired|amount|price")
                failure_class = failure_class or "amount_key"

    # de-dupe preserving order
    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    # Soft findings (unsupported scheme info) must not flip ok=False.
    hard_findings = [f for f in findings if "(info)" not in f]
    ok = failure_class is None and not hard_findings
    return ValidateResult(
        ok=ok,
        failure_class=failure_class,
        schemes=_uniq(schemes),
        networks=_uniq(networks),
        findings=findings,
    )


def classify_failure(
    status: int,
    headers: Mapping[str, str],
    body_text: str,
) -> str | None:
    """Classify non-x402 payment dialects. Returns None when x402 channels exist."""
    if status != 402:
        return None
    if decode_payment_required_header(headers) is not None:
        return None
    if _parse_body_payment(body_text) is not None:
        return None
    www = _header_get(headers, "www-authenticate") or ""
    www_l = www.lower()
    if www and (
        "l402" in www_l
        or "macaroon" in www_l
        or "lightning" in www_l
        or www_l.startswith("payment ")
        or 'realm="' in www_l
    ):
        return "l402_www_authenticate"
    return None


def caip2_in_obj(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return False
    accepts = obj.get("accepts")
    if not isinstance(accepts, list):
        return False
    for item in accepts:
        if isinstance(item, dict) and _is_caip2(str(item.get("network", ""))):
            return True
    return False
