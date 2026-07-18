# `rule-catalog/reports/`

Report definitions consumed by the reporting subsystem
(`src/fdai/core/reporting/`). Every file here is one report, loaded and
validated at composition-root time and rendered on demand through the
read-only ``GET /reports/*`` routes.

- [`schema/report.schema.json`](schema/report.schema.json) - JSON Schema
  every report file MUST satisfy. Loader:
  [`load_report_catalog`](../../src/fdai/core/reporting/catalog.py).
- Reports shipped upstream are **customer-agnostic**: they never carry a
  subscription id, resource name, endpoint, or any private identifier.
  A fork adds its own reports under a fork-local directory and loads
  both at its composition root (last-write-loss on duplicate ids).

## Authoring a new report

1. Copy an existing YAML (for example
   [`signal-feed-overview.yaml`](signal-feed-overview.yaml)) as a template.
2. Give it a unique lowercase `id` and a semver `version`.
3. Pick the widget types you need from
   [docs/roadmap/interfaces/reporting-subsystem.md](../../docs/roadmap/interfaces/reporting-subsystem.md#widget-catalog).
4. Wire each widget's `query.datasource` to a registered source
  (`audit`, `report_feed`, `security_assessment`, `metric`, `log_query`,
  `static`, `noop`, or
   a fork-registered custom source).
5. Validate locally by loading the catalog through
   `python -c "from fdai.core.reporting.catalog import load_report_catalog; load_report_catalog(...)"`
   or by running the reporting test suite.

Widget shapes and the JSON contract the FE consumes live in
[docs/roadmap/interfaces/reporting-subsystem.md](../../docs/roadmap/interfaces/reporting-subsystem.md).

`security-assessment.yaml` is the reference for deep evidence reports. It keeps
observed/expected values, assessment completeness, source freshness, positive
controls, remediation validation, CVE applicability, compliance mappings, and
missing evidence visible through existing generic widgets.

## What the loader enforces

- The whole file must match the JSON Schema (unknown top-level keys are
  rejected; a widget MUST declare `id`, `type`, and `title`).
- `time_range` must supply one of `last` / `relative_duration` / a
  `since` / a full `since`+`until` pair (mutually exclusive).
- Two files claiming the same `id` fails the load.
- When the loader is called with an `allowed_widget_types` /
  `allowed_datasources` set (the upstream composition does this by
  default), an unknown widget type or datasource fails the load rather
  than surfacing as an ``error`` widget at render time.
