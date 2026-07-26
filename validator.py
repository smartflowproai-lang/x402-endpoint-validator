#!/usr/bin/env python3
"""x402 Endpoint Validator — CI compliance checker.

Reads input via environment variables prepared by entrypoint.sh, validates
each endpoint against five checks, writes a JSON report, and exits with
status 0 (all checks meet thresholds) or 1 (one or more failed).

Checks per endpoint
-------------------
1. HTTP reachability — decided from the probe attempts in check 3: the route
   is alive when any method got a non-5xx, non-404/410 answer. A 402 from
   POST proves a POST-only route exists, so a GET 404 on it is not a dead
   route. Network errors / 5xx / all-methods-404 are failures.
2. /.well-known/x402 manifest — fetched once per host, must parse as JSON
   and contain either an `accepts[]` (per resource) or a `resources[]` /
   `payment` block compatible with x402 spec v1 or v2. A defect here is a
   HOST-level finding surfaced in `summary.manifest_defect_hosts`; it does
   not fail the endpoint.
3. PaymentRequired conformance — probes GET then POST (configurable) with
   no payment headers; on HTTP 402, prefers the v2 PAYMENT-REQUIRED header
   (base64 PaymentRequired) as canonical, falls back to body accepts[] as
   legacy placement, and reports channel / mismatch / failure_class.
4. Response time P95 — five sequential probes; the 95th percentile of the
   latency samples (ms) must be below `threshold_p95_ms`.
5. Payment-required behavior — confirms that the unauthenticated probe in
   check 3 returned HTTP 402 (not 401/403/200/empty body), unless the route
   is declared `expect: free`.

Severity
--------
Each endpoint carries `pass`, `info`, or `fail`. `info` (`free_route`,
`auth_gated`, `unknown_network`) means there is nothing to convict: it never
counts as a failure and never launders into a pass.

Spec reference: the response-body shape mirrored here is the
`x402Version=1` shape observed across the dominant cohort of live x402
endpoints (canonical hash `ad0c163412139f1e`, 97,532 scans across 10,841
URLs per the operator-launch-kit pattern analysis). Both v1 and v2 schemas
are accepted to avoid penalising early adopters.

Exit codes
----------
- 0: all endpoints passed (or fail_on == "never")
- 1: one or more endpoints failed (subject to fail_on policy)
- 2: input parsing error
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - yaml is in image but stay defensive
    yaml = None  # type: ignore

from payment_required import (
    INFO_CLASSES,
    SEVERITY_FAIL,
    SEVERITY_INFO,
    SEVERITY_PASS,
    caip2_in_obj,
    classify_failure,
    compare_channels,
    extract_payment_required,
    validate_accepts,
)

VALIDATOR_VERSION = "1.3.0"
USER_AGENT = f"x402-endpoint-validator/{VALIDATOR_VERSION} (+https://smartflowproai.com/atlas)"
DEFAULT_TIMEOUT_S = 10
P95_SAMPLE_COUNT = 5
REQUIRED_402_KEYS = ("x402Version", "accepts", "error")
REQUIRED_ACCEPT_KEYS = ("scheme", "network")
PRICE_KEYS = ("maxAmountRequired", "amount", "price")

# Archive limits for raw_response (strict-v2 design contract).
# Cap keeps corpus reports bounded when a single endpoint returns a huge body.
RAW_RESPONSE_BODY_MAX_BYTES = 64 * 1024  # 64 KiB
# Headers that must never land in CI artifacts / corpus reports. Beyond the
# obvious secrets: CDN telemetry headers carry per-zone reporting tokens and
# nothing about x402 conformance (audit 2026-07-25, redaction list, LOW).
REDACTED_RESPONSE_HEADERS = frozenset({
    "set-cookie",
    "authorization",
    "nel",
    "report-to",
    "reporting-endpoints",
})
REDACTED_HEADER_PLACEHOLDER = "[REDACTED]"


def log(msg: str) -> None:
    print(f"[x402-validator] {msg}", flush=True)


# Outbound request throttle. A full run is up to 7 requests per endpoint
# (probe + 5 latency samples + one manifest fetch per host); on a 75-endpoint
# corpus that is a load spike on someone else's production API. Set
# X402V_MAX_RPS=0 to disable.
_last_request_at: float = 0.0


def _throttle() -> None:
    global _last_request_at
    try:
        max_rps = float(os.environ.get("X402V_MAX_RPS", "0") or "0")
    except ValueError:
        max_rps = 0.0
    if max_rps <= 0:
        return
    min_gap = 1.0 / max_rps
    wait = min_gap - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


# Characters that never appear in a bare endpoint URL but do appear when a
# sentence from a provider's docs is mistaken for one (audit 2026-07-25 RS-12:
# `https://…/v1/llm {"prompt":"..."} — $0.002, or GET /v1/weather…` was scanned
# as an endpoint and became the only finding in a partner-facing report).
_URL_FORBIDDEN_CHARS = frozenset(' \t\n\r\v\f"\'{}<>|\\^`')
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_endpoint_url(url: str) -> str | None:
    """Return None when `url` is a usable endpoint URL, else the reason why not."""
    if not url:
        return "empty entry"
    if any(ch in _URL_FORBIDDEN_CHARS for ch in url):
        return "contains whitespace or prose punctuation (looks like documentation text, not a URL)"
    if any(ord(ch) > 127 for ch in url):
        return "contains non-ASCII characters (looks like documentation text, not a URL)"
    if not url.startswith(("http://", "https://")):
        return "not an http(s) URL"
    parts = urlsplit(url)
    if not parts.netloc:
        return "missing host"
    host = parts.netloc.rsplit("@", 1)[-1].rsplit(":", 1)[0]
    if not host or not _HOST_RE.match(host):
        return "invalid host"
    if "." not in host and host != "localhost":
        return "implausible host (no dot, not localhost)"
    return None


def parse_endpoints(raw: str, workspace: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Resolve the `endpoints` input into (specs, rejected).

    Accepts: a single URL string, a newline-separated URL list, a JSON array
    literal, or a path to a YAML/JSON file inside the workspace whose
    top-level value is either a list or an object with an `endpoints` key.

    Each spec is ``{"url", "probe_method", "expect"}``. List entries may be
    plain URL strings or objects carrying per-endpoint ``probe_method``
    (auto|GET|POST) and ``expect`` (auto|paid|free).

    Entries that do not look like URLs are *rejected*, not scanned — they are
    returned as ``{"entry", "reason"}`` so the run can report them instead of
    accusing a merchant of a route it never published (RS-12).
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("endpoints input is empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        # One URL per line. Splitting on arbitrary whitespace is what turned a
        # documentation sentence into three "endpoints" (RS-12).
        return _coerce_list([line.strip() for line in raw.splitlines() if line.strip()])

    if raw.startswith("[") or raw.startswith("{"):
        return _coerce_list(json.loads(raw))

    candidate = os.path.join(workspace, raw)
    if os.path.isfile(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            text = f.read()
        if candidate.endswith((".yml", ".yaml")):
            if yaml is None:
                raise RuntimeError("PyYAML is required to read YAML configs")
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        return _coerce_list(data)

    raise ValueError(f"could not interpret endpoints input: {raw!r}")


def _coerce_list(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and "endpoints" in data:
        entries = data["endpoints"]
    else:
        raise ValueError("endpoints config must be a list or {endpoints: [...]}")

    specs: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in entries:
        if isinstance(item, str):
            url, probe_method, expect = item.strip(), "auto", "auto"
        elif isinstance(item, dict) and "url" in item:
            url = str(item["url"]).strip()
            probe_method = str(item.get("probe_method") or "auto").strip() or "auto"
            expect = str(item.get("expect") or "auto").strip().lower() or "auto"
        else:
            raise ValueError(f"unrecognised endpoint entry: {item!r}")
        if expect not in ("auto", "paid", "free"):
            raise ValueError(f"expect must be auto|paid|free, got {expect!r}")
        reason = validate_endpoint_url(url)
        if reason:
            rejected.append({"entry": url, "reason": reason})
            continue
        specs.append({"url": url, "probe_method": probe_method, "expect": expect})
    return specs, rejected


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def check_reachability(url: str, probe_attempts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Decide liveness from the probe attempts that produced the verdict.

    A route is alive when *any* method got a non-5xx, non-404/410 answer out
    of it. Judging liveness with a standalone GET convicted POST-only routes
    as "Dead route (HTTP 404)" in the same record where the POST probe
    reported `402 with strict-v2 conformant PaymentRequired` — the report
    contradicted itself (audit 2026-07-25 RS-2). 401/403/429 still count as
    alive: the route exists and answers.
    """
    attempts = list(probe_attempts or [])
    if not attempts:
        # No probe evidence (probe itself failed at the network layer).
        return {
            "passed": False,
            "status_code": None,
            "method": None,
            "attempts": [],
            "note": "no probe response (network error)",
        }

    def _alive(status: Any) -> bool:
        return isinstance(status, int) and 0 < status < 500 and status not in (404, 410)

    # A 402 is the strongest liveness evidence there is: the route exists and
    # is paywalled. Prefer it over any other answer, whichever method got it.
    deciding = next((a for a in attempts if a.get("status_code") == 402), None)
    if deciding is None:
        deciding = next((a for a in attempts if _alive(a.get("status_code"))), None)

    tried = ", ".join(
        f"{a.get('method')} {a.get('status_code')}" for a in attempts
    )
    if deciding is not None:
        status = deciding["status_code"]
        method = deciding.get("method")
        note = (
            f"Route alive: HTTP 402 via {method}"
            if status == 402
            else f"Route answered (HTTP {status} via {method})"
        )
        return {
            "passed": True,
            "status_code": status,
            "method": method,
            "attempts": attempts,
            "note": note,
        }

    statuses = [a.get("status_code") for a in attempts]
    if any(isinstance(s, int) and s >= 500 for s in statuses):
        note = f"Server error (tried: {tried})"
    else:
        note = f"Dead route — no method answered (tried: {tried})"
    return {
        "passed": False,
        "status_code": statuses[-1],
        "method": attempts[-1].get("method"),
        "attempts": attempts,
        "note": note,
    }


def check_manifest(url: str) -> dict[str, Any]:
    manifest_url = origin_of(url) + "/.well-known/x402"
    _throttle()
    try:
        resp = requests.get(
            manifest_url,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    except requests.RequestException as exc:
        return {
            "passed": False,
            "manifest_url": manifest_url,
            "note": f"network error: {exc.__class__.__name__}",
        }

    if resp.status_code != 200:
        return {
            "passed": False,
            "manifest_url": manifest_url,
            "status_code": resp.status_code,
            "note": "manifest not reachable (expected 200)",
        }

    try:
        data = resp.json()
    except ValueError:
        return {
            "passed": False,
            "manifest_url": manifest_url,
            "status_code": resp.status_code,
            "note": "manifest body is not valid JSON",
        }

    schema_ok = False
    schema_kind = "unknown"
    if isinstance(data, dict):
        resources = data.get("resources")
        if "accepts" in data and isinstance(data["accepts"], list):
            schema_ok = bool(data["accepts"])
            schema_kind = "v1-accepts"
        elif resources is not None and "payment" in data:
            schema_ok = isinstance(resources, list) and bool(resources)
            schema_kind = "v2-provider-payment"
        elif (
            isinstance(resources, list)
            and resources
            and all(isinstance(r, dict) for r in resources)
            and any(isinstance(r.get("accepts"), list) and r["accepts"] for r in resources)
        ):
            # Per-resource payment terms (no top-level payment block): each
            # resource entry carries its own accepts array. Seen in the wild
            # (e.g. multi-resource providers); self-describing, so it passes.
            schema_ok = True
            schema_kind = "v2-resource-accepts"
        elif (
            isinstance(resources, list)
            and resources
            and all(isinstance(r, str) for r in resources)
        ):
            # Bare URL list: machine-readable inventory but carries no payment
            # terms, so agents still need a live probe per resource.
            schema_ok = False
            schema_kind = "resource-list-bare"
        elif "endpoints" in data and isinstance(data["endpoints"], list):
            schema_ok = bool(data["endpoints"])
            schema_kind = "legacy-endpoints"

    if schema_ok:
        note = "manifest parsed and schema recognised"
    elif schema_kind == "resource-list-bare":
        note = "resource list without payment terms (no accepts per resource)"
    else:
        note = "manifest schema not recognised"

    return {
        "passed": schema_ok,
        "manifest_url": manifest_url,
        "status_code": resp.status_code,
        "schema_kind": schema_kind,
        "x402_version": data.get("x402Version") if isinstance(data, dict) else None,
        "note": note,
    }


def _probe_methods(probe_method: str) -> list[str]:
    method = (probe_method or "auto").strip().upper()
    if method in ("GET", "POST"):
        return [method]
    return ["GET", "POST"]


def _probe_once(url: str, method: str) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    _throttle()
    if method == "POST":
        headers["Content-Type"] = "application/json"
        return requests.post(url, timeout=DEFAULT_TIMEOUT_S, headers=headers, json={})
    return requests.get(url, timeout=DEFAULT_TIMEOUT_S, headers=headers)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _redact_archived_headers(headers: dict[str, str]) -> dict[str, str]:
    """Lowercase header names; redact secrets that must not land in reports."""
    out: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).lower()
        if name in REDACTED_RESPONSE_HEADERS:
            out[name] = REDACTED_HEADER_PLACEHOLDER
        else:
            out[name] = str(value)
    return out


def _archive_response_body(body_text: str | None) -> tuple[str, bool, str | None]:
    """Return (archived_body, body_truncated, body_sha256).

    ``body_sha256`` is the SHA-256 hex digest of the full original body bytes
    (UTF-8, replacement on encode errors). When the body exceeds
    ``RAW_RESPONSE_BODY_MAX_BYTES``, the archived text is truncated and
    ``body_truncated`` is True. ``body_sha256`` is None when no body was received.
    """
    if body_text is None:
        return "", False, None
    body_bytes = body_text.encode("utf-8", errors="replace")
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    if len(body_bytes) > RAW_RESPONSE_BODY_MAX_BYTES:
        truncated = body_bytes[:RAW_RESPONSE_BODY_MAX_BYTES]
        return truncated.decode("utf-8", errors="replace"), True, body_sha256
    return body_text, False, body_sha256


def build_raw_response(
    *,
    method: str | None,
    url: str,
    status_code: int | None,
    headers: dict[str, str],
    body_text: str | None,
) -> dict[str, Any]:
    """Build the strict-v2 ``raw_response`` archive object (design field table)."""
    archived_body, body_truncated, body_sha256 = _archive_response_body(body_text)
    return {
        "method": method,
        "url": url,
        "status_code": status_code,
        "headers": _redact_archived_headers(headers),
        "body": archived_body,
        "body_truncated": body_truncated,
        "body_sha256": body_sha256,
    }


def check_402_body(
    url: str,
    probe_method: str = "auto",
    strict_v2: bool = False,
    expect: str = "auto",
) -> dict[str, Any]:
    """Probe for HTTP 402 and validate PaymentRequired (header-canonical v2).

    Probe order for ``auto``: GET then POST. First 402 response wins.
    Requirements are taken from PAYMENT-REQUIRED when present; body-only
    responses still pass with ``legacy_placement=True`` unless ``strict_v2``.
    """
    probed_at_utc = _utc_now()
    last_exc: Exception | None = None
    chosen = None
    chosen_method: str | None = None

    # Every attempt is recorded (audit 2026-07-25 N1-6: the earlier response
    # used to vanish from the archive when a later method overwrote it).
    attempts: list[tuple[str, Any]] = []
    for method in _probe_methods(probe_method):
        try:
            resp = _probe_once(url, method)
        except requests.RequestException as exc:
            last_exc = exc
            continue
        probed_at_utc = _utc_now()
        attempts.append((method, resp))
        if resp.status_code == 402:
            chosen = resp
            chosen_method = method
            break
    if chosen is None and attempts:
        # No 402 anywhere. Prefer a 2xx answer (route exists, likely free)
        # over a method error, so a GET 200 is not buried under a POST 405
        # (audit N2-7: "this route is free" never surfaced).
        for method, resp in attempts:
            if 200 <= resp.status_code < 300:
                chosen, chosen_method = resp, method
                break
        else:
            chosen_method, chosen = attempts[-1][0], attempts[-1][1]
    attempts_meta = [
        {"method": m, "status_code": r.status_code} for m, r in attempts
    ]

    def _base_result(**extra: Any) -> dict[str, Any]:
        out = {
            "passed": False,
            "payment_required_passed": False,
            "status_code": None,
            "body_conformant": False,
            "channel": None,
            "probe_method": None,
            "schemes": [],
            "networks": [],
            "failure_class": "undecided",
            "legacy_placement": False,
            "channel_mismatch": False,
            "channel_mismatch_fields": [],
            "caip2_in_header": False,
            "missing_keys": [],
            "x402_version": None,
            "findings": [],
            "strict_v2": strict_v2,
            "expect": expect,
            "severity": SEVERITY_FAIL,
            "probed_at_utc": probed_at_utc,
            "probe_attempts": attempts_meta,
            "note": "",
        }
        out.update(extra)
        return out

    if chosen is None:
        return _base_result(
            note=f"network error: {last_exc.__class__.__name__}" if last_exc else "no probe response",
        )

    status = chosen.status_code
    is_402 = status == 402
    body_text = chosen.text if chosen.text is not None else ""
    headers = {str(k): str(v) for k, v in chosen.headers.items()}
    raw_response = build_raw_response(
        method=chosen_method,
        url=url,
        status_code=status,
        headers=headers,
        body_text=body_text,
    )

    extracted = extract_payment_required(status, headers, body_text)
    mismatch_fields = compare_channels(extracted.header_obj, extracted.body_obj)
    channel_mismatch = bool(mismatch_fields)

    failure_class: str | None = None
    schemes: list[str] = []
    networks: list[str] = []
    findings: list[str] = []
    body_ok = False
    note = ""

    severity = SEVERITY_FAIL

    if not is_402 and expect == "free":
        # The provider documents this route as free (e.g. its own OpenAPI
        # declares responses: ["200"]). Absence of a 402 is the documented
        # behaviour, not a spec violation — reporting it as a failure accuses
        # the merchant of breaking a contract it never made (audit RS-3).
        failure_class = "free_route"
        severity = SEVERITY_INFO
        note = f"documented free route answered HTTP {status}; no payment required (info)"
    elif not is_402:
        failure_class = "undecided"
        note = f"expected HTTP 402, got {status}"
    elif extracted.header_invalid:
        failure_class = "v2_header_invalid"
        note = "PAYMENT-REQUIRED header present but not valid base64 JSON PaymentRequired"
    elif extracted.canonical is None:
        failure_class = classify_failure(status, headers, body_text) or "header_only_accepts"
        note = (
            "L402/WWW-Authenticate dialect without x402 PaymentRequired"
            if failure_class == "l402_www_authenticate"
            else "no PaymentRequired in PAYMENT-REQUIRED header or body accepts[]"
        )
    elif strict_v2 and extracted.legacy_placement:
        # Issue #1: strict-v2 forbids body-only legacy placement.
        failure_class = "legacy_placement"
        body_ok = False
        note = "strict-v2 requires PAYMENT-REQUIRED header; body-only legacy placement rejected"
        if isinstance(extracted.body_obj, dict):
            soft = validate_accepts(extracted.body_obj, source="body", strict_v2=False)
            schemes = soft.schemes
            networks = soft.networks
    else:
        source = "header" if extracted.header_obj is not None else "body"
        validated = validate_accepts(
            extracted.canonical,
            source=source,
            strict_v2=strict_v2,
        )
        body_ok = validated.ok
        schemes = validated.schemes
        networks = validated.networks
        findings = list(validated.findings)
        failure_class = None if validated.ok else validated.failure_class
        severity = validated.severity
        if expect == "free":
            findings.append(
                "route is documented as free but returned 402 (documentation drift)"
            )
        if channel_mismatch:
            findings.append(
                "header/body channel mismatch on: " + ", ".join(mismatch_fields)
            )
        if validated.ok:
            if extracted.legacy_placement:
                note = "402 with legacy body-only PaymentRequired"
            elif channel_mismatch:
                note = "402 with conformant header PaymentRequired (body mismatch noted)"
            else:
                mode = "strict-v2 " if strict_v2 else ""
                note = f"402 with {mode}conformant PaymentRequired via {extracted.channel}"
        else:
            note = "; ".join(findings) if findings else "non-conformant PaymentRequired"

    passed = bool(is_402 and body_ok)
    if passed:
        severity = SEVERITY_PASS
    x402_version = None
    if extracted.canonical is not None:
        x402_version = extracted.canonical.get("x402Version")

    missing_keys: list[str] = []
    if extracted.channel == "body" and isinstance(extracted.body_obj, dict):
        missing_keys = [k for k in REQUIRED_402_KEYS if k not in extracted.body_obj]

    return {
        "passed": passed,
        "payment_required_passed": is_402,
        "status_code": status,
        "body_conformant": body_ok,
        "channel": extracted.channel,
        "probe_method": chosen_method,
        "schemes": schemes,
        "networks": networks,
        "failure_class": failure_class if not passed else None,
        "legacy_placement": extracted.legacy_placement,
        "channel_mismatch": channel_mismatch,
        "channel_mismatch_fields": mismatch_fields,
        "caip2_in_header": caip2_in_obj(extracted.header_obj),
        "missing_keys": missing_keys,
        "x402_version": x402_version,
        "findings": findings,
        "strict_v2": strict_v2,
        "expect": expect,
        "severity": severity,
        "probed_at_utc": probed_at_utc,
        # Advertised evidence field that never reached the report: it was
        # built for _base_result() only, so 0 of 81 endpoint records in the
        # 2026-07-25 re-scans carried it (audit RS-10).
        "probe_attempts": attempts_meta,
        "raw_response": raw_response,
        "note": note,
    }


def check_p95(url: str, threshold_ms: int) -> dict[str, Any]:
    samples: list[int] = []
    errors = 0
    for _ in range(P95_SAMPLE_COUNT):
        _throttle()
        started = time.monotonic()
        try:
            resp = requests.get(
                url,
                timeout=DEFAULT_TIMEOUT_S,
                headers={"User-Agent": USER_AGENT},
            )
            _ = resp.status_code
        except requests.RequestException:
            errors += 1
            continue
        samples.append(int((time.monotonic() - started) * 1000))

    if not samples:
        return {
            "passed": False,
            "samples_ms": [],
            "p95_ms": None,
            "threshold_ms": threshold_ms,
            "errors": errors,
            "note": "no successful probes",
        }

    # statistics.quantiles requires n>=2; for small samples use the
    # interpolation-free "max of sample" as a conservative P95.
    if len(samples) >= 4:
        p95 = int(statistics.quantiles(samples, n=20)[18])
    else:
        p95 = max(samples)

    return {
        "passed": p95 <= threshold_ms,
        "samples_ms": samples,
        "p95_ms": p95,
        "threshold_ms": threshold_ms,
        "errors": errors,
        "note": f"P95={p95}ms (threshold {threshold_ms}ms)",
    }


def enhanced_check(url: str, api_key: str) -> dict[str, Any]:
    """Query Mapper API for paid-tier intel (wash flag, reputation, history)."""
    try:
        resp = requests.get(
            f"https://api.smartflowproai.com/v1/endpoints/{url}",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "reputation_score": data.get("reputation_score"),
                "wash_flag": data.get("wash_flag"),
                "facilitator_mediated": data.get("is_facilitator_mediated"),
                "on_chain_volume_30d": data.get("on_chain_volume_usdc_30d"),
                "ok": True,
            }
        return {"ok": False, "error": f"api_status_{resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_MANIFEST_CACHE: dict[str, dict[str, Any]] = {}


def _check_manifest_cached(url: str) -> dict[str, Any]:
    """One manifest check per host per run (audit 2026-07-25 N3-2: the same
    host manifest used to be fetched once per endpoint, so a single manifest
    defect was counted N times and read as N broken endpoints)."""
    host = url.split("//", 1)[-1].split("/", 1)[0]
    if host not in _MANIFEST_CACHE:
        _MANIFEST_CACHE[host] = check_manifest(url)
    return _MANIFEST_CACHE[host]


def validate_endpoint(
    url: str,
    threshold_ms: int,
    api_key: str = "",
    probe_method: str = "auto",
    strict_v2: bool = False,
    expect: str = "auto",
) -> dict[str, Any]:
    log(f"validating {url}")
    # The payment probe runs first so reachability can be decided from the
    # method that actually produced the verdict (RS-2).
    body = check_402_body(
        url, probe_method=probe_method, strict_v2=strict_v2, expect=expect
    )
    reach = check_reachability(url, body.get("probe_attempts"))
    manifest = _check_manifest_cached(url)
    perf = check_p95(url, threshold_ms)
    # Severity, not a bare boolean: `info` means "nothing to convict here"
    # (documented free route, auth wall, unverifiable network), so it must not
    # count as a failure — and must not be laundered into a pass either.
    severity = body.get("severity") or (SEVERITY_PASS if body.get("passed") else SEVERITY_FAIL)
    # A manifest defect is a HOST-level finding, reported via manifest_defect;
    # it no longer fails every endpoint of the host (audit N3-2). The endpoint
    # answers for its own behaviour only.
    endpoint_passed = all((
        reach["passed"],
        perf["passed"],
        severity in (SEVERITY_PASS, SEVERITY_INFO),
    ))
    result = {
        "url": url,
        "passed": endpoint_passed,
        "severity": severity,
        "failure_class": body.get("failure_class"),
        "expect": expect,
        "manifest_defect": not manifest["passed"],
        "probed_at_utc": body.get("probed_at_utc"),
        "checks": {
            "reachability": reach,
            "manifest": manifest,
            "body_conformance": body,
            "response_time_p95": perf,
            "payment_required": {
                "passed": body.get("payment_required_passed", False),
                "status_code": body.get("status_code"),
                "note": "HTTP 402 returned" if body.get("payment_required_passed") else "did not return 402",
            },
        },
    }
    if api_key:
        enhanced = enhanced_check(url, api_key)
        result["enhanced"] = enhanced
        if enhanced.get("ok"):
            log(
                f"  enhanced: reputation={enhanced.get('reputation_score')} "
                f"wash_flag={enhanced.get('wash_flag')} "
                f"facilitator_mediated={enhanced.get('facilitator_mediated')} "
                f"on_chain_volume_30d={enhanced.get('on_chain_volume_30d')}"
            )
        else:
            log(f"  enhanced: lookup failed ({enhanced.get('error')})")
    return result


def print_upsell(api_key_present: bool) -> None:
    """Lead-funnel CTA. Opt-in via X402V_SHOW_UPSELL=true.

    Off by default: scan logs get pasted into partner-facing bug reports, and
    a sales pitch stapled to an accusation is not a defensible artifact
    (audit 2026-07-25, redaction list).
    """
    if (os.environ.get("X402V_SHOW_UPSELL", "") or "").strip().lower() not in (
        "1", "true", "yes", "on"
    ):
        return
    if api_key_present:
        return  # paid user, no need to upsell
    log("")
    log("⚡ Free tier scan complete.")
    log("⚡ Want wash detection, operator farm flags, endpoint reputation history, & cross-endpoint correlation?")
    log("⚡ Subscribe to Mapper API: https://hypersub.xyz/s/smartflow-scorecard ($15-$4999/mo)")
    log("⚡ Query directly: https://api.smartflowproai.com/v1/endpoints/{url}?key=YOUR_KEY")
    log("")


def maybe_post_webhook(webhook_url: str, report: dict[str, Any]) -> None:
    if not webhook_url:
        return
    summary = report["summary"]
    text = (
        f"x402 validator run: {summary['endpoints_checked']} checked, "
        f"{summary['failures']} failed, status={'PASS' if summary['all_passed'] else 'FAIL'}"
    )
    try:
        requests.post(
            webhook_url,
            timeout=DEFAULT_TIMEOUT_S,
            json={"text": text, "report_summary": summary},
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        log(f"webhook delivery failed: {exc}")


def decide_exit_code(report: dict[str, Any], fail_on: str) -> int:
    """Map the report to an exit code. Every mode is a subset of `passed`.

    `critical` used to also fail on a manifest defect, which `passed` says is
    not the endpoint's failure — two contradictory definitions of failure in
    one binary (audit 2026-07-25 RS-7). Manifest drift now has its own opt-in
    mode so the behaviour is requested, not smuggled in.
    """
    summary = report["summary"]
    if fail_on == "never":
        return 0
    if fail_on == "manifest":
        return 1 if summary.get("manifest_defect_hosts") else 0
    if fail_on == "critical":
        # Payment-conformance defects only, and only ones that already made
        # the endpoint fail. Info classes never reach here.
        critical = sum(
            1
            for ep in report["endpoints"]
            if not ep["passed"]
            and ep["checks"]["body_conformance"].get("severity") == SEVERITY_FAIL
        )
        return 1 if critical else 0
    # default: "any"
    return 0 if summary["all_passed"] else 1


def main() -> int:
    endpoints_raw = os.environ.get("X402V_ENDPOINTS", "")
    workspace = os.environ.get("X402V_WORKSPACE", os.getcwd())
    try:
        threshold_ms = int(os.environ.get("X402V_THRESHOLD_P95", "1000"))
    except ValueError:
        log("threshold-p95 must be an integer")
        return 2
    tier = (os.environ.get("X402V_TIER", "free") or "free").lower()
    pro_key = os.environ.get("X402V_PRO_LICENSE_KEY", "")
    webhook_url = os.environ.get("X402V_WEBHOOK_URL", "")
    report_path = os.environ.get("X402V_REPORT_PATH", "x402-validator-report.json")
    fail_on = (os.environ.get("X402V_FAIL_ON", "any") or "any").lower()
    api_key = os.environ.get("INPUT_API_KEY", "") or os.environ.get("X402V_API_KEY", "")
    probe_method = (os.environ.get("X402V_PROBE_METHOD", "auto") or "auto").strip() or "auto"
    strict_v2_raw = (os.environ.get("X402V_STRICT_V2", "false") or "false").strip().lower()
    strict_v2 = strict_v2_raw in ("1", "true", "yes", "on")

    if tier == "pro" and not pro_key:
        log("tier=pro requires pro-license-key — falling back to free tier")
        tier = "free"
        webhook_url = ""

    try:
        specs, rejected = parse_endpoints(endpoints_raw, workspace)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        log(f"failed to parse endpoints: {exc}")
        return 2
    for bad in rejected:
        log(f"rejected input entry (not a URL): {bad['reason']}")
    if not specs:
        log("no endpoints to validate")
        return 2

    log(f"validating {len(specs)} endpoint(s)")

    results = [
        validate_endpoint(
            spec["url"],
            threshold_ms,
            api_key,
            probe_method=spec.get("probe_method") or probe_method,
            strict_v2=strict_v2,
            expect=spec.get("expect", "auto"),
        )
        for spec in specs
    ]
    failures = sum(1 for r in results if not r["passed"])
    info_only = sum(1 for r in results if r["passed"] and r.get("severity") == SEVERITY_INFO)
    # Host-level, not per-endpoint: one broken manifest used to be counted once
    # per endpoint of the host (audit N3-2) and then vanished from the summary
    # entirely (RS-6). It is a real finding — it belongs in the headline.
    defect_hosts = sorted({
        r["checks"]["manifest"]["manifest_url"]
        for r in results
        if r.get("manifest_defect")
    })
    info_classes = sorted({
        r.get("failure_class")
        for r in results
        if r.get("failure_class") in INFO_CLASSES
    })
    summary = {
        "endpoints_checked": len(results),
        "failures": failures,
        "all_passed": failures == 0,
        "info_findings": info_only,
        "info_classes": info_classes,
        "manifest_defect_hosts": defect_hosts,
        "manifest_defects": len(defect_hosts),
        "input_entries_rejected": rejected,
        "threshold_p95_ms": threshold_ms,
        "tier": tier,
        "enhanced_enabled": bool(api_key),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "validator_version": VALIDATOR_VERSION,
        "probe_method": probe_method,
        "strict_v2": strict_v2,
    }
    report = {"summary": summary, "endpoints": results}

    # Ensure report directory exists.
    abs_report = os.path.abspath(report_path)
    os.makedirs(os.path.dirname(abs_report) or ".", exist_ok=True)
    with open(abs_report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    # Basename only: the full path leaks the runner's filesystem layout into
    # every log that gets pasted into a partner-facing report.
    log(f"wrote report to {os.path.basename(abs_report)}")
    if defect_hosts:
        log(f"manifest defects: {len(defect_hosts)} host(s) — {', '.join(defect_hosts)}")
    if info_only:
        log(f"informational (not failures): {info_only} endpoint(s) — {', '.join(info_classes)}")
    log(f"result: {len(results) - failures} passed, {failures} failed")

    if tier == "pro":
        maybe_post_webhook(webhook_url, report)

    print_upsell(api_key_present=bool(api_key))

    return decide_exit_code(report, fail_on)


if __name__ == "__main__":
    sys.exit(main())
