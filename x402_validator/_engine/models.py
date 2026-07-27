"""Pydantic models for x402 conformance check results.

Every check in the engine returns one of these typed result objects. The
discriminated ``check_name`` literal on each subclass lets downstream
consumers (CLI, MCP, dashboard) handle checks by type without resorting to
string matching.

Status values (literal ``Status``):
    PASS            — check satisfied all expectations.
    FAIL            — check found a defect that the endpoint must fix.
    CRITICAL_FAIL   — defect that makes downstream verification impossible
                      (e.g., 402 returning a primitive instead of an object).
    ERROR           — the check could not run (network, parsing, exception).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


Status = Literal["PASS", "FAIL", "CRITICAL_FAIL", "ERROR"]
CheckName = Literal[
    "manifest_discovery",
    "caip2_compliance",
    "json_resilience",
    "bazaar_compliance",
    "marketplace_products",
    "product_check",
]


class CheckResult(BaseModel):
    """Base result for any conformance check.

    Attributes:
        check_name: Stable identifier for the check (e.g., ``"manifest_discovery"``).
        status: One of ``PASS``/``FAIL``/``CRITICAL_FAIL``/``ERROR``.
        message: Single-line, actionable human-readable summary.
        details: Optional structured payload for programmatic consumers
                 (always JSON-serializable).
    """

    check_name: str
    status: Status
    message: str
    details: Optional[dict[str, Any]] = None


class ManifestResult(CheckResult):
    """Result for ``manifest_discovery`` — GET /.well-known/x402."""

    check_name: Literal["manifest_discovery"] = "manifest_discovery"


class Caip2Result(CheckResult):
    """Result for ``caip2_compliance`` — CAIP-2 network identifiers in headers/body."""

    check_name: Literal["caip2_compliance"] = "caip2_compliance"


class JsonResilienceResult(CheckResult):
    """Result for ``json_resilience`` — verifies HTTP 402 body is a JSON object."""

    check_name: Literal["json_resilience"] = "json_resilience"


class BazaarResult(CheckResult):
    """Result for ``bazaar_compliance`` — checks extensions.bazaar block shape."""

    check_name: Literal["bazaar_compliance"] = "bazaar_compliance"


class ProductResult(CheckResult):
    """Result for ``product_check`` — one endpoint per marketplace product."""

    check_name: Literal["product_check"] = "product_check"
    product_id: str = ""
    endpoint_url: str = ""


class MarketplaceResult(CheckResult):
    """Result for ``marketplace_products`` — catalog-wide x402 compliance."""

    check_name: Literal["marketplace_products"] = "marketplace_products"
    total_products: int = 0
    conformant_count: int = 0


class AuditReport(BaseModel):
    """Top-level report aggregating one or more checks for a single target.

    Attributes:
        target_url: URL the audit was run against.
        timestamp: UTC timestamp when the audit completed.
        overall_status: Worst status among all checks
                        (CRITICAL_FAIL > FAIL > ERROR > PASS).
        checks: List of all check results that ran.
        summary: One-line summary suitable for terminal output.
    """

    target_url: str
    timestamp: datetime
    overall_status: Status
    checks: list[CheckResult]
    summary: str
