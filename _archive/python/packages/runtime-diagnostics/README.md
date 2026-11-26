# Runtime diagnostics

This package provides the local-only, authority-free FDAI development diagnostic probe. It owns
bounded process snapshots, explicit CPU and Python heap capture, validated profile packets, and an
owner-only Unix socket transport.

## Boundary

- Disabled by default and rejected outside the local execution venue.
- No HTTP, browser, channel, Event Bus, provider, approval, or executor integration.
- No request bodies, answers, environment values, credentials, heap objects, or hidden reasoning.
- Every packet is content-addressed and carries `external_state_authority=false` and
  `execution_authority=false`.

## Testing

Run `uv run pytest -q --no-cov packages/runtime-diagnostics/tests` from the repository root.
