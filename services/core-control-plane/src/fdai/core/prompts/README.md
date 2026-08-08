# `core/prompts`

Prompt composition seam. Loads catalog-as-code prompt fragments from
`rule-catalog/prompts/`, validates them against the JSON Schema, and exposes a
read-only `PromptRegistry` Protocol plus an async `PromptComposer` Protocol to
the composition root. `core/` MUST NOT open the YAML files directly - it
consumes injected `ComposedPrompt` values produced by the composer.

## Files

| File | Role |
|------|------|
| `types.py` | `PromptArtifact`, `PromptLayer`, `PromptMode`, `LayerRef`, `ComposedPrompt` |
| `registry.py` | `PromptRegistry` Protocol + `FileSystemPromptRegistry` |
| `composer.py` | `PromptComposer` Protocol + `DefaultPromptComposer` (Base + Task Pack + Tool Manifest + Operator Memory) |
| `testing.py` | `StaticPromptComposer` fake for tests |
| `__init__.py` | Re-exports the public surface |

The tool-catalog registry lives in [`../tools/`](../tools/README.md); the
operator-memory store lives in
[`../operator_memory/`](../operator_memory/README.md). The composer imports
both optionally so prompt-only tests do not need any registry beyond
`PromptRegistry`.

## Contracts

- **Aggregate errors**: `FileSystemPromptRegistry.__init__` scans every YAML and
  raises a single `PromptRegistryError` with the full list of `PromptRegistryIssue`
  entries, matching the pattern in `fdai.rule_catalog.schema.llm_registry`.
- **Fail-fast**: constructor validates every artifact before returning. A missing
  catalog root, a missing schema file, and any per-file issue all abort startup.
- **Determinism**: `artifacts()` is sorted by (id, version); `get_base` picks the
  highest version and tie-breaks on id; `get_packs` groups packs by id and keeps
  the highest version so a legacy pack next to a bumped one never double-injects.
- **Composer async**: `PromptComposer.compose` is async so later waves can read
  operator memory from Postgres without a Protocol change. The Wave 2 default
  implementation is CPU-only and completes immediately.
- **Recognition primitives**: `ComposedPrompt.layer_manifest` records
  `(id, version, layer, token_estimate)` per contribution so the audit log can
  reconstruct exactly which fragments produced any given decision.
- **Shadow-vs-enforce**: `DefaultPromptComposer(include_shadow_packs=False)` is
  the production default. Packs authored as `default_mode: shadow` live in git
  and are visible to recognition probes but never affect the live prompt until
  promoted to `enforce` in a separately reviewed change.
- **Tool manifest (Wave 2.5-B)**: passing a `ToolRegistry` to the composer
  emits a synthetic `tool` layer that lists eligible tool descriptions. Shadow
  tools follow the same opt-in filter (`include_shadow_tools=True`) as
  shadow packs. The executor and function-calling integration land next.
- **Operator memory layer (Wave 3 step C-1)**: passing an
  `OperatorMemoryStore` **and** a `scope` on `compose(...)` emits a
  synthetic `operator-memory` layer. Every retrieved entry is wrapped
  via `wrap_operator_note`, resource-group notes precede resource notes,
  superseded / expired entries are silently filtered. When either the
  store or the scope is missing, the layer is skipped entirely - the
  model never sees an "empty notes" section.

See [docs/roadmap/decisioning/prompt-composition.md](../../../../docs/roadmap/decisioning/prompt-composition.md)
for how this module fits into the evolving-system-prompt design.
