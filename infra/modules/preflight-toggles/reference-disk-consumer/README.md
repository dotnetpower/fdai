# Example: consuming the `disk_provisioning` toggle

A copy-paste reference showing how a fork wires the data-only
[`disk_provisioning`](../disk_provisioning/) toggle into a real
`azurerm_managed_disk` so the [Deployment Preflight active-reassembly
loop](../../../../docs/roadmap/deployment/preflight-active-reassembly.md) can flip the
plan from inline disk creation to attaching a pre-provisioned disk - resolving
a `deploy.disk_inline_creation_denied` policy blocker without ever emitting the
denied operation.

## The pattern

1. The toggle module stays data-only (`should_create_disk`, `disk_source_ids`).
2. The consumer wraps `count` around `should_create_disk` for the inline
   branch, and reads `disk_source_ids` for the attach branch.
3. The consumer never branches on the toggle NAME - it reads the outputs and
   picks the effective id set (`local.effective_disk_ids`).

When preflight reports the blocker, the reassembly loop accumulates
`disk_provisioning = "attach_existing"` (plus `existing_disk_ids`) as a tfvars
override and opens it as a fix PR through the
`remediate.apply-preflight-toggle` ActionType.

## Scope

Illustrative and **validate-only**. The upstream deploy does not instantiate
this module; a fork copies the branch into whichever compute module already
owns its VM / disk resources. See the
[toggle catalog README](../README.md) for the full toggle set.
