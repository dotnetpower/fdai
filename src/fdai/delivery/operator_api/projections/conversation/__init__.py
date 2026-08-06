"""Conversation read-projection boundary.

Responsibility:
Group deterministic conversation projections outside HTTP route namespaces.

Boundary:
Accept verified request-local evidence and produce bounded presentation values;
HTTP, SSE, authentication, cancellation, and persistence stay route-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
persist conversation state and receives no executor identity.

Dependencies:
Conversation contracts plus pure evidence and projection helpers.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""
