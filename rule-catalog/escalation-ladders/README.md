# Escalation ladders and urgency policies

Catalog-as-code for the human side of escalation: which audiences a finding
walks through, how long each of them gets to answer, and how a closing forecast
compresses those windows.

Loaded by
[`escalation_ladder.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/escalation_ladder.py).
The design of record is
[escalation-and-standing-authority.md](../../docs/roadmap/decisioning/escalation-and-standing-authority.md).

This is **not** the T2 model-class ladder in
`fdai.core.quality_gate.escalation_ladder`, which decides whether to spend a
stronger model on a disagreement. This directory is about humans and approval
authority.

## Files

Every YAML file carries a `kind` discriminator and validates against the
matching schema in this directory.

| `kind` | Schema | Purpose |
|--------|--------|---------|
| `escalation_ladder` | `escalation-ladder.schema.json` | One ordered ladder of approval rungs with a hard overall deadline. |
| `urgency_policy` | `urgency-policy.schema.json` | How a closing forecast compresses rung windows. |

## Invariants the loader enforces

- **Deterministic selection.** `priority` is unique across the catalog and
  ladders are matched first-match in ascending priority, so the same finding
  always selects the same ladder.
- **Every declared rung is reachable.** The rung TTLs must fit inside
  `overall_deadline_seconds`. A ladder cannot name an audience that the
  deadline silently makes unreachable.
- **Paging is not deciding.** A rung may not page its own `audience_group`.
  `also_page` channels carry awareness, never approval authority.
- **Urgency only compresses.** An effective TTL is clamped to
  `[min_effective_ttl_seconds, rung.ttl_seconds]`, so a forecast walks the
  ladder faster while still guaranteeing each human a usable window, and never
  lengthens a window past its declared value.
- **A forecast must earn its influence.** A reading below
  `min_forecast_confidence` compresses nothing.

## Placeholders

Audience groups (`aw-*`) and channel ids (`pagerduty-primary`, `sms-oncall`)
are upstream placeholders. A deployment overlay replaces them with real values;
upstream never carries a tenant-identifying value. See
[generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md).
