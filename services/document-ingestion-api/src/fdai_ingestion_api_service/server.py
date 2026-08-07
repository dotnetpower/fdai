"""ASGI server adapter for the Document Ingestion API process."""

from __future__ import annotations

from typing import Any

import uvicorn


def serve(application: Any) -> int:
    """Serve one constructed ASGI application on the Container App ingress port."""
    uvicorn.run(
        application,
        host="0.0.0.0",  # noqa: S104 - Container App ingress terminates external HTTPS.
        port=8000,
    )
    return 0
