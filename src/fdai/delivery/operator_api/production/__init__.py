"""Production Operator API composition boundary.

Responsibility:
Bind production authentication, persistence, provider adapters, and app wiring.

Boundary:
Resolve deployment configuration and identities without moving judgment or
managed-resource execution into the HTTP process.

Authority and state:
No Thor executor authority. Read and command-transport identities stay
distinct, and durable state is owned by injected stores.

Dependencies:
Environment configuration, managed identities, PostgreSQL, event transport,
and Operator API application composition.

Deployment:
Runs only in the deployed Operator API Container App.
"""
