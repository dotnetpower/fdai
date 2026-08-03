# SRE Agent S1-S14 Execution Review

This review records the bounded S1-S14 validation campaign without retaining raw cloud identifiers,
resource names, endpoints, approval references, or operator-session details in the repository. The
tracked artifact is a sanitized summary; the full ledger and source document remain in private
external evidence storage.

> **Scope:** These results describe one disposable non-production campaign. They demonstrate the
> observed scenario outcomes and recovery evidence, not universal readiness for every topology.

## Outcome at a glance

The strict evidence review produced the following decisions:

| Decision | Count | Meaning |
|----------|------:|---------|
| Passed | 5 | Required signal and terminal closure were observed. |
| Partial | 7 | Injection or recovery completed, but one required signal or replay field was missing. |
| Blocked | 2 | A required safe prerequisite or current control-plane state was unavailable. |
| Failed | 0 | No scenario recorded an unrecovered execution failure. |

The S1-S12 fault subset contains 4 Passed, 7 Partial, and 1 Blocked decisions. S13 is Blocked
because the current scheduled-task projection is empty. S14 is Passed as a review-mode
investigation; it did not execute a mitigation.

## Scenario decisions

| ID | Decision | Retained evidence or gap |
|----|----------|--------------------------|
| S1 | Partial | Recovery was observed, but its exact completion timestamp was not captured. |
| S2 | Partial | CPU pressure was observed without the required throttling counter. |
| S3 | Passed | Latency shifted during injection and returned to baseline after cleanup. |
| S4 | Passed | Request abort behavior and HTTP recovery were observed. |
| S5 | Partial | Maximum platform CPU reached 83.58%, below the required greater-than-90% signal. |
| S6 | Partial | A bounded 400 MB variant ran, but the original memory and swap-pressure contract did not. |
| S7 | Partial | Cleanup was verified, but the successful final raw guest transcript is unavailable. |
| S8 | Blocked | A credential-safe load path and bounded database load runner were unavailable. |
| S9 | Partial | Rate limiting was observed, but the exact execution start timestamp was not captured. |
| S10 | Passed | Gateway backend first-byte latency exceeded five seconds and recovered. |
| S11 | Passed | Backend outage, gateway failure, and terminal recovery were observed. |
| S12 | Partial | Rollout failure and recovery were observed without exact execution and rollback timestamps. |
| S13 | Blocked | Previously observed scheduled tasks are absent from the current projection. |
| S14 | Passed | The alert-triggered investigation produced a grounded rate-limit cause in review mode. |

## Retention decision

The campaign artifacts are split by purpose:

- **Tracked summary:** The repository stores scenario IDs, decisions, bounded measurements,
  recovery and cleanup states, provenance digests, and the source-ledger SHA-256 digest.
- **Private bundle:** Raw command output, cloud identifiers, detailed approval context, and the
  source document remain outside the repository with restricted local permissions.
- **Canonical execution:** FDAI scenario execution remains owned by
  [`scripts/catalog/run-catalog-scenario.py`](../../scripts/catalog/run-catalog-scenario.py).
  One-off campaign runners are not a second execution path and are not tracked.
- **Validation:**
  [`validate-sre-scenario-evidence.py`](../../scripts/quality/repository/validate-sre-scenario-evidence.py)
  validates the full ledger before producing the tracked summary.

## Reproduce the summary

Run the validator from the repository root against a locally retained full ledger:

```bash
.venv/bin/python scripts/quality/repository/validate-sre-scenario-evidence.py \
  <private-ledger.json> \
  --summary-output \
  rule-catalog/chaos-scenarios/evidence/sre-agent-s1-s14-validation-summary.json
```

The command fails before writing a summary when the ledger is incomplete or inconsistent. The
summary generator intentionally omits targets, approval text, source identities, residual text,
and event payloads.

## Related artifacts

| To review | Read |
|-----------|------|
| Sanitized machine summary | [`sre-agent-s1-s14-validation-summary.json`](../../rule-catalog/chaos-scenarios/evidence/sre-agent-s1-s14-validation-summary.json) |
| Chaos catalog retention rules | [`rule-catalog/chaos-scenarios/README.md`](../../rule-catalog/chaos-scenarios/README.md) |
| Governed catalog runner | [`run-catalog-scenario.py`](../../scripts/catalog/run-catalog-scenario.py) |
