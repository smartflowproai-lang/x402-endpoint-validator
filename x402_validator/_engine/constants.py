"""Module-level constants for the x402 conformance engine.

All check functions import from this module directly. Centralizing these
constants ensures pattern and header-name changes propagate uniformly without
risk of drift between individual check implementations.
"""

from __future__ import annotations

import re
from typing import Final


# CAIP-2 (Chain Agnostic Identifier) — https://chainagnostic.org/CAIP-2
#
# Format: `<namespace>:<reference>`, where:
#   - namespace must be lowercase (eip155, solana, polkadot, etc.)
#   - reference may include alphanumerics, underscores, hyphens
CAIP2_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9-]+:[a-zA-Z0-9_-]+$"
)


# Standard x402 discovery path (suffix appended to base URL).
MANIFEST_PATH_SUFFIX: Final[str] = "/.well-known/x402"


# HTTP header names that may carry the PaymentRequired payload (v2 channel).
#
# Header is canonical per x402 spec; body is the legacy placement. Tests for
# CAIP-2 compliance probe these in priority order: lowercased, then decoded.
PAYMENT_HEADERS: Final[tuple[str, ...]] = (
    "payment-required",
    "x-payment-required",
    "x-402-accepts",
    "www-authenticate",
)


class CheckMode:
    """Audit mode constants — string enums for clarity. Use ``CheckMode.STANDARD`` etc.

    ``standard``    — single-endpoint conformance audit (4 base checks).
    ``marketplace`` — multi-product catalog (adds marketplace + product walks).
    """

    STANDARD: Final[str] = "standard"
    MARKETPLACE: Final[str] = "marketplace"
    ALL: Final[tuple[str, ...]] = (STANDARD, MARKETPLACE)
