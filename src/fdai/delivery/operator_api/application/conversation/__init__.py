"""Process-local conversation application capabilities.

Responsibility:
Group typed conversation use cases that coordinate deterministic answer
processing after transport validation.

Boundary:
Accept plain typed values and return application results without owning HTTP,
SSE, authentication, or persistence transport behavior.

Authority and state:
No approval, execution, promotion, or provider-scope authority. Durable state
remains owned by injected conversation providers.

Dependencies:
Operator application contracts and deterministic process-local helpers.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""
