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


# CAIP-2 (chainagnostic.org/CAIPs/caip-2): namespace 3-8 chars of [-a-z0-9],
# reference 1-32 chars of [-_a-zA-Z0-9]. Real grammar, not an allowlist —
# audit 2026-07-25 N2-5: the old (eip155|solana) pair rejected every other
# valid namespace and passed judgement for the wrong reason.
#
# The reference bound is widened to 44 for the generic form because live
# Solana quotes carry the full 44-char base58 genesis hash rather than the
# CAIP-2 32-char truncation (audit 2026-07-25 RS-11: the 32-char cap created
# an undocumented, untested conviction class). Per-namespace reference
# grammars below are authoritative for the namespaces we actually know.
CAIP2_RE = re.compile(r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,44}$")

# Solana references seen in live quotes: the CAIP-2 32-char genesis-hash
# truncation, the full 44-char genesis hash (RS-11), and the cluster aliases
# x402 merchants actually publish. Aliases are kept because they were already
# accepted — widening the grammar must not smuggle in a new conviction class.
_SOLANA_REF_RE = re.compile(r"^([1-9A-HJ-NP-Za-km-z]{32,44}|mainnet|mainnet-beta|devnet|testnet)$")

# Registry of networks whose unit convention we actually know (RS-4). The
# price rule may only be enforced against a namespace listed here; a network
# string the merchant invents must never silently switch the rule off.
#   reference       — grammar for the CAIP-2 reference part
#   atomic_amount   — True when the x402 spec defines `amount` as an
#                     atomic-unit digit string on this namespace
NAMESPACE_REGISTRY: dict[str, dict[str, Any]] = {
    "eip155": {"reference": re.compile(r"^[0-9]+$"), "atomic_amount": True},
    "solana": {"reference": _SOLANA_REF_RE, "atomic_amount": True},
}

# Auth-challenge extensions we recognise by name (RS-5). `accepts: []` plus one
# of these is an authentication wall, not a payment defect. Anything else with
# an empty accepts[] is a real conformance failure — the previous substring
# sniff ("auth" in the error text) whitelisted `author unknown`.
AUTH_EXTENSION_KEYS = frozenset({
    "sign-in-with-x",
    "siwx",
    "sign-in-with-ethereum",
    "siwe",
    "sign-in-with-solana",
    "siws",
})

# failure_class values that are informational: they describe something we
# cannot judge or that is out of payment-conformance scope. They are never
# merchant defects and must never be reported as failures.
INFO_CLASSES = frozenset({"auth_gated", "unknown_network", "free_route"})

SEVERITY_PASS = "pass"
SEVERITY_INFO = "info"
SEVERITY_FAIL = "fail"


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
    # pass  — at least one rail is fully valid, the endpoint is conformant
    # info  — nothing convictable: out of scope (auth wall) or unverifiable
    #         (network we have no unit convention for). Not a defect.
    # fail  — a real payment-conformance defect
    severity: str = SEVERITY_FAIL


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


def namespace_of(network: str) -> str:
    return (network or "").partition(":")[0]


def is_known_namespace(network: str) -> bool:
    """True when the namespace is in NAMESPACE_REGISTRY (RS-4)."""
    return namespace_of(network) in NAMESPACE_REGISTRY


def _is_caip2(network: str) -> bool:
    s = network or ""
    if not CAIP2_RE.match(s):
        return False
    ns, _, ref = s.partition(":")
    known = NAMESPACE_REGISTRY.get(ns)
    if known is not None:
        # A registered namespace is held to its own reference grammar:
        # "eip155:mainnet" is not a valid CAIP-2 id even though the generic
        # grammar allows it, and a Solana reference must be base58 (32-44,
        # so the full genesis hash is accepted — RS-11).
        return bool(known["reference"].match(ref))
    return True


def _recognised_auth_extension(obj: Mapping[str, Any]) -> str | None:
    """Return the extension name when a known auth challenge is declared."""
    extensions = obj.get("extensions")
    if not isinstance(extensions, dict):
        return None
    for key in extensions:
        if str(key).strip().lower() in AUTH_EXTENSION_KEYS:
            return str(key)
    return None


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
        # Auth challenges (SIWX / login walls) reuse the 402 envelope with no
        # payment offer. That is out of payment-conformance scope, not a
        # merchant defect — but it has to be *proved*, not sniffed: an empty
        # accepts[] plus a recognised auth extension. The previous substring
        # test on the error text passed "author unknown" as an auth wall and
        # returned ok=True (audit 2026-07-25 RS-5).
        auth_ext = _recognised_auth_extension(obj)
        if isinstance(accepts, list) and not accepts and auth_ext:
            return ValidateResult(
                ok=False,
                failure_class="auth_gated",
                severity=SEVERITY_INFO,
                findings=[
                    f"auth challenge via '{auth_ext}' extension with accepts: []; "
                    "payment conformance not applicable (info)"
                ],
            )
        return ValidateResult(
            ok=False,
            failure_class="v2_header_invalid" if source == "header" else "header_only_accepts",
            severity=SEVERITY_FAIL,
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

    # Per-rail validation (audit 2026-07-25 N2-1/N2-2): each accepts[] entry is
    # judged on its own, findings carry the rail index, and the endpoint is
    # conformant when AT LEAST ONE rail is fully valid — an agent can pay a
    # compliant rail today regardless of what the neighbouring rail declares.
    per_item_ok: list[bool] = []
    per_item_info: list[bool] = []
    first_fail_class: str | None = None
    first_info_class: str | None = None

    for i, item in enumerate(accepts):
        prefix = f"accepts[{i}]: "
        item_hard = False
        item_info = False
        item_class: str | None = None
        item_info_class: str | None = None

        if not isinstance(item, dict):
            findings.append(prefix + "entry is not an object")
            per_item_ok.append(False)
            per_item_info.append(False)
            first_fail_class = first_fail_class or "v2_header_invalid"
            continue

        scheme = item.get("scheme")
        network = item.get("network")
        if scheme is not None:
            schemes.append(str(scheme))
        if network is not None:
            networks.append(str(network))

        if scheme is None:
            findings.append(prefix + "entry missing scheme")
            item_hard, item_class = True, item_class or "scheme_unsupported"
        elif str(scheme) not in ("exact", "upto"):
            if strict_v2:
                findings.append(prefix + f"unsupported scheme '{scheme}'")
                item_hard, item_class = True, item_class or "scheme_unsupported"
            else:
                # exact first-class; upto warning-level; unknown schemes are
                # findings but do not hard-fail free tier (README / issue #3).
                findings.append(prefix + f"unsupported scheme '{scheme}' (info)")
        if network is None:
            findings.append(prefix + "entry missing network")
            item_hard, item_class = True, item_class or "network_format"

        if header_like or strict_v2:
            amount = item.get("amount")
            net_str = str(network) if network is not None else ""
            if amount is None or str(amount).strip() == "":
                findings.append(prefix + "header/v2 entry missing amount")
                item_hard, item_class = True, item_class or "amount_key"
            elif not str(amount).isdigit():
                ns = namespace_of(net_str)
                registered = NAMESPACE_REGISTRY.get(ns)
                if registered is not None and registered["atomic_amount"]:
                    # x402 v2: amount is an atomic-unit digit string on the
                    # networks whose convention the spec defines.
                    findings.append(prefix + "amount must be an atomic-unit digit string")
                    item_hard, item_class = True, item_class or "amount_key"
                else:
                    # Namespace outside the registry (audit RS-4): we have no
                    # unit convention to check against, so we can neither
                    # convict nor clear this rail. It is NOT a pass — that is
                    # exactly the hole a merchant walked through by renaming
                    # its network string.
                    findings.append(
                        prefix
                        + f"namespace '{ns or '(none)'}' is not in the known-network registry; "
                        "amount convention unverifiable, price rule not applied (info)"
                    )
                    item_info = True
                    item_info_class = item_info_class or "unknown_network"

            if network is not None and not _is_caip2(net_str):
                findings.append(prefix + "network must be CAIP-2 (namespace:reference)")
                item_hard, item_class = True, item_class or "network_format"

            if strict_v2:
                asset = item.get("asset")
                if asset is None or str(asset).strip() == "":
                    findings.append(prefix + "strict-v2 entry missing asset")
                    item_hard, item_class = True, item_class or "v2_header_invalid"
                pay_to = item.get("payTo")
                if pay_to is None or str(pay_to).strip() == "":
                    findings.append(prefix + "strict-v2 entry missing payTo")
                    item_hard, item_class = True, item_class or "v2_header_invalid"
                timeout = item.get("maxTimeoutSeconds")
                if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
                    findings.append(prefix + "strict-v2 requires maxTimeoutSeconds number > 0")
                    item_hard, item_class = True, item_class or "v2_header_invalid"
        else:
            if _accept_price(item) is None:
                findings.append(prefix + "body entry missing maxAmountRequired|amount|price")
                item_hard, item_class = True, item_class or "amount_key"

        per_item_ok.append(not item_hard and not item_info)
        per_item_info.append(not item_hard and item_info)
        if item_hard:
            first_fail_class = first_fail_class or item_class
        elif item_info:
            first_info_class = first_info_class or item_info_class

    # de-dupe preserving order
    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    # One fully valid rail is enough to clear the endpoint: an agent can pay
    # it today regardless of what a neighbouring rail declares. Failing that,
    # an unverifiable rail downgrades to info rather than a conviction.
    ok = any(per_item_ok)
    if ok:
        severity, failure_class = SEVERITY_PASS, None
    elif any(per_item_info):
        severity, failure_class = SEVERITY_INFO, first_info_class
    else:
        severity, failure_class = SEVERITY_FAIL, first_fail_class
    return ValidateResult(
        ok=ok,
        failure_class=failure_class,
        schemes=_uniq(schemes),
        networks=_uniq(networks),
        findings=findings,
        severity=severity,
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


@dataclass
class BazaarResult:
    ok: bool
    present: bool
    failure_class: str | None
    findings: list[str] = field(default_factory=list)


def check_bazaar_extension(obj: dict[str, Any] | None) -> BazaarResult:
    """Validate the ``extensions.bazaar`` block against the shape observed in
    production captures (viridis_regulatory_radar, viridis_ghg_ledger,
    asterpay_crypto_prices, asterpay_sentiment — all four agree byte-for-byte
    on the top-level keys below).

    The block is an OPTIONAL marketplace-discovery extension, not part of the
    core x402 PaymentRequired contract, so its absence is conformant (PASS,
    ``present=False``). When present, the observed shape is::

        extensions.bazaar.info.input.type    == "http"
        extensions.bazaar.info.input.method  (str, e.g. "GET"/"POST")
        extensions.bazaar.info.output.type   (str, e.g. "json")
        extensions.bazaar.schema             (JSON Schema dict, optional but
                                               always present in every capture
                                               collected so far)

    Returns FAIL when the block exists but is missing ``info``, or ``info``
    is missing ``input``/``output``, or those sub-objects are not dicts, a
    present ``schema`` is not itself an object, or ``input.type``,
    ``input.method``, ``output.type`` are missing OR not strings. Values are
    not pinned — ``"ftp"`` for ``input.type`` is not flagged, only a missing
    or non-string value is — but the type itself is enforced: a marketplace
    client parsing ``method: 7`` breaks the same way it breaks on a missing
    field, which is the failure mode this check exists to catch.

    These are the failure modes that would break a marketplace client
    parsing this block, not a strict reading of fields no capture has ever
    required (no ``serviceName`` / ``tags`` field exists in any of the four
    production captures; an earlier draft of this check assumed a shape
    that does not match any real merchant and would have failed 4/4
    conformant Bazaar merchants).
    """
    if not isinstance(obj, dict):
        return BazaarResult(ok=True, present=False, failure_class=None)

    extensions = obj.get("extensions")
    if not isinstance(extensions, dict) or "bazaar" not in extensions:
        return BazaarResult(ok=True, present=False, failure_class=None)

    bazaar = extensions.get("bazaar")
    findings: list[str] = []

    if not isinstance(bazaar, dict):
        return BazaarResult(
            ok=False,
            present=True,
            failure_class="bazaar_malformed",
            findings=["extensions.bazaar is present but not an object"],
        )

    info = bazaar.get("info")
    if not isinstance(info, dict):
        return BazaarResult(
            ok=False,
            present=True,
            failure_class="bazaar_malformed",
            findings=["extensions.bazaar.info missing or not an object"],
        )

    input_block = info.get("input")
    if not isinstance(input_block, dict):
        findings.append("extensions.bazaar.info.input missing or not an object")
    else:
        input_type = input_block.get("type")
        if not isinstance(input_type, str) or not input_type:
            findings.append("extensions.bazaar.info.input.type missing or not a string")
        input_method = input_block.get("method")
        if not isinstance(input_method, str) or not input_method:
            findings.append("extensions.bazaar.info.input.method missing or not a string")

    output_block = info.get("output")
    if not isinstance(output_block, dict):
        findings.append("extensions.bazaar.info.output missing or not an object")
    else:
        output_type = output_block.get("type")
        if not isinstance(output_type, str) or not output_type:
            findings.append("extensions.bazaar.info.output.type missing or not a string")

    schema = bazaar.get("schema")
    if schema is not None and not isinstance(schema, dict):
        findings.append("extensions.bazaar.schema present but not an object")

    if findings:
        return BazaarResult(
            ok=False,
            present=True,
            failure_class="bazaar_malformed",
            findings=findings,
        )

    return BazaarResult(ok=True, present=True, failure_class=None)
