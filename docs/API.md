# x402 Validator — API Reference

The conformance engine has a single public surface:

```
async with X402Auditor() as auditor:
    report = await auditor.run_full_audit(url, mode="standard")
```

This document is the **ground truth** for every public function, every result type, and every status value. If behaviour here disagrees with code, **fix the code** or **fix this doc** — never both silently.

---

## Audit modes

| Mode            | Checks run                                                            | When to use                                  |
|-----------------|-----------------------------------------------------------------------|----------------------------------------------|
| `"standard"`    | manifest, CAIP-2, JSON resilience, bazaar                             | Single-endpoint audit (default)              |
| `"marketplace"` | the four above + `marketplace_products` + per-product checks + bazaar | Multi-product catalog audit                  |

A `mode` value not in this set raises `ValueError`.

---

## Result hierarchy

Every check returns a `CheckResult` subclass. The discriminator `check_name`
lets callers route by type without string checks on `details`.

### `CheckResult` (base)

| Field        | Type                              | Meaning                                         |
|--------------|-----------------------------------|-------------------------------------------------|
| `check_name` | `str`                             | Stable identifier, e.g. `"manifest_discovery"`  |
| `status`     | `Literal["PASS","FAIL","CRITICAL_FAIL","ERROR"]` | One word summary                       |
| `message`    | `str`                             | Human-readable, actionable summary              |
| `details`    | `Optional[dict[str, Any]]`        | Typed payload for programmatic consumers        |

#### Status precedence (`X402Auditor._worst_status`)

```
CRITICAL_FAIL  >  FAIL  >  ERROR  >  PASS
```

When aggregating checks for an `AuditReport`, the highest-precedence status wins.

### `ManifestResult` (`check_name = "manifest_discovery"`)

Probes `GET {base_url}/.well-known/x402`.

| `status`           | When                                                          |
|--------------------|---------------------------------------------------------------|
| `PASS`             | 200, valid JSON object, has `accepts` or non-empty `products` |
| `FAIL`             | 404, non-JSON, primitive body, missing both keys              |
| `ERROR`            | Timeout, connection refused, or other transport failure        |

### `Caip2Result` (`check_name = "caip2_compliance"`)

Probes payment headers on the target URL:

- `payment-required`
- `x-payment-required` (alias)
- `x-402-accepts`
- `www-authenticate` (only when prefixed with `X402 `)

Each is expected to be `base64(JSON)` with a `network` field in
CAIP-2 form. The first header that decodes AND pattern-matches wins.

| `status` | When                                                |
|----------|-----------------------------------------------------|
| `PASS`   | At least one valid CAIP-2 network found             |
| `FAIL`   | None found, or all found headers malformed/invalid  |

CAIP-2 regex (from `_engine.constants`):

```
^[a-z0-9-]+:[a-zA-Z0-9_-]+$
```

Examples accepted: `eip155:1`, `eip155:8453`, `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`.
Examples rejected: `8453` (no namespace), `EIP155:8453` (uppercase), `eip155:` (empty chain).

### `JsonResilienceResult` (`check_name = "json_resilience"`)

Probes the endpoint itself.

| `status`         | When                                                                  |
|------------------|-----------------------------------------------------------------------|
| `PASS`           | Endpoint returns non-402 OR 402 body is a JSON object                 |
| `CRITICAL_FAIL`  | 402 body is a JSON primitive (string/number/array/null) or non-JSON   |
| `ERROR`          | Timeout, connection refused, or other transport failure               |

### `BazaarResult` (`check_name = "bazaar_compliance"`)

Static check on the HTTP 402 response body for the `extensions.bazaar` block.

Required fields:

| Field         | Type                | Constraint                                       |
|---------------|---------------------|--------------------------------------------------|
| `method`      | `str`               | Must be `"POST"` exactly                         |
| `serviceName` | `str`               | Non-empty after `str.strip()`                    |
| `tags`        | `list[str]`         | At least one entry                               |

| `status` | When                                                              |
|----------|-------------------------------------------------------------------|
| `PASS`   | All three fields valid, including when no 402 body (skip = pass)  |
| `FAIL`   | Block missing, or any required field missing/invalid             |

### `MarketplaceResult` (`check_name = "marketplace_products"`)

Catalog-level check (only in `marketplace` mode). For each product in
`manifest["products"]`, validates:

- `x402.scheme == "exact"`
- `x402.network` matches CAIP-2
- `x402.pay_to` or `payTo` is set
- `x402.facilitator_url` is set
- `method` (if specified) is `"GET"`

| `status` | When                                |
|----------|-------------------------------------|
| `PASS`   | All products conformant             |
| `FAIL`   | One or more products non-conformant |

### `ProductResult` (`check_name = "product_check"`)

Per-endpoint probe inside marketplace mode.

| `status` | Case                                                            |
|----------|-----------------------------------------------------------------|
| `PASS`   | Free product returns 200 OR paid returns 402 with header        |
| `FAIL`   | Paid returns non-402, or 402 missing `Payment-Required` header  |
| `ERROR`  | Transport failure                                               |

### `AuditReport` (top-level)

Aggregate result of all checks for one target.

| Field            | Type     | Notes                                                      |
|------------------|----------|------------------------------------------------------------|
| `target_url`     | `str`    | The URL audited                                            |
| `timestamp`      | `datetime` | UTC, when audit finished                                 |
| `overall_status` | `AuditReport.status` | Worst check status                              |
| `checks`         | `list[CheckResult]`  | All results (4 in standard, more in marketplace) |
| `summary`        | `str`    | One-line summary like `"3/4 checks passed. Overall: FAIL"` |

---

## Functions

### `check_manifest(client, base_url) -> ManifestResult`

GET `base_url/.well-known/x402`. Verifies:

1. HTTP 200
2. Body parses as JSON object
3. Body has `accepts` (list) or non-empty `products` (list)

Network failures → `status=ERROR` (never raises).

### `check_caip2(client, target_url) -> Caip2Result`

Probes `target_url` for payment headers. Decodes each candidate as
`base64(JSON)` and validates the `network` field against the CAIP-2 regex.
First match wins.

### `check_json_resilience(client, endpoint_url) -> JsonResilienceResult`

GET `endpoint_url`. If status is 402, verifies the body is a JSON object
(not a primitive or non-JSON text).

### `check_bazaar(response_body) -> BazaarResult`

Pure function (no I/O). Validates an HTTP 402 body for the `extensions.bazaar` block.

Pass `None` to skip the check (returns `PASS` with "skipped" message).

### `check_bazaar_for_url(client, target_url) -> BazaarResult`

Convenience wrapper: `GET target_url`, extract 402 body, run `check_bazaar`.

### `check_marketplace(client, base_url, manifest_payload) -> MarketplaceResult`

Validate each product in `manifest_payload["products"]`.

### `check_product_endpoint(client, base_url, product) -> ProductResult`

Probe `{base_url}{product["endpoint"]}`. Free products should return 200,
paid products should return 402 + `Payment-Required` header.

### `run_audit(url, *, timeout=10.0, mode="standard", transport=None) -> AuditReport`

One-shot entry point.

```python
import asyncio
from x402_validator._engine import run_audit

async def main():
    report = await run_audit("https://observer.137-184-67-179.sslip.io")
    print(report.summary)

asyncio.run(main())
```

### `X402Auditor` class

Use as an async context manager:

```python
async with X402Auditor(timeout=15.0, default_headers={"User-Agent": "x402-validator"}) as auditor:
    report = await auditor.run_full_audit("https://example.com", mode="marketplace")
```

Constructor parameters:

| Parameter           | Type                          | Default | Purpose                                  |
|---------------------|-------------------------------|---------|------------------------------------------|
| `timeout`           | `float`                       | `10.0`  | Per-request timeout (seconds)            |
| `default_headers`   | `Optional[dict[str, str]]`    | `None`  | Headers applied to every request         |
| `follow_redirects`  | `bool`                        | `True`  | Whether httpx follows 3xx                |
| `transport`         | `Optional[httpx.AsyncBaseTransport]` | `None` | Inject custom transport (testing)  |

Public methods:

| Method                            | Returns       | Notes                                       |
|-----------------------------------|---------------|---------------------------------------------|
| `__aenter__` / `__aexit__`        | —             | Manages the underlying `httpx.AsyncClient`  |
| `run_full_audit(url, mode=...)`   | `AuditReport` | Aggregates all relevant checks              |

---

## Constants

```python
from x402_validator._engine import (
    CAIP2_PATTERN,    # re.Pattern[str] — CAIP-2 regex
    PAYMENT_HEADERS,  # tuple[str, ...] — probed in priority order
    CheckMode,        # class with .STANDARD, .MARKETPLACE, .ALL
)
```

---

## Error semantics

| Network class             | Handling                                         |
|---------------------------|--------------------------------------------------|
| `httpx.TimeoutException`  | Resolved to `status=ERROR` (or `status=FAIL` for `check_caip2`) |
| `httpx.ConnectError`      | Same                                            |
| `httpx.HTTPError` and subclasses | Same (for `_safe_get` consumers)        |
| Any other `Exception`     | Caught and surfaced as `status=ERROR`            |

No check function ever raises — all exceptions become typed results.
