# `core/operator_memory`

Operator memory seam. Wave 3 step A ships the types, the async
`OperatorMemoryStore` Protocol, an in-memory implementation for tests, and
the sanitizer that wraps every retrieved entry in a `trusted="false"`
XML envelope before it reaches the model.

## Files

| File | Role |
|------|------|
| `types.py` | `OperatorMemoryEntry`, `ScopeKind` (resource-group / resource only), `MemorySource`, `MemoryCategory` |
| `store.py` | `OperatorMemoryStore` Protocol + `InMemoryOperatorMemoryStore` + `OperatorMemoryPolicyError` |
| `sanitizer.py` | `detect_injection_markers`, `InjectionMarkerError`, `wrap_operator_note` |
| `__init__.py` | Re-exports the public surface |

## Contracts

- **Scope <= resource-group**: writes with a broader scope raise
  `OperatorMemoryPolicyError('scope_too_wide', ...)`. Disabling a rule
  organization-wide is a rule retirement, not an operator memory entry, and
  MUST flow through the catalog pipeline.
- **Distinct approver**: `author` and `approved_by` MUST differ (case-insensitive
  compare). Self-approval is rejected fail-closed at the store boundary.
- **Append-only**: the store never mutates a stored entry's body. A newer entry
  supersedes the older one via `supersede(entry_id, superseded_by)`; readers
  filter superseded rows out.
- **TTL optional**: a `ttl_seconds=None` entry is long-lived by design (matches
  the Human Override policy). Non-null values MUST be positive.
- **Injection defense at write time**: the sanitizer scans the body for common
  prompt-injection markers ("ignore previous", "system:", role-hijack tokens)
  and raises `InjectionMarkerError` on any hit. The composer inject path applies
  the XML wrap on top so the marker check is layered, not single-point.
- **XML wrap**: `wrap_operator_note` renders every accepted body inside
  `<operator_note trusted="false" ...>...</operator_note>` with XML-escaped
  attribute values and content so an entry cannot forge the closing tag.

See [docs/roadmap/decisioning/prompt-composition.md](../../../../docs/roadmap/decisioning/prompt-composition.md)
for how operator memory fits into the evolving-system-prompt design.
