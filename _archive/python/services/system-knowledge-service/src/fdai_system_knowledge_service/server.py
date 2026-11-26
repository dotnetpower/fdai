"""Production ASGI server runner for the System Knowledge Service."""

from __future__ import annotations

import uvicorn
from starlette.applications import Starlette

from fdai_system_knowledge_service.config import SystemKnowledgeSettings


def serve(app: Starlette, settings: SystemKnowledgeSettings) -> int:
    """Run the service on its validated host and port."""

    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False)
    return 0


__all__ = ["serve"]
