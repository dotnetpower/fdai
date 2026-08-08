# Operator Console Applications

This directory contains read-only WorkflowApp manifests used to discover governed workflow
experiences in the FDAI Console. A manifest binds one Workflow definition to one declarative view,
localized labels, an audience role, and navigation metadata.

## Contract

- [`schema/workflow-app.schema.json`](schema/workflow-app.schema.json) defines the authored shape.
- `workflow_ref` must resolve under [`../workflows/`](../workflows/), and `view_ref` must resolve
  under [`../views/`](../views/).
- Manifests control discovery and presentation only. They do not approve, judge, execute, or grant
  a browser privileged identity.
- English is the fallback label and Korean is a supported localized label. Machine ids remain
  stable English identifiers.

The loader in
[`workflow_apps.py`](../../services/core-control-plane/src/fdai/core/views/workflow_apps.py)
validates schema, duplicate ids, lifecycle, audience, and workflow/view cross-references.
