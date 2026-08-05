"""Operator API-owned read projections.

Responsibility: group deterministic read-model projections outside HTTP route
namespaces. Authority: none; projections cannot approve, execute, or write
domain state. State remains in injected authoritative stores. Dependencies are
read contracts and pure projection helpers. Deployment role: imported by the
Operator API composition while compatibility routes forward published paths.
"""
