# `core/tools`

Tool catalog seam. Wave 2.5-A ships the registry that loads tool descriptions
from `rule-catalog/prompts/tools/`. Wave 2.5-B step 2a adds the async
`ToolExecutor` and its `DefaultToolExecutor` upstream implementation together
with the `ToolProvider` seam. Wave 2.5-B step 2b wires the executor into the
Azure OpenAI cross-check adapter.

## Files

| File | Role |
|------|------|
| `types.py` | `ToolArtifact`, `CapabilityGate` |
| `registry.py` | `ToolRegistry` Protocol + `FileSystemToolRegistry` |
| `executor.py` | `ToolExecutor` Protocol + `DefaultToolExecutor` + `ToolProvider` + `ToolResult` + typed errors |
| `testing.py` | `InMemoryToolProvider` (canned responses) + `NoOpToolProvider` (refuses everything) |
| `__init__.py` | Re-exports the public surface |

## Contracts

- **Aggregate errors (registry)**: constructor scans every YAML and raises
  `ToolRegistryError` with the full list of `ToolRegistryIssue` entries.
- **Fail-fast (registry)**: missing catalog root, missing schema file, and any
  per-file issue abort startup.
- **`trusted="false"` invariant**: any populated `output_wrapper` MUST embed
  the marker; the registry rejects tool YAMLs whose wrapper is missing it.
- **Determinism**: `artifacts()` is sorted by (id, version); `get` picks the
  highest version.
- **Fail-closed dispatch**: every executor failure surfaces as a typed
  `ToolExecutorError` subclass (`UnknownToolError`,
  `ShadowToolBlockedError`, `ToolArgumentValidationError`,
  `MissingProviderError`, `ProviderCallError`). The executor never returns a
  partial result - the caller routes to HIL.
- **Shadow guard**: `DefaultToolExecutor(allow_shadow_dispatch=False)` (the
  default) refuses every `default_mode: shadow` tool at dispatch time even if
  the composer's manifest layer somehow surfaced it, providing a belt-and-
  braces enforcement of the shadow-before-enforce rule.
- **Wrapper enforcement**: the executor renders every provider payload inside
  the tool's `output_wrapper` (or the canonical
  `<tool_result trusted="false" tool="{tool_id}">{payload}</tool_result>`
  fallback), so the `trusted="false"` invariant reaches the next model turn
  even when a fork forgets to author a wrapper.

See [docs/roadmap/decisioning/prompt-composition.md](../../../../docs/roadmap/decisioning/prompt-composition.md)
for how tools fit into the evolving-system-prompt design.
