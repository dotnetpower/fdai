# `rule-catalog/prompts/scenarios/`

Recognition-probe scenarios the runner replays against the composer +
responder pair. Each scenario names a capability, an optional operator-memory
scope, and the ground-truth contract the model response is scored against.
Wave 3 step D-2b-ii-beta ships the schema and the directory contract; the CLI
runner and the KPI dashboard emission land in Wave 3 step D-2b-ii-gamma.

See [docs/roadmap/prompt-composition.md](../../../docs/roadmap/prompt-composition.md)
for the full recognition-probe design.

## Layout

| Path | What lives here |
|------|-----------------|
| `schema/scenario.schema.json` | JSON Schema every scenario YAML validates against |
| `catalog/<id>.v<n>.yaml` | Per-scenario fixtures (empty in Wave 3 step D-2b-ii-beta) |

## Contract

- File name: `<id>.v<version>.yaml`. `id` and `version` in the front-matter
  MUST match the file name.
- Every scenario carries `provenance.source` so a reviewer can trace where
  the scenario came from.
- `capability_id` names which composer capability the runner invokes.
- `expected.required_fields` MUST list at least one required field with a
  known `expected_type` (`string` / `object` / `array`).
- `expected.expected_cited_rule_ids` is optional; leaving it out (or empty)
  opts the scenario out of citation F1 scoring so the KPI stays clean.
- `expected.canary_tokens` is optional; leaving it out lets the composer's
  own tokens carry through automatically (the runner's default path).

## Loading

`core/measurement/prompt_probe_loader.py` walks this tree at startup and
exposes a `ScenarioCatalog` return type. Aggregate errors follow the pattern
established in `aiopspilot.core.prompts.registry` and
`aiopspilot.core.tools.registry` so every malformed scenario surfaces in a
single exception.
