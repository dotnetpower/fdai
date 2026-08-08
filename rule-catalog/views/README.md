# Declarative Process Views

This directory contains read-only ViewSpec data for rendering governed Process and ontology
projections. A view chooses reports and layout regions for a Workflow; it does not create or
advance the Process it displays.

## Contract

- [`schema/view.schema.json`](schema/view.schema.json) defines the authored shape.
- `applies_to.workflow_ref` resolves to a Workflow under [`../workflows/`](../workflows/).
- Every region references a registered report under [`../reports/`](../reports/).
- Routes, regions, and column spans are presentation metadata only. A view has no mutation,
  approval, judgment, or execution authority.

The loader in [`catalog.py`](../../services/core-control-plane/src/fdai/core/views/catalog.py)
validates schema, duplicate ids, workflow references, report references, and layout bounds.
WorkflowApp discovery manifests under [`../operator-console/`](../operator-console/) reference
these view ids.
