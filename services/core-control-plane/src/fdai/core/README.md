# `src/fdai/core`

Headless control plane. Contains the event loop, trust router, tiers, quality gate,
risk gate, executor, and audit writer. MUST NOT import cloud SDKs directly - access
flows through `shared/providers/`.
