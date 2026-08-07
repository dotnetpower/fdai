"""Process-local conversation capabilities outside HTTP transport.

Responsibility:
Group typed, non-authoritative conversation capabilities by domain.

Boundary:
Accept validated application inputs; HTTP, SSE, authentication, cancellation,
and terminal transport remain route-owned.

Authority and state:
Request-local and non-authoritative. Capabilities cannot approve, execute,
promote, or persist transport state and receive no executor identity.

Dependencies:
May depend on Operator API application contracts and read-only projections.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""
