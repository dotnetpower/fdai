"""Operator API persistence-adapter boundary.

Responsibility:
Expose persistence helpers owned by the Operator API delivery surface.

Boundary:
Implement storage contracts without deciding policy, approval, or execution.

Authority and state:
May read or write only the records declared by each injected store contract;
it has no managed-resource authority.

Dependencies:
Shared provider contracts and concrete database clients.

Deployment:
Loaded by Operator API composition when durable adapters are configured.
"""
