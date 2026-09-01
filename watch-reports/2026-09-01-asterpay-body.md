# Fixture watch report: asterpay body-channel drift, 2026-09-01

The daily corpus watch read status and response headers only. Two fixtures — `asterpay_crypto_prices` and `asterpay_sentiment` — declare `channel: "both"`, meaning the challenge is served in the `PAYMENT-REQUIRED` header *and* in the response body. Half of what those two fixtures claim was therefore never checked. This report records the measurement, the drift it found, and the re-capture that closed it.

- Run timestamps: `2026-09-01T16:50:52Z` (detection pass, corpus at `3955eb7`) and `2026-09-01T16:51:02Z` (verification pass, corpus at `a77de13`)
- Observer: SmartFlow Observatory corpus watch (`smartflowproai-lang/x402-endpoint-validator`)
- Method, per route: unpaid preflight using the fixture's own method and request body (no payment involved), then byte comparison of the returned `PAYMENT-REQUIRED` challenge against the stored value, status comparison against the captured status, and — new in this run — comparison of the body-side `PaymentRequired` for fixtures whose expected channel covers the body.

## Measurement before any change

Each of the two routes was fetched twice, two seconds apart, with the watch's own preflight (no payment, plain 402):

| route | fetch 1 vs fetch 2 | live header vs fixture | live body vs fixture |
|---|---|---|---|
| asterpay_crypto_prices | body and `PAYMENT-REQUIRED` byte-identical | identical (7224 B) | **differs** (7276 B → 7700 B) |
| asterpay_sentiment | body and `PAYMENT-REQUIRED` byte-identical | identical (5760 B) | **differs** (6210 B → 6634 B) |

Because both fetches returned identical bytes, this is seller drift, not a per-request field — the condition under which patching the fixture is the right move rather than a mistake.

One field *is* per-request and is worth recording so it is never mistaken for drift: `WWW-Authenticate` changes on every call (its `id` and `expires`). It is stored in these fixtures as snapshot metadata and is not compared, exactly like the `date` and request-id headers elsewhere in the corpus.

### Structural diff, both routes (identical on each)

Three keys added under `first_call_free`; nothing removed, no value changed, `accepts[]` untouched, top-level key order unchanged:

```
+ first_call_free.requires_balance            true
+ first_call_free.requires_balance_note       "Your wallet must hold at least the endpoint price for your
                                               x402/MPP client to sign the authorization. AsterPay verifies
                                               but does not settle it, so nothing is deducted."
+ first_call_free.zero_balance_alternative    "No wallet balance at all? Every endpoint under freeEndpoints
                                               below answers with no payment and no signature."
```

The seller documented a precondition of its own first-call-free offer — the caller still needs a non-zero balance for the client to sign the authorization — and pointed zero-balance callers at its free endpoints. It is a documentation change in the quote, not a change in payment terms. That is precisely why the header did not move: the compact `PAYMENT-REQUIRED` challenge carries `accepts[]` and the bazaar extension, while `first_call_free`, `mpp`, `howToPay` and `example_response` live in the body only. A header-only watch cannot see this class of change at all.

## Detection pass (16:50Z, corpus at `3955eb7` — watch patched, fixtures not yet re-captured)

| fixture | live status | challenge | body | capture reference |
|---|---|---|---|---|
| apinow_buzzwords | 402 | match | n/a | git history 2026-07-19 |
| asterpay_crypto_prices | 402 | match | **DRIFT** | captured_at_utc 2026-07-19 |
| asterpay_sentiment | 402 | match | **DRIFT** | captured_at_utc 2026-07-19 |
| hugen_address | 402 | match | n/a | git history 2026-07-19 |
| stabletravel_airports | 402 | match | n/a | captured_at_utc 2026-08-31 |
| terradeed_scrape | 402 | match | n/a | captured_at_utc 2026-08-26 |
| viridis_ghg_ledger | 402 | match | n/a | capture_date 2026-07-26 |
| viridis_regulatory_radar | 402 | match | n/a | captured_at 2026-07-26 |
| weatherxm_current | 402 | match | n/a | git history 2026-07-19 |
| web3identity_blockcount | 402 | match | n/a | git history 2026-07-19 |

**Detection pass: 8/10, 2 findings.** `body` is `n/a` for the eight fixtures whose expected channel is `header`: they make no body claim, so their live body is not compared and cannot be drift.

Re-captured in `a77de13`.

## Verification pass (16:51Z, corpus at `a77de13`)

**10/10 fully matched, 0 findings.**

## Blindness guard

The same review raised a second defect, unrelated to asterpay: `git ls-tree` exits 0 with empty stdout for a path that does not exist (verified: `git ls-tree --name-only origin/main tests/nonexistent_path/` → exit 0, 0 bytes). If `tests/fixtures/` were ever moved or renamed, the watch would have derived an empty route list, logged `0/0 fully matched, 0 finding(s)` and exited 0 — blindness reported as a clean run, indefinitely and silently.

Verified end to end against a scratch clone whose `origin/main` had `tests/fixtures/` renamed to `tests/golden/`:

```
[2026-09-01T16:51:20Z] FINDING: route list empty (fixtures path missing?) - git ls-tree returned no tests/fixtures/*.json on origin/main
EXIT CODE: 2
```

The alert fires, and the blind run leaves the previous `state.json` untouched rather than overwriting ten known-good routes with nothing.

## Scope note

Both channels of a `both` fixture are live claims and are now checked independently — neither result shadows the other, so a route can report `challenge_match=True body_match=False`, which is exactly what happened here. The header is still compared byte-for-byte. The body is compared as the object `payment_required.extract_payment_required()` pulls out of it — the same extraction the validator and the fixture tests run — rather than as raw bytes: the parser never sees key order or whitespace, so re-serialisation is not drift, while an added, removed or changed field is. Synthetic fixtures (constructed bazaar cases, `example.test` hosts) remain excluded automatically.

The two runs above were executed against a scratch clone of this repository whose `origin/main` pointed at the local commits, because the fix has not been pushed at the time of writing. That is the only difference from the scheduled 06:25 UTC run; the route list, the network calls and the comparisons are identical.

## Raw state (verification pass)

```json
{
  "checked_at": "2026-09-01T16:51:02+00:00",
  "origin_main": "a77de13",
  "routes": {
    "apinow_buzzwords":        {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "git_history"},
    "asterpay_crypto_prices":  {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "both", "body_match": true, "capture_field": "captured_at_utc", "capture_value": "2026-09-01T16:49:58Z"},
    "asterpay_sentiment":      {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "both", "body_match": true, "capture_field": "captured_at_utc", "capture_value": "2026-09-01T16:49:58Z"},
    "hugen_address":           {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "git_history"},
    "stabletravel_airports":   {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "captured_at_utc", "capture_value": "2026-08-31T18:51:19Z"},
    "terradeed_scrape":        {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "captured_at_utc", "capture_value": "2026-08-26T18:16:35Z"},
    "viridis_ghg_ledger":      {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "capture_date", "capture_value": "2026-07-26"},
    "viridis_regulatory_radar":{"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "captured_at", "capture_value": "2026-07-26T16:47:37+00:00"},
    "weatherxm_current":       {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "git_history"},
    "web3identity_blockcount": {"live_status": 402, "status_match": true, "challenge_match": true, "expect_channel": "header", "body_match": null, "capture_field": "git_history"}
  }
}
```
