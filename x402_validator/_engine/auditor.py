"""Top-level orchestrator: ``X402Auditor`` runs checks against a target URL.

This class is the public entry point. It holds the httpx client lifecycle
(via async context manager) and composes individual check functions from
``_engine.checks`` into a full audit report.

Two audit modes:

    standard    — runs the four core checks:
                    1. manifest discovery
                    2. CAIP-2 compliance
                    3. JSON resilience
                    4. Bazaar compliance

    marketplace — runs the four standard checks PLUS:
                    5. catalog-level product conformance
                    6. one ``product_check`` per endpoint declared in catalog
                    7. one ``bazaar_compliance`` per paid endpoint walked

Each check returns its own result; this class aggregates them into an
``AuditReport``. The status precedence is CRITICAL_FAIL > FAIL > ERROR > PASS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final, Literal

import httpx

from x402_validator._engine.checks import (
    check_bazaar,
    check_bazaar_for_url,
    check_caip2,
    check_json_resilience,
    check_manifest,
    check_marketplace,
    check_product_endpoint,
)
from x402_validator._engine.constants import (
    CAIP2_PATTERN,
    CheckMode,
    MANIFEST_PATH_SUFFIX,
)
from x402_validator._engine.models import (
    AuditReport,
    Caip2Result,
    CheckResult,
)


_STATUS_PRIORITY: Final[dict[str, int]] = {
    "PASS": 0,
    "ERROR": 1,
    "FAIL": 2,
    "CRITICAL_FAIL": 3,
}


class X402Auditor:
    """Asynchronous auditor for x402 endpoint conformance.

    Use as an async context manager::

        async with X402Auditor() as auditor:
            report = await auditor.run_full_audit("https://example.com")

    Or call ``run_audit`` directly, which constructs and closes the client
    for you (handy in scripts).
    """

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        default_headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Construct an auditor.

        Args:
            timeout: HTTP request timeout (seconds).
            default_headers: Headers applied to every request.
            follow_redirects: Whether the httpx client follows 3xx redirects.
            transport: Optional httpx transport (used by tests with
                       ``httpx.MockTransport``); ignored in production.
        """
        self._timeout = timeout
        self._default_headers = dict(default_headers or {})
        self._follow_redirects = follow_redirects
        self._explicit_transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "X402Auditor":
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers=self._default_headers,
            follow_redirects=self._follow_redirects,
            transport=self._explicit_transport,
        )
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Convenience entry points
    # ------------------------------------------------------------------

    async def run_full_audit(
        self,
        target_url: str,
        mode: Literal["standard", "marketplace"] = CheckMode.STANDARD,
    ) -> AuditReport:
        """Run the full audit suite for ``target_url`` and return the report.

        Args:
            target_url: Base URL of the endpoint under audit.
            mode: ``"standard"`` (4 base checks) or ``"marketplace"``
                  (adds product-by-product walk + per-product bazaar).

        Raises:
            RuntimeError: if the auditor is not used as a context manager.
            ValueError: if ``mode`` is not a recognized value.
        """
        if self._client is None:
            raise RuntimeError(
                "X402Auditor must be used as 'async with X402Auditor() as auditor'"
            )
        if mode not in CheckMode.ALL:
            raise ValueError(
                f"mode must be one of {CheckMode.ALL}; got {mode!r}"
            )

        started = datetime.now(timezone.utc)
        checks: list[CheckResult] = []

        # 1) Manifest discovery
        checks.append(await check_manifest(self._client, target_url))

        # 2) CAIP-2 compliance (probes response headers)
        checks.append(await check_caip2(self._client, target_url))

        # 3) JSON resilience on a 402 response (skipped if not 402)
        checks.append(await check_json_resilience(self._client, target_url))

        # 4) Bazaar compliance (skipped if no 402 body)
        checks.append(await check_bazaar_for_url(self._client, target_url))

        # 5..7) Marketplace-only checks
        if mode == CheckMode.MARKETPLACE:
            await self._run_marketplace_checks(target_url, checks)

        # Aggregate
        overall = self._worst_status(checks)
        passed = sum(1 for c in checks if c.status == "PASS")
        total = len(checks)
        summary = f"{passed}/{total} checks passed. Overall: {overall}"

        return AuditReport(
            target_url=target_url,
            timestamp=started,
            overall_status=overall,
            checks=checks,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Marketplace helpers (private)
    # ------------------------------------------------------------------

    async def _run_marketplace_checks(
        self, target_url: str, checks: list[CheckResult]
    ) -> None:
        """Append marketplace + per-product results to ``checks`` in-place."""
        assert self._client is not None  # enforced by caller
        manifest_url = target_url.rstrip("/") + MANIFEST_PATH_SUFFIX
        try:
            manifest_payload = (await self._client.get(manifest_url)).json()
        except Exception:
            manifest_payload = {}

        if not isinstance(manifest_payload, dict):
            manifest_payload = {}

        checks.append(
            await check_marketplace(self._client, target_url, manifest_payload)
        )

        products = manifest_payload.get("products", [])
        if not isinstance(products, list):
            return

        for product in products:
            if not isinstance(product, dict):
                continue
            pr = await check_product_endpoint(self._client, target_url, product)
            checks.append(pr)

            # Per paid product: also probe bazaar on the endpoint itself.
            if pr.status == "PASS" and product.get("x402"):
                endpoint = str(product.get("endpoint", "") or "")
                if endpoint:
                    full = target_url.rstrip("/") + endpoint + "/"
                    body = await self._fetch_402_body(full)
                    bz = check_bazaar(body)
                    bz.check_name = f"bazaar_{product.get('id', 'unknown')}"
                    checks.append(bz)

        # If manifest declares a top-level network, also check it
        manifest_network = manifest_payload.get("network")
        if (
            isinstance(manifest_network, str)
            and manifest_network
            and CAIP2_PATTERN.match(manifest_network)
        ):
            checks.append(
                Caip2Result(
                    status="PASS",
                    message=f"CAIP-2 network from manifest declaration: {manifest_network}",
                    details={
                        "header_present": True,
                        "header_name": "manifest.network",
                        "caip2_value": manifest_network,
                        "valid": True,
                    },
                )
            )

    async def _fetch_402_body(self, url: str) -> dict[str, Any] | None:
        """GET ``url``; return its 402 body if a dict, else None."""
        assert self._client is not None
        try:
            response = await self._client.get(url)
            if response.status_code != 402:
                return None
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Aggregation helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _worst_status(checks: list[CheckResult]) -> str:
        if not checks:
            return "PASS"
        worst = max(checks, key=lambda c: _STATUS_PRIORITY.get(c.status, 0))
        return worst.status


# ---------------------------------------------------------------------------
# Module-level convenience entry point
# ---------------------------------------------------------------------------


async def run_audit(
    url: str,
    *,
    timeout: float = 10.0,
    mode: Literal["standard", "marketplace"] = CheckMode.STANDARD,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AuditReport:
    """One-shot audit helper: builds an auditor, runs, closes.

    Equivalent to::

        async with X402Auditor(timeout=timeout, transport=transport) as auditor:
            return await auditor.run_full_audit(url, mode=mode)

    Args:
        url: Target endpoint URL.
        timeout: HTTP request timeout in seconds.
        mode: ``"standard"`` or ``"marketplace"``.
        transport: Optional httpx transport (testing).
    """
    async with X402Auditor(timeout=timeout, transport=transport) as auditor:
        return await auditor.run_full_audit(url, mode=mode)
