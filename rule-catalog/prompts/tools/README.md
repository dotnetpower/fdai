# `rule-catalog/prompts/tools/`

Tool descriptions the LLM MAY call, stored as catalog-as-code. Wave 2.5-A ships
the schema and directory contract; the `ToolExecutor` and function-calling
integration land in Wave 2.5-B. See
[docs/roadmap/prompt-composition.md](../../../docs/roadmap/prompt-composition.md)
for the full design.

## Layout

| Path | What lives here |
|------|-----------------|
| `schema/tool.schema.json` | JSON Schema every tool YAML validates against |
| `catalog/<tool-id>.v<n>.yaml` | Per-tool descriptions (empty in Wave 2.5-A) |

## Contract

- File name: `<id>.v<version>.yaml`. `id` and `version` in the front-matter MUST
  match the file name.
- Every artifact carries `provenance.source` so a reader can see where the
  description came from.
- `description` is the exact string shown to the model. Keep it short - the
  tool manifest is prompt content, and long descriptions blow the context.
- `input_schema.type` MUST be `object`; the executor validates every call
  against the schema before dispatching to a provider.
- `output_wrapper` MUST carry `trusted="false"` so the model treats tool
  output as data, not instructions
  ([architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)).
- `default_mode` follows the shadow-before-enforce rule: a `shadow` tool is
  loaded and listed in the manifest for probes but never actually dispatched
  until promoted.

## Loading

`core/prompts/tool_registry.py` walks this tree at startup and exposes a
`ToolRegistry` Protocol. The `ToolExecutor` (Wave 2.5-B) validates every
model-issued tool call against the artifact's `input_schema`, applies the
`capability_gate` filters, and dispatches to the DI-injected provider.
