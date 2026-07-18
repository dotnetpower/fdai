# `rule-catalog/prompts/`

Prompt fragments used by the T2 tier and quality gate, stored as catalog-as-code
so a fork can override without editing `core/`. This tree is the source of truth
for the base prompt today; task packs, critic / judge role headers, and tool
manifests land in later waves. See
[docs/roadmap/decisioning/prompt-composition.md](../../docs/roadmap/decisioning/prompt-composition.md)
for the full design.

## Layout

| Path | What lives here |
|------|-----------------|
| `schema/prompt.schema.json` | JSON Schema every prompt YAML validates against |
| `base/` | Short, immutable role skeletons (e.g. `t2-cross-check.v1.yaml`) |
| `packs/` | Capability-scoped skill packs (Wave 2+) |
| `roles/` | Critic / judge headers (Wave 3-4) |
| `tools/` | Tool descriptions surfaced to the model (Wave 2.5+) |

## Contract

- File name: `<id>.v<version>.yaml`. `id` and `version` in the front-matter MUST
  match the file name.- Every artifact carries `provenance.source` so a reader can see where the text
  came from (mirrors the rule-catalog provenance rule in
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- New prompts default to `default_mode: shadow`. Promotion to `enforce` is a
  separately reviewed change and MUST cite the measured `promotion_gate` result.
- All bodies use ASCII punctuation only. The repo-wide
  [`scripts/quality/repository/check-punctuation.sh`](../../scripts/quality/repository/check-punctuation.sh) enforces this.

## Loading

`core/prompts/registry.py` walks this tree at startup and exposes a
`PromptRegistry` Protocol. The composition root passes resolved bodies into the
Azure OpenAI adapters; `core/` never opens these files directly.

The operator-console narrator is not loaded from this catalog. Pull-direction
channels call the shared read API, whose chat coordinator owns its grounded
prompt and verification flow. Keep channel-specific presentation instructions
out of this T2 prompt registry.
