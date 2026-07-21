# Strict v2 Mode Design Contract

Date: 2026-07-19
Source: GitHub issue #1
Scope: documentation/contract plus GitHub Action input wiring only. The
non-goals below describe the original contract-only task and predate the
strict-v2 implementation that landed in the same PR (validator logic,
`payment_required.py`, and `check_402_body`).

## Purpose

Strict v2 mode exists to produce reproducible x402 v2 verdicts for endpoint
operators and CI reviewers. A strict verdict must be tied to the response that
was actually probed, not to stale report state or a cached fixture.

The mode locks three requirements:

1. **Reproducible strict-v2 verdicts** - the same archived probe response and
   strict policy inputs must produce the same pass/fail, `failure_class`, and
   report fields.
2. **Fresh probe before verdict** - each strict verdict must perform a fresh
   unauthenticated probe and record `probed_at_utc` for the response used to
   decide the check.
3. **Raw response archive** - the report must retain enough raw HTTP response
   data to debug and reproduce the strict decision without re-probing.

## Issue framing

The Asterpay instance that motivated issue #1 was an endpoint drift example, not
the feature itself. Issue #1 tracks the strict-v2 mode contract and reporting
surface. Individual endpoint behavior may change over time; strict-v2 verdicts
must therefore be anchored to the fresh probe timestamp and archived response
from the run that produced them.

## Policy table

| Policy area | Default (`strict_v2=false`) | Strict (`strict_v2=true`) |
|---|---|---|
| Canonical v2 placement | Prefer `PAYMENT-REQUIRED` header when present; allow valid body-only legacy placement. | Require a valid v2 `PAYMENT-REQUIRED` header for a passing v2 verdict. |
| Body-only `PaymentRequired` | May pass via legacy/body path and report `legacy_placement=true`. | Must fail the strict v2 check with `failure_class=legacy_placement`. |
| Header/body mismatch | Header remains canonical; mismatch is reported. | Header remains canonical; mismatch is reported and must not be hidden by body fallback. |
| Probe freshness | Probe result is recorded by the existing report path. | A fresh unauthenticated probe is required immediately before verdict; record `probed_at_utc`. |
| Raw response archive | Optional implementation detail unless another check needs it. | Required in the report for the response that produced the verdict. |
| Report reproducibility | Best effort from normalized fields. | Reproducible from `strict_v2`, `probed_at_utc`, normalized verdict fields, and `raw_response`. |
| Action behavior | `strict-v2` defaults to `false`; existing behavior is unchanged. | User opts in with `strict-v2: 'true'`. |

## Failure class

`legacy_placement` is the strict-v2 `failure_class` for a response that only
publishes a decodable body `PaymentRequired` and does not publish a valid v2
`PAYMENT-REQUIRED` header.

Default mode may continue to report the same response as:

```json
{
  "channel": "body",
  "legacy_placement": true,
  "failure_class": null
}
```

Strict mode must instead report a failed strict-v2 verdict, preserving the
placement evidence:

```json
{
  "channel": "body",
  "legacy_placement": true,
  "failure_class": "legacy_placement"
}
```

## Raw response shape

When `strict_v2=true`, each endpoint verdict must archive the raw HTTP response
used for the strict v2 decision under the endpoint report. The stable shape is:

```json
{
  "strict_v2": true,
  "probed_at_utc": "2026-07-19T20:20:00Z",
  "raw_response": {
    "method": "GET",
    "url": "https://api.example.com/v1/resource",
    "status_code": 402,
    "headers": {
      "content-type": "application/json",
      "payment-required": "<base64 PaymentRequired>"
    },
    "body": "{\"accepts\":[]}",
    "body_truncated": false,
    "body_sha256": "hex-encoded-sha256-of-archived-body"
  }
}
```

Field requirements:

| Field | Type | Requirement |
|---|---|---|
| `strict_v2` | `bool` | Effective strict mode for this verdict. |
| `probed_at_utc` | ISO-8601 UTC string | Timestamp of the fresh probe whose response produced the verdict. |
| `raw_response.method` | `"GET" \| "POST"` | Probe method that produced the archived response. |
| `raw_response.url` | `string` | Final requested endpoint URL for the verdict. |
| `raw_response.status_code` | `int \| null` | HTTP status, or `null` if no HTTP response was received. |
| `raw_response.headers` | `object` | Response headers normalized to lowercase names. Secrets should be redacted if ever present. |
| `raw_response.body` | `string` | Archived response body text used for parsing, subject to implementation size limits. |
| `raw_response.body_truncated` | `bool` | `true` when `body` was truncated by the archive limit. |
| `raw_response.body_sha256` | `string \| null` | SHA-256 hex digest of the archived body text; `null` when no body was received. |

## Action input

The GitHub Action exposes strict mode as:

```yaml
with:
  strict-v2: 'true'
```

Contract:

- Input name: `strict-v2`
- Default: `false`
- Docker argument position: after `probe-method`
- Entrypoint environment export: `X402V_STRICT_V2`
- Accepted values for future validator logic: case-insensitive boolean strings
  such as `true`/`false`, `1`/`0`, and `yes`/`no`

Until validator logic is implemented, wiring this input must not change default
validation behavior.

## Non-goals for this contract task

These non-goals applied to the original contract-only documentation task.
They predate the implementation that landed in the same PR; that work
intentionally implements verdict logic and updates `payment_required.py` /
`check_402_body` to match this contract.

- Do not implement strict-v2 verdict logic.
- Do not modify `payment_required.py`.
- Do not modify `check_402_body` logic.
- Do not add endpoint-specific special cases for Asterpay or any other live
  instance.
