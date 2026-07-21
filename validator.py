#!/usr/bin/env python3
"""x402 Endpoint Validator — CI compliance checker.

Reads input via environment variables prepared by entrypoint.sh, validates
each endpoint against five checks, writes a JSON report, and exits with
status 0 (all checks meet thresholds) or 1 (one or more failed).

Checks per endpoint
-------------------
1. HTTP reachability — GET returns a non-5xx status; expectation is 200 for
   resource roots and 402 for paywalled paths. The check records the status
   and treats network errors / 5xx as failures.
2. /.well-known/x402 manifest — fetched at the origin, must parse as JSON
   and contain either an `accepts[]` (per resource) or a `resources[]` /
   `payment` block compatible with x402 spec v1 or v2.
3. PaymentRequired conformance — probes GET then POST (configurable) with
   no payment headers; on HTTP 402, prefers the v2 PAYMENT-REQUIRED header
   (base64 PaymentRequired) as canonical, falls back to body accepts[] as
   legacy placement, and reports channel / mismatch / failure_class.
4. Response time P95 — five sequential probes; the 95th percentile of the
   latency samples (ms) must be below `threshold_p95_ms`.
5. Payment-required behavior — confirms that the unauthenticated POST in
   check 3 returned HTTP 402 (not 401/403/200/empty body).

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
    caip2_in_obj,
    classify_failure,
    compare_channels,
    extract_payment_required,
    validate_accepts,
)

USER_AGENT = "x402-endpoint-validator/1.0 (+https://smartflowproai.com/atlas)"
DEFAULT_TIMEOUT_S = 10
P95_SAMPLE_COUNT = 5
REQUIRED_402_KEYS = ("x402Version", "accepts", "error")
REQUIRED_ACCEPT_KEYS = ("scheme", "network")
PRICE_KEYS = ("maxAmountRequired", "amount", "price")

# Archive limits for raw_response (strict-v2 design contract).
# Cap keeps corpus reports bounded when a single endpoint returns a huge body.
RAW_RESPONSE_BODY_MAX_BYTES = 64 * 1024  # 64 KiB
# Headers that must never land in CI artifacts / corpus reports.
REDACTED_RESPONSE_HEADERS = frozenset({"set-cookie", "authorization"})
REDACTED_HEADER_PLACEHOLDER = "[REDACTED]"


def log(msg: str) -> None:
    print(f"[x402-validator] {msg}", flush=True)


def parse_endpoints(raw: str, workspace: str) -> list[str]:
    """Resolve the `endpoints` input into a list of URLs.

    Accepts: a single URL string, a JSON array literal, or a path to a
    YAML/JSON file inside the workspace whose top-level value is either a
    list or an object with an `endpoints` key.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("endpoints input is empty")

    if raw.startswith("http://") or raw.startswith("https://"):
        # Could still be space- or newline-separated multi-URL.
        parts = [p.strip() for p in raw.split() if p.strip()]
        return parts

    if raw.startswith("[") or raw.startswith("{"):
        data = json.loads(raw)
        return _coerce_list(data)

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


def _coerce_list(data: Any) -> list[str]:
    if isinstance(data, list):
        urls = data
    elif isinstance(data, dict) and "endpoints" in data:
        urls = data["endpoints"]
    else:
        raise ValueError("endpoints config must be a list or {endpoints: [...]}")
    out: list[str] = []
    for item in urls:
        if isinstance(item, str):
            out.append(item.strip())
        elif isinstance(item, dict) and "url" in item:
            out.append(str(item["url"]).strip())
        else:
            raise ValueError(f"unrecognised endpoint entry: {item!r}")
    return [u for u in out if u]


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def check_reachability(url: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        resp = requests.get(
            url,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            allow_redirects=True,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = resp.status_code < 500 and resp.status_code != 0
        return {
            "passed": passed,
            "status_code": resp.status_code,
            "response_time_ms": elapsed_ms,
            "note": "Non-5xx status received" if passed else "Server error",
        }
    except requests.RequestException as exc:
        return {
            "passed": False,
            "status_code": None,
            "response_time_ms": None,
            "note": f"network error: {exc.__class__.__name__}",
        }


def check_manifest(url: str) -> dict[str, Any]:
    manifest_url = origin_of(url) + "/.well-known/x402"
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
        if "accepts" in data and isinstance(data["accepts"], list):
            schema_ok = bool(data["accepts"])
            schema_kind = "v1-accepts"
        elif "resources" in data and "payment" in data:
            schema_ok = isinstance(data["resources"], list) and bool(data["resources"])
            schema_kind = "v2-provider-payment"
        elif "endpoints" in data and isinstance(data["endpoints"], list):
            schema_ok = bool(data["endpoints"])
            schema_kind = "legacy-endpoints"

    return {
        "passed": schema_ok,
        "manifest_url": manifest_url,
        "status_code": resp.status_code,
        "schema_kind": schema_kind,
        "x402_version": data.get("x402Version") if isinstance(data, dict) else None,
        "note": "manifest parsed and schema recognised" if schema_ok else "manifest schema not recognised",
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

    for method in _probe_methods(probe_method):
        try:
            resp = _probe_once(url, method)
        except requests.RequestException as exc:
            last_exc = exc
            continue
        probed_at_utc = _utc_now()
        if resp.status_code == 402:
            chosen = resp
            chosen_method = method
            break
        # Keep the last non-402 response in case nothing yields 402.
        chosen = resp
        chosen_method = method

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
            "probed_at_utc": probed_at_utc,
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

    if not is_402:
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
        "probed_at_utc": probed_at_utc,
        "raw_response": raw_response,
        "note": note,
    }


def check_p95(url: str, threshold_ms: int) -> dict[str, Any]:
    samples: list[int] = []
    errors = 0
    for _ in range(P95_SAMPLE_COUNT):
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


def validate_endpoint(
    url: str,
    threshold_ms: int,
    api_key: str = "",
    probe_method: str = "auto",
    strict_v2: bool = False,
) -> dict[str, Any]:
    log(f"validating {url}")
    reach = check_reachability(url)
    manifest = check_manifest(url)
    body = check_402_body(url, probe_method=probe_method, strict_v2=strict_v2)
    perf = check_p95(url, threshold_ms)
    endpoint_passed = all((
        reach["passed"],
        manifest["passed"],
        body["passed"],
        perf["passed"],
        body.get("payment_required_passed", False),
    ))
    result = {
        "url": url,
        "passed": endpoint_passed,
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
    """Lead-funnel CTA appended to every Action run."""
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
    if fail_on == "never":
        return 0
    summary = report["summary"]
    if fail_on == "critical":
        critical = 0
        for ep in report["endpoints"]:
            checks = ep["checks"]
            if not checks["manifest"]["passed"] or not checks["body_conformance"]["passed"]:
                critical += 1
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
        urls = parse_endpoints(endpoints_raw, workspace)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        log(f"failed to parse endpoints: {exc}")
        return 2
    if not urls:
        log("no endpoints to validate")
        return 2

    log(
        f"tier={tier}, threshold_p95_ms={threshold_ms}, endpoints={len(urls)}, "
        f"probe_method={probe_method}, strict_v2={strict_v2}, enhanced={'on' if api_key else 'off'}"
    )

    results = [
        validate_endpoint(
            u,
            threshold_ms,
            api_key,
            probe_method=probe_method,
            strict_v2=strict_v2,
        )
        for u in urls
    ]
    failures = sum(1 for r in results if not r["passed"])
    summary = {
        "endpoints_checked": len(results),
        "failures": failures,
        "all_passed": failures == 0,
        "threshold_p95_ms": threshold_ms,
        "tier": tier,
        "enhanced_enabled": bool(api_key),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "validator_version": "1.2.0",
        "probe_method": probe_method,
        "strict_v2": strict_v2,
    }
    report = {"summary": summary, "endpoints": results}

    # Ensure report directory exists.
    abs_report = os.path.abspath(report_path)
    os.makedirs(os.path.dirname(abs_report) or ".", exist_ok=True)
    with open(abs_report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    log(f"wrote report to {abs_report}")

    if tier == "pro":
        maybe_post_webhook(webhook_url, report)

    print_upsell(api_key_present=bool(api_key))

    return decide_exit_code(report, fail_on)


if __name__ == "__main__":
    sys.exit(main())
