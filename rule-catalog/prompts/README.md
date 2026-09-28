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
| `profiles/` | Exact active and shadow compositions with request budgets |
| `history/` | Inactive artifacts retained for source review but excluded from runtime loading |
| `roles/` | Critic / judge headers (Wave 3-4) |
| `tools/` | Tool descriptions surfaced to the model (Wave 2.5+) |

## Contract

- File name: `<id>.v<version>.yaml`. `id` and `version` in the front-matter MUST
  match the file name.
- Every artifact carries `provenance.source` so a reader can see where the text
  came from (mirrors the rule-catalog provenance rule in
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- New prompts default to `default_mode: shadow`. Artifact mode never activates a root prompt.
  `profiles/catalog.yaml` selects one exact active profile per capability, and an explicit profile id
  selects a shadow treatment.
- A dynamic profile (catalog schema `1.1.0`) marks packs conditional with `when_any` assembly keys
  and names the result keys each pack governs with `covers`. The root is never conditional. See
  [Dynamic assembly](../../docs/roadmap/decisioning/prompt-composition.md#dynamic-assembly).
- All bodies use ASCII punctuation only. The repo-wide
  [`scripts/quality/repository/check-punctuation.sh`](../../scripts/quality/repository/check-punctuation.sh) enforces this.

## Loading

`core/prompts/registry.py` walks the hot artifact tree and validates
`profiles/catalog.yaml` at startup. Historical artifacts are not loaded. The registry exposes a
`PromptRegistry` Protocol whose `resolve()` method returns one exact root-and-pack composition.
The composition root passes digest-bound bodies and budgets into the Azure OpenAI adapters;
`core/` never opens these files directly.

`semantic.judgment`, `semantic.query.frame`, and `semantic.query.plan` are
prompt-only lookup keys. Semantic judgment reuses resolved T1 and optional T2
targets. Semantic query framing and planning reuse the resolved primary and
secondary T2 reasoner candidates for two sequential schema-validated calls.
None of these keys provisions a separate deployment.

The operator-console narrator is not loaded from this catalog. Pull-direction
channels call the shared Operator API, whose chat coordinator owns its grounded
prompt and verification flow. Keep channel-specific presentation instructions
out of this T2 prompt registry.
