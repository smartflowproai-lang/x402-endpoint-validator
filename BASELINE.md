# Baseline — functionality existing before any grant-funded work

Reference commit: `2ac965b4ee91` (2026-08-26). Everything listed here exists at that commit and is
**not** part of any grant-funded milestone; grant milestones are deltas from this baseline.

## Validator (validator.py, payment_required.py)
- Endpoint reachability check with method fallback and probe-attempt logging (RS-2: 401/403/429 count as alive).
- Manifest / discovery check with caching.
- HTTP 402 contract check: v2 canonical `PAYMENT-REQUIRED` header and legacy body-only JSON,
  channel detection (header / body / both), `x402Version` validation.
- Strict-v2 mode with fresh-probe response archive (redacted headers, archived bodies).
- Expect-mode verdict extraction (`expect=auto|…`) used by the golden-fixture corpus.
- p95 latency check against a configurable threshold.
- URL input validation (`validate_endpoint_url`): http/https only, private/link-local ranges rejected.
- Global request throttling (`X402V_MAX_RPS`).

## Test corpus & CI
- Golden-fixture corpus incl. edge cases (`l402_www_authenticate`, `legacy_placement`,
  `channel_mismatch`, `unknown_network`, `auth_gated`); 105 tests passing at baseline.
- One live fixture contributed by an external endpoint operator (PR #13, merged 2026-08-26).
- Bazaar-extension conformance check by an external contributor (PR #16, merged 2026-07-28).

## Distribution
- GitHub Action (Dockerfile + entrypoint) published and consumed by external workflows.
- Releases up to `v1.4.0` (tag parity `v1`/`v1.1.0` verified 2026-08-24).

## Explicitly NOT at baseline (examples of grant-funded deltas)
- Declarative versioned conformance profiles (targets-as-data) and clause-mapped CHANGELOG.
- Vendor-neutral CLI/container distribution beyond the Action.
- Batch mode with per-host caps, backoff, `RATE_LIMITED` verdict (PR #11 is unmerged, changes requested).
- Automated SSRF/security acceptance matrix as CI.
- Bounded reproducibility package, source manifests, dataset releases, methodology CI.
