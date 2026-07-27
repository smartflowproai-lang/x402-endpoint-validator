"""Public package exports for the x402 conformance engine.

Layout:
    _engine.models     — Pydantic result types
    _engine.constants  — Module-level constants (regex patterns, header names)
    _engine.messages   — Actionable, human-readable error/warning messages
    _engine.checks     — Single-responsibility check functions
    _engine.auditor    — X402Auditor class (orchestrator)
"""

from x402_validator._engine.auditor import X402Auditor, run_audit
from x402_validator._engine.constants import (
    CAIP2_PATTERN,
    PAYMENT_HEADERS,
    CheckMode,
)
from x402_validator._engine.models import (
    AuditReport,
    BazaarResult,
    Caip2Result,
    CheckResult,
    JsonResilienceResult,
    ManifestResult,
    MarketplaceResult,
    ProductResult,
)


__all__ = [
    "X402Auditor",
    "run_audit",
    "AuditReport",
    "CheckResult",
    "ManifestResult",
    "Caip2Result",
    "JsonResilienceResult",
    "BazaarResult",
    "ProductResult",
    "MarketplaceResult",
    "CAIP2_PATTERN",
    "PAYMENT_HEADERS",
    "CheckMode",
]
