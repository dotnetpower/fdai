"""ASGI server adapter for the Document Ingestion API process."""

from __future__ import annotations

import uvicorn


def serve(factory_reference: str) -> int:
    """Serve a local ASGI factory on the Container App ingress port."""
    uvicorn.run(
        factory_reference,
        factory=True,
        host="0.0.0.0",  # noqa: S104 - Container App ingress terminates external HTTPS.
        port=8000,
    )
    return 0
