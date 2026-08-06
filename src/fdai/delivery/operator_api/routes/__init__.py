"""Operator API HTTP route-family boundary.

Responsibility:
Group thin Starlette route modules by published HTTP responsibility.

Boundary:
Parse transport input, enforce server-owned authentication/RBAC, and delegate
to typed application or projection services rather than domain implementations.

Authority and state:
No executor authority. Routes own no shared mutable workflow state and cannot
grant approval, promotion, or managed-resource eligibility.

Dependencies:
Starlette transport types, Operator API application services, projections, and
injected provider contracts.

Deployment:
Composed only into development or production Operator API ASGI applications.
"""
