# `src/fdai/shared/providers`

Provider interfaces realizing the four CSP-neutrality contracts (event bus,
runtime, secret, workload identity). Concrete adapters plug in at the composition
root - `core/` never imports a cloud SDK directly.
