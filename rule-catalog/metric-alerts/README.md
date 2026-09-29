# Metric alert entries (deployment-supplied)

Drop folder for reviewed static-threshold metric alerts that a deployment materializes as Azure
Monitor metric alert rules on
[push path #1](../../docs/roadmap/rules-and-detection/near-real-time-detection-paths.md#push-path-1---metric-alert-rule---webhook-30-90-s).
The upstream catalog ships no entries: a generic deployment stays on the pull path, and a fork
adds only the alerts it reviewed.

| Field | Meaning |
|-------|---------|
| `alert_id` | Stable lowercase identifier that names the generated rule `alert-fdai-<alert_id>` |
| `metric` | CSP-neutral metric key from the reviewed Azure Monitor Metrics API template catalog |
| `resource_type` | ARM type for templates that don't declare one; must match when the template does |
| `comparison` | `above`, `at_or_above`, `below`, or `at_or_below` |
| `threshold` | Finite number in the metric's native unit |
| `window`, `frequency` | Azure-supported ISO 8601 durations; the frequency can't exceed the window |
| `severity` | Azure Monitor severity 0 through 4 |
| `mode` | Always `shadow`; alerts reach FDAI only as shadow-mode Events |
| `provenance` | Standard catalog provenance for review |

Generate the Terraform inputs from a checkout:

```bash
uv run python -m fdai.delivery.azure.alert_rule_authoring_cli \
  --catalog rule-catalog/metric-alerts \
  --output <deployment>/metric-alerts.auto.tfvars.json
```

The generator is all-or-nothing. It refuses unknown metrics, dimension-filtered or
deployment-scoped templates, missing or conflicting resource types, and unsupported
comparisons, and it writes nothing when any entry is refused. Each generated alert maps onto
one `infra/modules/observability/metric-alert-rules` instance. Entries grant no detection,
approval, or execution authority.
