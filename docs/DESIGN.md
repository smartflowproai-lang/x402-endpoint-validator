# x402 Validator — Design

This document records the *why* of the engine. For the *what*, see [`API.md`](API.md).
For the *how*, read the source. If you change behaviour, update this file.

---

## Goals

A conformance engine that:

1. **Reports ground truth.** Every `PASS` means the operator can rely on it; every
   `FAIL`/`CRITICAL_FAIL` is specific enough to fix without re-reading the spec.
2. **Never raises on broken endpoints.** HTTP errors, malformed JSON, and
   missing fields become typed results, not exceptions.
3. **Is small enough to read in an hour.** Each check fits on one screen.
4. **Is testable without mocks or a network.** `httpx.MockTransport` is enough.

## Non-goals

- Settlement verification (transport of funds, on-chain checks).
- Authentication / authorisation beyond public discovery.
- Generating payment payloads (we only *inspect*).
- Reading the spec lock-in version 2; legacy v1 fixtures are tolerated but
  not optimised for.

---

## Architecture

```
x402_validator/_engine/
├── __init__.py      ← public re-exports only (4 lines)
├── auditor.py       ← X402Auditor + run_audit — orchestration
├── checks.py        ← check_manifest, check_caip2, check_json_resilience,
│                      check_bazaar, check_marketplace, check_product_endpoint
├── constants.py     ← regex patterns, header names, mode labels
├── models.py        ← Pydantic result types (one class per check)
└── messages.py      ← human-readable, actionable error/warning strings
```

Each file has a single responsibility. The auditor is the only place where
multiple checks are coordinated.

---

## Design choices

### One function per check

Every check is a `async def` that returns a result. They don't know about
each other. The auditor wires them together.

**Pro:** tests are pure unit tests against typed inputs.
**Con:** if you want to add a check that depends on another check's output
(e.g. "skip bazaar if manifest fails"), wire it in `X402Auditor`, not in
`checks.check_*`.

### Pydantic for result types

Status is a `Literal["PASS","FAIL","CRITICAL_FAIL","ERROR"]`, not an enum,
so it's JSON-serialisable without custom converters. The `check_name`
Literal on each subclass is the discriminator for routing.

**Pro:** a downstream consumer can dispatch on `type(result)` directly.
**Con:** adding a fifth status (e.g., `WARN`) is a breaking change to
the Literal and requires updating every result model.

### Status uses words, not numbers

`PASS` / `FAIL` / `CRITICAL_FAIL` / `ERROR`, ordered by severity:

```
CRITICAL_FAIL > FAIL > ERROR > PASS
```

`X402Auditor._worst_status` enforces this. If you copy a result into CSV,
the column type matches the model's enum and stays string-sortable.

### Messages are centralised

`messages.py` builds every human-readable message. Checks never inline a
string. Two reasons:

1. A change in tone is one diff, not many.
2. Tests can assert on the *exact* string operators will see.

### Errors never raise

The auditor never propagates an `httpx` exception to the caller. Every
transport-level failure becomes a `status=ERROR` result with a human
message. This is enforced by the helper `_safe_get` and the per-check
try/except blocks.

**Why:** endpoints under audit *will* be broken. Treating breakage as an
exception would force every caller to wrap the auditor in `try/except`,
defeating the point of typed results.

### Manifest discovery is mandatory

Every audit hits `GET {base}/.well-known/x402`. There is no skip flag,
because if the manifest is missing or wrong, the spec compliance story is
already broken.

### CAIP-2 enforcement is regex-only

The CAIP-2 spec defines more than just `<namespace>:<reference>`. We
intentionally keep our regex loose (`^[a-z0-9-]+:[a-zA-Z0-9_-]+$`) so
future networks (e.g. `tron:mainnet`) don't require a validator update.

**Risk:** a garbage string passes the regex but isn't a real network. We
call this out in the FAIL message, e.g. `"network 'XYZ' is not a valid
CAIP-2 identifier"`. The author of the endpoint decides what is canonical.

### `chainId` accepted as `network` alias

Some implementations predate the formal spec. `payment_required.py` (the
v2 header validator used alongside this engine) accepts both.

### MockTransport is the test harness

Every check is exercised through `httpx.MockTransport`, not by hitting a
real server. This makes the test suite deterministic and ~500ms.

### 100% line coverage is enforced

Tests assert every branch in the engine. If you add a branch, add a test.

---

## What's NOT in this engine

These concerns live in `MSSATANASS/x402-validator-tools` (separate repo):

- Dashboard / web UI (Flask)
- Server endpoint exposing audit as a paid API (Stripe)
- Proxy middleware that injects Payment-Required headers
- Container images / CI workflows
- Bulk PDF / report generation

The core repo here is intentionally small (one auditor, one CLI, one
MCP server) so operators can vendor it as a single dependency.

---

## History

- **v0.1.0**: Single-endpoint only, four checks.
- **v0.2.0**: Marketplace mode + cleaner error messages.
- **v0.3.0** (current): Modular package, 100% coverage, full docstrings.

Future: when settlement verification becomes cheap, add a `check_settlement`
function without touching existing checks.
