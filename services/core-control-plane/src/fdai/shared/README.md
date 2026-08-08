# `src/fdai/shared`

Cross-cutting library used by every layer. Contracts, provider interfaces,
telemetry helpers, and config schema live here. One-way dependency: `shared/` does
not import `core/`.
