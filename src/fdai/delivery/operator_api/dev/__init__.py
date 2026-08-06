"""Development-only Operator API composition boundary.

Responsibility:
Compose local Azure-backed Operator API development adapters and explicit test
fixtures.

Boundary:
Keep local credential/debug behavior physically separate from production and
never present synthetic fixtures as observed Azure state.

Authority and state:
No executor authority. Local CLI credentials are read-provider credentials;
test fixtures remain opt-in and isolated.

Dependencies:
Local configuration, Azure CLI read adapters, production-compatible app wiring,
and explicit fixture builders.

Deployment:
Excluded from production runtime composition and used only for local or pytest
processes.
"""
