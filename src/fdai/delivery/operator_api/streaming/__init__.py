"""Operator API Server-Sent Events streaming boundary.

Responsibility:
Own long-lived SSE request lifecycle, bounded fan-out, and backpressure.

Boundary:
Relay server-owned progress and evidence frames without inventing events,
replaying work, or moving HTTP policy into providers.

Authority and state:
Presentation only. Streams hold connection-local state and no approval,
execution, or durable workflow authority.

Dependencies:
Starlette responses, stage publishers, typed activity frames, and cancellation
callbacks supplied by application composition.

Deployment:
Loaded only by Operator API ASGI processes for web streaming routes.
"""
