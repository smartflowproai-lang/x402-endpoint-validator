# v2 PAYMENT-REQUIRED Header Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `validator.py` decode canonical x402 v2 `PAYMENT-REQUIRED` headers first so the 610 header-only corpus passes conformance, with channel reporting and header/body mismatch findings.

**Architecture:** Extract pure helpers into `payment_required.py` (decode, validate accepts, compare channels). Refactor `check_402_body` into a version-aware probe (GET then POST) that extracts requirements from header and/or body, applies Tom's precedence (header canonical; body-only = pass + `legacy_placement`), and emits channel + failure_class in the report. L402/WWW-Authenticate stays out of this check.

**Tech Stack:** Python 3, `requests`, stdlib `unittest` or `pytest` (prefer pytest if available; else unittest), GitHub Action unchanged except optional `probe-method` input later if needed.

## Global Constraints

- Spec: header is canonical HTTP transport for `PaymentRequired` (x402 transports-v2/http.md)
- Tom's #3 notes: (1) report `header`|`body`|`both`; mismatch on price/network/payTo is a finding; (2) header wins; body-only passes with legacy flag; (3) L402 separate — do not pass on WWW-Authenticate alone
- No live network in CI unit tests — golden fixtures only
- Do not expand scheme handlers beyond `exact` first-class / `upto` warning in this PR
- Link PR to issue #3
- Branch: `cursor/v2-payment-required-header-cb3d`

## File map

- Create: `payment_required.py` — pure decode/validate/compare
- Create: `tests/test_payment_required.py` — unit tests
- Create: `tests/test_check_402_integration.py` — mocked HTTP tests for probe
- Create: `tests/fixtures/*.json` — status/headers/body golden files
- Modify: `validator.py` — wire helpers into check + report fields
- Modify: `README.md` — document header channel + report fields
- Modify: `action.yml` only if new input needed (`probe-method`, default `auto`)

---

### Task 1: Golden fixtures from issue #3 corpus

**Files:**
- Create: `tests/fixtures/apinow_buzzwords.json`
- Create: `tests/fixtures/web3identity_blockcount.json`
- Create: `tests/fixtures/weatherxm_current.json`
- Create: `tests/fixtures/hugen_address.json`
- Create: `tests/fixtures/stabletravel_airports.json`
- Create: `tests/fixtures/body_only_v1_legacy.json` (synthetic)
- Create: `tests/fixtures/header_body_mismatch.json` (synthetic)
- Create: `tests/fixtures/l402_www_authenticate_only.json` (synthetic)

**Fixture schema:**
```json
{
  "name": "apinow_buzzwords",
  "url": "https://...",
  "method": "GET",
  "status": 402,
  "headers": {"payment-required": "<base64>", "...": "..."},
  "body": "{}",
  "expect": {
    "passed": true,
    "channel": "header",
    "legacy_placement": false,
    "failure_class": null
  }
}
```

- [ ] Capture live GETs for the five corpus URLs; redact nothing required for decode
- [ ] Hand-author synthetic fixtures for legacy body-only, mismatch, L402-only
- [ ] Commit fixtures only

---

### Task 2: Failing unit tests for `payment_required.py` (TDD RED)

**Files:**
- Create: `tests/test_payment_required.py`

**Interfaces to assert (produce these names):**
- `decode_payment_required_header(headers: dict[str, str]) -> dict | None`
- `extract_payment_required(status, headers, body_text) -> ExtractResult`
- `validate_accepts(obj: dict, *, source: str) -> ValidateResult`
- `compare_channels(header_obj, body_obj) -> list[str]` mismatch codes
- `ExtractResult`: dataclass with `channel` (`none|header|body|both`), `canonical` obj, `header_obj`, `body_obj`, `legacy_placement: bool`
- `ValidateResult`: `ok: bool`, `failure_class: str|None`, `schemes`, `networks`, `findings: list`

- [ ] Write tests covering: decode happy path; empty body header pass; body-only legacy; both agree; both disagree price/network/payTo; L402-only → not ok, failure_class `l402_www_authenticate`; CAIP-2 required on header/v2; `amount` vs `maxAmountRequired`
- [ ] Run tests — expect ImportError / fail
- [ ] Commit tests only

---

### Task 3: Implement `payment_required.py` (TDD GREEN)

**Files:**
- Create: `payment_required.py`

- [ ] Minimal implementation to pass Task 2 tests
- [ ] Commit

---

### Task 4: Probe integration + report fields

**Files:**
- Modify: `validator.py`
- Create: `tests/test_check_402_integration.py`

Behavior:
- Probe methods: auto = GET then POST; use first 402
- On 402: extract via helpers; validate canonical object
- Report under `checks.body_conformance` (keep key for compat) extras: `channel`, `probe_method`, `schemes`, `networks`, `failure_class`, `legacy_placement`, `channel_mismatch`, `caip2_in_header`
- `passed` true when payment required + canonical validates; channel_mismatch is warning finding but does not fail if header validates (mismatch listed in findings / `channel_mismatch: true`)
- Body-only: passed true, `legacy_placement: true`
- Neither: fail with appropriate failure_class

- [ ] Failing integration tests with responses mocked
- [ ] Implement wiring
- [ ] Commit

---

### Task 5: README + Action input + paranoid verification

**Files:**
- Modify: `README.md`, optionally `action.yml` / `entrypoint.sh`

- [ ] Document header-canonical behavior and new report fields
- [ ] Optional `probe-method` input: `auto|GET|POST` default `auto`
- [ ] Run full unit suite
- [ ] Live spot-check 5 corpus URLs with the new check (manual script, not CI)
- [ ] Push branch; open PR to upstream main referencing #3

---
