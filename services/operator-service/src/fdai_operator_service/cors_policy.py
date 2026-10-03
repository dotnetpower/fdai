"""Cross-origin request policy for Console clients of the Operator API."""

from __future__ import annotations

from typing import Final

# A local Console calls the Operator cross-origin, and every revision-checked
# mutation sends If-Match, so the preflight must allow it.
CORS_ALLOW_HEADERS: Final = (
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "If-Match",
    "Last-Event-ID",
    "X-Correlation-ID",
)
CORS_EXPOSE_HEADERS: Final = (
    "X-FDAI-Artifact-SHA256",
    "X-FDAI-Entitlement",
    "X-FDAI-Expected-Rows",
    "X-FDAI-Included-Rows",
    "X-FDAI-Local-Session",
    "X-FDAI-Revision",
)
