"""Operator API provider adapters.

Responsibility:
Group concrete provider bindings used by the Operator API application layer.

Boundary:
Implement application contracts without owning HTTP routes, SSE frames,
authentication policy, or application decisions.

Authority and state:
Adapters perform bounded provider I/O only. They receive no approval,
promotion, execution, or durable-state ownership.

Dependencies:
Operator application contracts, provider SDK helpers, and injected identities.

Deployment:
Runs in-process within the Operator API and creates no service boundary.
"""
