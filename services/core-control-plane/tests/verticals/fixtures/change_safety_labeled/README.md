# change_safety_labeled fixtures

Labeled Activity Log events used by
[`services/core-control-plane/tests/verticals/test_change_safety_detection_metrics.py`](../../test_change_safety_detection_metrics.py)
to establish the phase-1 out-of-band detection baseline:

> "Out-of-band detection reports precision and recall against a labeled
> fixture set, with the false-positive suppression rate recorded -
> establishing the detection baseline Phase 2 must not regress."

Every fixture is customer-agnostic (synthetic principals, no real
tenant/subscription/resource identifiers) per
[generic-scope.instructions.md](../../../../../../.github/instructions/generic-scope.instructions.md).

## Layout

- `label` - ground-truth attribution
  (`AUTHORIZED` / `SUPPRESSED` / `OUT_OF_BAND`).
- `event` - an `Event` payload matching the day-zero Activity Log wire
  contract (`signal_kind = azure.activity_log`, `resource.type`,
  optional `actor.principal_id`, optional `correlation_id`).
- `narrative` - one-line English description of the case.

The metric harness loads every JSON in this folder, feeds it through a
single :class:`ChangeSafetyDetector` configured with a fixed known-actor
set and known-correlation set (declared in
[`_labeled_config.json`](_labeled_config.json)), and asserts the
per-class confusion matrix.
