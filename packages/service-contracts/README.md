# FDAI Service Contracts

`fdai-service-contracts` is the implementation-free Python SDK shared by FDAI's independently
released services. It defines typed wire records, compatibility and readiness checks, schema
codecs, and provider protocols without carrying service composition, persistence, business
workflows, or execution authority.

## Responsibilities

Use this package for contracts that cross an independently released process boundary:

- Versioned request, event, projection, receipt, and evidence records.
- JSON Schema lookup, validation, and bounded wire codecs.
- N/N-1 compatibility checks, additive translators, and rolling-transition evidence.
- Provider-neutral protocols that service-owned adapters implement.
- Stable service identity, execution venue, readiness, and audit serialization records.

Contract data can describe an action or an executor boundary, but importing this package never
grants approval, mutation, provider access, or executor identity. Keep provider clients, database
access, composition, and workflow decisions in the service that owns them.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_service_contracts/codec.py`, `compatibility.py`, `manifest.py`, `transition.py`, `translators.py` | Wire encoding, release compatibility, and transition checks |
| `src/fdai_service_contracts/document.py`, `operator.py`, `semantic_turn.py`, `ontology_query.py` | Cross-service domain records and read contracts |
| `src/fdai_service_contracts/discovery.py`, `discovery_evidence.py`, `operational_activity.py` | Bounded discovery and operational evidence contracts |
| `src/fdai_service_contracts/executor.py`, `executor_models.py`, `executor_providers.py` | Isolated Executor commands, receipts, values, and protocols |
| `src/fdai_service_contracts/schema.py`, `schemas/` | Package-backed JSON Schema registry and immutable schema versions |
| `tests/` | Focused contract, compatibility, delivery, and boundary tests |

The package is typed and includes `py.typed`. Public convenience exports are available from
`fdai_service_contracts`; domain modules remain available for explicit imports.

## Use In The Workspace

The repository installs this distribution as a `uv` workspace member. Prepare the development
environment from the repository root:

```bash
uv sync --extra dev
```

Import only the contract needed by the consuming service:

```python
from fdai_service_contracts import SemVer, ensure_supported_version

wire_version = ensure_supported_version("1.3.0", supported_major=1)
assert wire_version >= SemVer.parse("1.0.0")
```

## Change A Contract

Keep contract changes reviewable across independently deployable consumers:

1. Add a new schema version instead of changing a published schema in place.
2. Preserve additive compatibility within a major version and update explicit translators when an
   older peer needs a smaller envelope.
3. Update the compatibility manifest and producer or consumer codecs for every affected edge.
4. Add focused N/N-1 and malformed-input tests without importing another service implementation.
5. Keep authorization, policy, provider I/O, and business behavior outside this package.

## Testing

Run the package tests from the repository root:

```bash
uv run pytest -q --no-cov packages/service-contracts/tests
```

Validate the independent-service boundary after changing package structure or metadata:

```bash
uv run python scripts/quality/architecture/check-independent-services.py
```

## Related Documentation

| To learn about | Read |
|----------------|------|
| Shared SDK ownership | [Code map](../../docs/roadmap/architecture/code-map.md#shared-contract-sdk) |
| Process and data ownership | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Repository package boundaries | [Project structure](../../docs/roadmap/architecture/project-structure.md) |
