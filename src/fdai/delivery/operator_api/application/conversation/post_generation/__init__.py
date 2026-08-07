"""Process-local post-generation orchestration for Operator conversations.

Responsibility:
Coordinate quality review, terminal verification, history persistence, terminal
payload construction, and post-turn review after answer generation completes.

Boundary:
Accept validated turn state and injected adapters. HTTP parsing, authorization,
SSE framing, frame sequencing, connection cancellation, and transport delivery
remain route-owned.

Authority and state:
This package cannot approve, execute, promote, or select provider scope. Durable
conversation writes occur only through an injected principal-scoped persister.

Dependencies:
Conversation application contracts, deterministic verification, terminal
projections, and injected route adapters for transport-local behavior.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.application.conversation.post_generation.service import (
    PostGenerationContext,
    PostGenerationDependencies,
    PostGenerationFrame,
    evidence_timing_status,
    finalize_post_generation,
)

__all__ = [
    "PostGenerationContext",
    "PostGenerationDependencies",
    "PostGenerationFrame",
    "evidence_timing_status",
    "finalize_post_generation",
]
