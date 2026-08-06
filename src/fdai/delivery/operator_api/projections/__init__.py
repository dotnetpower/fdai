"""Operator API-owned read-projection boundary.

Responsibility:
Group deterministic read-model projections outside HTTP route namespaces.

Boundary:
Transform authoritative records into bounded views without writing domain
state or treating presentation as evidence.

Authority and state:
Read-only. Projections cannot approve or execute; state and provenance remain
in injected authoritative stores.

Dependencies:
Read contracts and pure projection helpers.

Deployment:
Imported by Operator API composition while compatibility routes preserve
published paths.
"""
