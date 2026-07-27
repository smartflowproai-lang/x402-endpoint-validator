# Changelog

All notable changes to x402-validator are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com). This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Quality refactor

The conformance engine was split from a single 670-line file into a
focused package of single-responsibility modules. No behaviour change
intended; observable output and CLI are identical.

- Engine refactored into the `x402_validator._engine` *package* with:
  - `auditor.py` — `X402Auditor` and `run_audit` orchestration.
  - `checks.py` — one async function per check (`check_manifest`,
    `check_caip2`, `check_json_resilience`, `check_bazaar`,
    `check_marketplace`, `check_product_endpoint`).
  - `constants.py` — `CAIP2_PATTERN`, `PAYMENT_HEADERS`, `CheckMode`.
  - `models.py` — Pydantic result classes (`CheckResult`,
    `ManifestResult`, `Caip2Result`, `JsonResilienceResult`,
    `BazaarResult`, `ProductResult`, `MarketplaceResult`, `AuditReport`).
  - `messages.py` — centralised, actionable human-readable strings.
- Legacy `x402_conformance_engine.py` removed (was a 428-line duplicate of
  the published engine structure).
- `tests/test_engine.py` introduced (60 kB, 118 tests). 100 % line
  coverage of `x402_validator/_engine/`.
- `tests/test_bazaar_checker.py`, `tests/test_marketplace.py`,
  `tests/test_ecosystem_checks.py`,
  `tests/test_x402_conformance_engine.py` removed (tested the legacy
  module that no longer exists).
- `docs/API.md` — exhaustive specification of every public function and
  result type.
- `docs/DESIGN.md` — what the engine does, what it doesn't, and why.
- `docs/VALIDATION_REPORT_v0.3.md` — 27 endpoints audited in 5.2 s.
- `CONTRIBUTING.md` rewritten in English with explicit rules for adding
  checks without breaking the contract.
- `x402_validator/cli.py::audit_command` now accepts `output` as either
  `list[str]` or `str` (backward compatible with previous single-string
  callers).
- `X402Auditor` constructor accepts an optional `transport=` for
  `httpx.MockTransport` (used in tests).
- Error messages now include operator-actionable remediation text in
  every `FAIL` and `CRITICAL_FAIL`.

## [0.2.0] — 2026-07-25

Initial PyPI release. Manifest discovery, CAIP-2 compliance, JSON
resilience, bazaar compliance; `--mode marketplace` for multi-product
catalogs; MCP server and CLI.
