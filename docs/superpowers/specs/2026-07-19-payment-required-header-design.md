# PAYMENT-REQUIRED Header Channel Design Contract

Date: 2026-07-19
Source: GitHub issue #3 plus Tom Smart's confirmation comment
Scope: documentation/contract only. This document does not authorize implementing
`payment_required.py` or rewriting `validator.py` check logic in this task.

## Locked design

### Canonical channel

For x402 v2 HTTP transport, the canonical wire location for the
`PaymentRequired` object is the `PAYMENT-REQUIRED` response header. The header
value is base64-encoded JSON.

The validator's v2 conformance path must read `PAYMENT-REQUIRED` first. Response
bodies remain a legacy/body-path source, not the canonical v2 source.

### Channel reporting

Each endpoint verdict must report where a decodable `PaymentRequired` object was
found:

- `header`
- `body`
- `both`

If no `PaymentRequired` object is decoded, the check fails with a stable
`failure_class` rather than inventing a passing channel.

### Header/body precedence and mismatches

When both header and body are present:

- The header wins as canonical.
- The body is still parsed for comparison.
- A mismatch between header and body on any of these fields is a finding:
  - `amount`
  - `network`
  - `payTo`

The mismatch finding is valuable even when the canonical header validates,
because it identifies a merchant publishing conflicting payment quotes across
channels.

### Body-only legacy behavior

Body-only x402 responses continue to pass when the body validates under the
legacy/body rules. They must be reported with:

- `channel: "body"`
- `legacy_placement: true`

This preserves v1-to-v2 transition compatibility while making the placement
visible in reports.

### L402 / WWW-Authenticate

L402 or Lightning-style `WWW-Authenticate` payment challenges are not part of
the v2 `PAYMENT-REQUIRED` pass path.

If a response has only a `WWW-Authenticate` payment dialect and no decodable
JSON `PaymentRequired` in `PAYMENT-REQUIRED` or body, it should fail this check
with a separate `failure_class` such as `l402_www_authenticate`. A future L402
check may define its own verdict vocabulary.

### Probe method

The default probe method is `auto`:

1. Try `GET`.
2. If no usable `402 Payment Required` response is found, try `POST`.
3. Use the first `402` response for the conformance verdict.

Explicit `GET` or `POST` configuration may force a single probe method. Reports
must record the method that produced the verdict.

## Report fields

The compatibility key remains `checks.body_conformance`, even though the check
now evaluates the canonical header channel first.

Add these fields under `checks.body_conformance`:

| Field | Type | Meaning |
|---|---|---|
| `channel` | `"header" | "body" | "both" | null` | Source of the decoded `PaymentRequired`; `null` only when extraction fails. |
| `probe_method` | `"GET" | "POST" | null` | HTTP method whose response produced the verdict. |
| `schemes` | `list[str]` | Unique schemes observed in the canonical `accepts[]`. |
| `networks` | `list[str]` | Unique networks observed in the canonical `accepts[]`. |
| `failure_class` | `str | null` | Machine-stable failure class, or `null` on pass. |
| `legacy_placement` | `bool` | `true` when a body-only response passes via the legacy path. |
| `channel_mismatch` | `bool` | `true` when header and body both exist but disagree on amount, network, or `payTo`. |
| `channel_mismatch_fields` | `list["amount", "network", "payTo"]` | Fields that differ between header and body. Empty when there is no mismatch. |
| `caip2_in_header` | `bool` | `true` when the canonical header contains CAIP-2 network identifiers. |

Recommended `failure_class` values from issue #3:

| `failure_class` | Meaning |
|---|---|
| `header_only_accepts` | 402 response where the body has no `accepts[]` and no decodable v2 header was available. |
| `v2_header_invalid` | `PAYMENT-REQUIRED` was present but could not be decoded or failed v2 schema validation. |
| `amount_key` | `accepts[]` was present but the price key did not match the detected version/channel policy. |
| `network_format` | Network was present but failed the detected version/channel network policy. |
| `scheme_unsupported` | Scheme is outside the configured support policy. |
| `method_mismatch` | A 402 is available only on a method not used by an explicit probe configuration. |
| `l402_www_authenticate` | L402/Lightning `WWW-Authenticate` dialect without a JSON `PaymentRequired`. |
| `undecided` | Unreachable, non-402, or otherwise unclassifiable response. |

## Acceptance fixtures from issue #3

| Fixture | Source evidence | Expected verdict |
|---|---|---|
| `apinow_buzzwords` | 402; body `{}`; header v2 `exact`, `eip155:8453`, `amount` | Pass, `channel=header`, `legacy_placement=false` |
| `web3identity_blockcount` | 402; custom body; header v2 `exact`, `eip155:8453`, `amount` | Pass, `channel=header`, `legacy_placement=false` |
| `weatherxm_current` | 402; body `{}`; header v2 `exact`, `eip155:8453`, `amount` | Pass, `channel=header`, `legacy_placement=false` |
| `hugen_address` | 402; sample body; header v2 multi-accept on Base and Solana | Pass, `channel=header`, both networks recorded |
| `stabletravel_airports` | 402; empty body; header v2 multi-accept plus separate `WWW-Authenticate` Payment dialect | Pass on v2 header, `channel=header`; note extra dialect without failing |
| `lightning_l402_only` | `WWW-Authenticate` payment dialect only; no JSON `PaymentRequired` | Fail, `failure_class=l402_www_authenticate` |
| `body_only_v1_legacy` | Body-only v1 with `maxAmountRequired` and `network: base` | Pass, `channel=body`, `legacy_placement=true` |
| `header_body_mismatch` | Header and body both decode but disagree on amount, network, or `payTo` | Pass only if canonical header validates; emit mismatch finding and `channel_mismatch=true` |
| `asterpay_body_caip2` | Body path with CAIP-2 network from issue #1 context | Pass once strict-v2/channel network policy is agreed |

## Non-goals for this contract task

- Do not implement settlement or pay endpoints.
- Do not implement `payment_required.py`.
- Do not rewrite `validator.py` check logic yet.
- Do not fold L402 / `WWW-Authenticate` into the v2 header pass path.
- Do not expand scheme support beyond the existing `exact` first-class contract in
  this documentation pass.
