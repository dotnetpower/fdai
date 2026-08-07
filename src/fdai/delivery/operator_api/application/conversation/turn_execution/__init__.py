"""Typed one-shot conversation execution outside HTTP transport.

Responsibility:
Expose the process-local JSON turn execution contract and facade.

Boundary:
Accept authenticated plain Python values and return typed outcomes without
importing Starlette or route modules.

Authority and state:
Coordinate request-local conversation work only. The package cannot approve,
execute, promote, select provider scope, or hold durable state directly.

Dependencies:
Injected conversation application, projection, persistence, and provider-neutral
backend contracts.

Deployment:
Runs in-process inside the Operator API and creates no network boundary.
"""

from .models import (
    JsonTurnExecutionError,
    JsonTurnExecutionResult,
    JsonTurnOutcome,
    StreamTurnEvent,
    StreamTurnExecution,
    StreamTurnExecutionError,
)
from .service import JsonTurnExecutionService
from .stream_service import StreamTurnExecutionService

__all__ = [
    "JsonTurnExecutionError",
    "JsonTurnExecutionResult",
    "JsonTurnExecutionService",
    "JsonTurnOutcome",
    "StreamTurnEvent",
    "StreamTurnExecution",
    "StreamTurnExecutionError",
    "StreamTurnExecutionService",
]
