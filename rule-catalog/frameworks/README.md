# Framework Definitions

This directory pins advisory framework structure separately from executable rules and assessed
outcomes. A framework definition can map a control to a `BestPractice` or `ControlObjective`, but it
cannot evaluate evidence, grant approval, set enforcement, or execute a change.

## Current definitions

| Framework | Scope | Representation |
|---|---|---|
| `azure-waf` | One workload | All 59 coded recommendations from the five pinned design-review checklist pages map bijectively to Best Practice records. |
| `azure-caf` | Cloud estate and platform | Seven adoption methodologies and eight landing-zone design areas are reference-only until a deployment supplies applicability and evidence. |
| `azure-wara` | Workload and Azure resources | All 456 APRL recommendations from the pinned source revision, including 393 active items consumed by WARA and 63 disabled items retained for lifecycle completeness. |

CAF, WAF, WARA, and APRL are advisory guidance rather than compliance standards. Each source is
pinned by URL, source date, Git commit or content digest, and retrieval time. The
`completeness_scope` field states exactly what the snapshot covers; it never claims regulatory
compliance.

## Regeneration

Run:

```bash
uv run python scripts/catalog/sync_azure_framework_catalogs.py
```

The script materializes both framework definitions, the complete WAF Best Practice set, and the five
WAF rule sets. Catalog validation then checks the WAF definition-to-Best-Practice bijection,
provenance consistency, typed evidence references, and rule-set members.

Regenerate the WARA/APRL snapshot from exact downloaded inputs:

```bash
uv run python scripts/catalog/import_wara_aprl.py \
  --source-root <aprl-checkout-at-pinned-commit> \
  --published-object <wara-recommendations.json> \
  --output rule-catalog/collected/wara-aprl/azure-wara.json
```

The importer requires the active APRL GUID set and metadata to match the published object exactly.
It retains query digests rather than treating external Azure Resource Graph text as executable FDAI
policy.
