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
| `profiles.py` | Exact profile, artifact reference, budget, and static composition contracts |
| `profile_loader.py` | Profile schema loading and exact artifact-reference validation |
| `profile_evaluation.py` | Content-free active-versus-shadow size and identity comparison |
| `assembly.py` | `PromptAssembler`: per-call conditional-pack selection with replay receipts |
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
- **Determinism**: `resolve()` uses the exact root and ordered pack references in the selected
  profile. Discovery helpers retain highest-version lookup only for profile-free compatibility
  catalogs and tests.
- **Budgets**: every exact profile pins system, complete request, and reserved output token
  budgets. Static composition rejects a system overrun, and Azure semantic adapters reject a
  complete request overrun before provider I/O.
- **Composer async**: `PromptComposer.compose` is async so later waves can read
  operator memory from Postgres without a Protocol change. The Wave 2 default
  implementation is CPU-only and completes immediately.
- **Recognition primitives**: `ComposedPrompt.layer_manifest` records
  `(id, version, layer, token_estimate)` per contribution so the audit log can
  reconstruct exactly which fragments produced any given decision.
- **Active-vs-shadow profiles**: the default composition resolves one exact active profile. A
  shadow treatment requires its explicit profile id, so a higher artifact version or unrelated
  shadow pack cannot change production composition.
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
- **Answer continuity and ablation**: a reviewed runtime profile can remove only
  optional packs, tool manifests, operator memory, or runtime skill layers.
  Protected role layers stay active, every exclusion is replay-visible, and a
  named shadow pack can be activated without enabling unrelated shadow packs.

See [docs/roadmap/decisioning/prompt-composition.md](../../../../../../docs/roadmap/decisioning/prompt-composition.md)
for how this module fits into the evolving-system-prompt design.
