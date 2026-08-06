"""Operator API application assembly boundary.

Responsibility:
Compose route families, application services, middleware, and lifespan hooks.

Boundary:
Translate authenticated HTTP/SSE requests into typed application calls without
embedding domain judgment or provider-specific policy in route registration.

Authority and state:
No executor authority. Request-local state and injected provider handles only;
durable state stays behind application and persistence contracts.

Dependencies:
Operator API application services, route/streaming modules, authentication,
and immutable composition records.

Deployment:
Runs in development and production Operator API processes; it is not imported
by the headless core runtime.
"""
